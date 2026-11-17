"""OrbitHub Digimode – Senden: Wellenformen, PTT, QSO-Ablauf, ADIF-Log.

Wird von digimode_server.py geladen. Sicherheitsregeln:
  * Probelauf (dry_run) ist die Voreinstellung: es wird nur die Wellenform
    erzeugt und mit dem Decoder zurückgeprüft – kein PTT, kein Ton.
  * Gesendet wird nur auf Bändern, die ausdrücklich freigegeben sind
    (tx_bands, Voreinstellung 2 m und 70 cm), nur wenn der IC-705 laut
    rigctld auf der Frequenz in USB/USB-D steht, und nur bei „TX frei“
    (Watchdog: nach 6 Minuten ohne Bedienung aus).
  * Not-Aus (halt) beendet sofort Ton und PTT.
  * PTT wird nach jeder Aussendung in einem finally-Block abgeschaltet,
    zusätzlich hat kappanhang eine eigene 3-Minuten-Abschaltung.
"""
from __future__ import annotations

import array
import math
import os
import random
import re
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RATE = 12000
TX_SINK = os.environ.get("TX_SINK", "kappanhang-IC-705")
WATCHDOG_SECONDS = 360
MAX_TRIES = 6
WSPR_DBM = (0, 3, 7, 10, 13, 17, 20, 23, 27, 30, 33, 37, 40, 43, 47, 50, 53, 57, 60)

# Sendebeginn relativ zum Periodenstart, spätester Start (sonst nächste Periode)
TX_TIMING = {
    # FT8: Decoder finden Signale bis DT ~2,5 s; auf vollem Band dauert die
    # Auswertung bis ~3 s -> spaeter Start bis 2,4 s (DT dann bis ~1,9 s)
    "FT8": {"offset": 0.5, "late": 2.4},
    "FT4": {"offset": 0.5, "late": 1.0},
    "WSPR": {"offset": 1.0, "late": 2.0},
}
PTT_LEAD = 0.25    # PTT so viel vor dem Ton einschalten
AUDIO_LEAD = 0.12  # Ton so viel früher starten (Pufferlaufzeit pacat/kappanhang)


# ----------------------------------------------------------- Wellenformen ---

def _gfsk_pulse(bt: float, t: float) -> float:
    c = math.pi * math.sqrt(2.0 / math.log(2.0))
    return 0.5 * (math.erf(c * bt * (t + 0.5)) - math.erf(c * bt * (t - 0.5)))


def gfsk_wave(tones: list[int], nsps: int, bt: float, f0: float, ft8_style: bool) -> list[float]:
    """Nachbau von WSJT-X gen_ft8wave (ft8_style) bzw. gen_ft4wave."""
    nsym = len(tones)
    twopi = 2 * math.pi
    dt = 1.0 / RATE
    pulse = [_gfsk_pulse(bt, (i - 1.5 * nsps) / nsps) for i in range(3 * nsps)]
    dphi_peak = twopi / nsps
    dphi = [0.0] * ((nsym + 2) * nsps)
    for j, tone in enumerate(tones):
        if tone:
            ib = j * nsps
            for i in range(3 * nsps):
                dphi[ib + i] += dphi_peak * pulse[i] * tone
    if ft8_style:
        # Hilfssymbole am Anfang/Ende mit erstem/letztem Ton
        for i in range(2 * nsps):
            dphi[i] += dphi_peak * tones[0] * pulse[nsps + i]
            dphi[nsym * nsps + i] += dphi_peak * tones[-1] * pulse[i]
    base = twopi * f0 * dt
    if ft8_style:
        start, nwave = nsps, nsym * nsps
    else:
        start, nwave = 0, (nsym + 2) * nsps
    wave = [0.0] * nwave
    phi = 0.0
    for k in range(nwave):
        wave[k] = math.sin(phi)
        phi = (phi + dphi[start + k] + base) % twopi
    nramp = round(nsps / 8) if ft8_style else nsps
    for i in range(nramp):
        up = (1 - math.cos(twopi * i / (2 * nramp))) / 2
        wave[i] *= up
        wave[nwave - nramp + i] *= (1 + math.cos(twopi * i / (2 * nramp))) / 2 if ft8_style else 1.0
    if not ft8_style:
        k1 = (nsym + 1) * nsps
        for i in range(nsps):
            wave[k1 + i] *= (1 + math.cos(twopi * i / (2 * nsps))) / 2
    return wave


def wspr_wave(symbols: list[int], f0: float) -> list[float]:
    nsps = 8192
    df = RATE / nsps
    wave = [0.0] * (len(symbols) * nsps)
    phi = 0.0
    k = 0
    for sym in symbols:
        dphi = 2 * math.pi * (f0 + (sym - 1.5) * df) / RATE
        for _ in range(nsps):
            wave[k] = math.sin(phi)
            phi = (phi + dphi) % (2 * math.pi)
            k += 1
    nramp = 120  # 10 ms weiche Flanken
    for i in range(nramp):
        g = (1 - math.cos(math.pi * i / nramp)) / 2
        wave[i] *= g
        wave[-1 - i] *= g
    return wave


def channel_symbols(mode: str, message: str, wsjtx_bin: Path, env: dict) -> list[int]:
    """Kanal-Symbole über die WSJT-X-Encoder; prüft, dass die Nachricht so
    kodierbar ist, wie sie gemeint ist."""
    if mode == "WSPR":
        out = subprocess.run([str(wsjtx_bin / "wsprsim"), "-c", message], capture_output=True,
                             text=True, timeout=10, env=env).stdout
        if "hannel symbols" not in out:
            raise ValueError(f"WSPR-Nachricht nicht kodierbar: {message}")
        syms = [int(x) for x in re.findall(r"\b[0-3]\b", out.split("hannel symbols", 1)[1])][:162]
        if len(syms) != 162:
            raise ValueError("WSPR-Kodierung unvollständig")
        return syms
    tool = "ft8code" if mode == "FT8" else "ft4code"
    out = subprocess.run([str(wsjtx_bin / tool), message], capture_output=True, text=True,
                         timeout=10, env=env).stdout
    lines = out.splitlines()
    row = next((ln for ln in lines if ln.strip().startswith("1.")), "")
    norm = " ".join(message.split())
    if "<" in norm:
        # gehashtes Rufzeichen: ft8code zeigt es als <...>, übrige Teile müssen stimmen
        plain = re.sub(r"<[^>]*>", " ", norm).split()
        ok = all(row.count(tok) >= 2 for tok in plain) and "<" in row
    else:
        ok = row.count(norm) >= 2
    if not ok:
        raise ValueError(f"„{message}“ lässt sich in {mode} nicht (unverändert) kodieren.")
    idx = next((i for i, ln in enumerate(lines) if "Channel symbols" in ln), None)
    if idx is None or idx + 2 >= len(lines):
        raise ValueError(f"{tool}: keine Kanal-Symbole")
    digits = [int(c) for c in lines[idx + 2] if c.isdigit()]
    if mode == "FT8":
        if len(digits) != 79:
            raise ValueError("FT8-Kodierung unvollständig")
        return digits
    if len(digits) != 105:
        raise ValueError("FT4-Kodierung unvollständig")
    return digits[1:-1]  # Rampensymbole


def build_samples(mode: str, message: str, df: float, level: float, wsjtx_bin: Path, env: dict) -> array.array:
    syms = channel_symbols(mode, message, wsjtx_bin, env)
    if mode == "FT8":
        wave = gfsk_wave(syms, 1920, 2.0, df, True)
    elif mode == "FT4":
        wave = gfsk_wave(syms, 576, 1.0, df, False)
    else:
        wave = wspr_wave(syms, df)
    amp = max(0.01, min(1.0, level)) * 32000
    return array.array("h", (int(amp * v) for v in wave))


# ---------------------------------------------------------- Nachrichten ---

def report(snr: int) -> str:
    snr = max(-30, min(30, int(snr)))
    return f"{snr:+03d}"


def _standard_call(call: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{1,3}[0-9][A-Z]{1,3}", call or ""))


def messages(me: str, grid4: str, his: str | None, rep_sent: str | None) -> dict:
    rep = rep_sent or "-10"
    if his and not _standard_call(his):
        # Präfix/Suffix-Rufzeichen (z. B. LX/PA1L): in FT8 gehasht als <LX/PA1L>,
        # zusammen mit dem eigenen Standardrufzeichen (ft8code-geprüft)
        h = f"<{his}>"
        return {
            "tx1": f"{h} {me} {grid4}", "tx2": f"{h} {me} {rep}", "tx3": f"{h} {me} R{rep}",
            "tx4": f"{h} {me} RR73", "tx5": f"{h} {me} 73", "tx6": f"CQ {me} {grid4}",
        }
    his = his or "<?>"
    return {
        "tx1": f"{his} {me} {grid4}",
        "tx2": f"{his} {me} {rep}",
        "tx3": f"{his} {me} R{rep}",
        "tx4": f"{his} {me} RR73",
        "tx5": f"{his} {me} 73",
        "tx6": f"CQ {me} {grid4}",
    }


REPORT_RE = re.compile(r"^[+-]\d{2}$")
RREPORT_RE = re.compile(r"^R[+-]\d{2}$")
GRID_RE = re.compile(r"^[A-R]{2}\d{2}$")


# ------------------------------------------------------------------ ADIF ---

def _adif_field(name: str, value) -> str:
    v = str(value)
    return f"<{name}:{len(v.encode('utf-8'))}>{v} "


def band_of(freq_hz: int) -> str:
    mhz = freq_hz / 1e6
    for lo, hi, b in ((1.8, 2.0, "160m"), (3.5, 4.0, "80m"), (5.3, 5.5, "60m"), (7.0, 7.3, "40m"),
                      (10.1, 10.15, "30m"), (14.0, 14.35, "20m"), (18.068, 18.168, "17m"),
                      (21.0, 21.45, "15m"), (24.89, 24.99, "12m"), (28.0, 29.7, "10m"), (50, 54, "6m"),
                      (144, 148, "2m"), (430, 440, "70cm")):
        if lo <= mhz <= hi:
            return b
    return ""


# ------------------------------------------------------------ Messwerte ---

def swr_from_raw(raw: int) -> float:
    pts = ((0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 6.0))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if raw <= x1:
            return round(y0 + (raw - x0) / (x1 - x0) * (y1 - y0), 2)
    return 6.0


def meter_reading(raw: dict) -> dict:
    """Rohwerte (0..255) -> Anzeige: Po in % (213 = 100 %), ALC in % des
    ALC-Bereichs (120 = 100 %), SWR als Verhältnis."""
    return {
        "ptt": bool(raw.get("ptt")),
        "po_pct": round(min(120.0, raw.get("po", 0) / 213 * 100), 1),
        "alc_pct": round(min(200.0, raw.get("alc", 0) / 120 * 100), 1),
        "swr": swr_from_raw(raw.get("swr", 0)),
        "po_raw": raw.get("po", 0), "alc_raw": raw.get("alc", 0), "swr_raw": raw.get("swr", 0),
    }


# --------------------------------------------------------------- Sender ---

class Transmitter:
    def __init__(self, engine) -> None:
        self.e = engine
        self.lock = threading.RLock()
        self.halt_event = threading.Event()
        self.plan: dict | None = None        # nächste Aussendung
        self.qso: dict | None = None
        self.transmitting = False
        self.sending: str | None = None
        self.ptt = False
        self.last_tx: dict | None = None
        self.last_error: str | None = None
        self.armed_until = 0.0
        self.tx_slots: set[float] = set()     # echte Aussendungen (Perioden nicht dekodieren)
        self.proc: subprocess.Popen | None = None
        self.wspr_decided: float = 0.0
        self.log_path = self.e.log_dir / "orbithub.adi"
        self.meter: dict | None = None        # letzte Live-Messung (während TX)
        self.last_meters: dict | None = None  # Zusammenfassung der letzten Aussendung
        threading.Thread(target=self._run, name="tx", daemon=True).start()

    # -- Einstellungen
    @property
    def cfg(self) -> dict:
        return self.e.cfg

    def tx_enabled(self) -> bool:
        if self.cfg.get("tx_enabled") and time.time() > self.armed_until:
            self.cfg["tx_enabled"] = False
            self.last_error = "Watchdog: 6 Minuten ohne Bedienung – TX abgeschaltet."
            self.plan = None
        return bool(self.cfg.get("tx_enabled"))

    def touch(self) -> None:
        self.armed_until = time.time() + WATCHDOG_SECONDS

    def configure(self, data: dict) -> None:
        cfg = self.cfg
        if "tx_bands" in data and isinstance(data["tx_bands"], list):
            cfg["tx_bands"] = [str(b) for b in data["tx_bands"]][:20]
        if "dry_run" in data:
            cfg["dry_run"] = bool(data["dry_run"])
        if "tx_df" in data:
            cfg["tx_df"] = max(200, min(2900, int(float(data["tx_df"]))))
        if "tx_level" in data:
            cfg["tx_level"] = max(0.02, min(1.0, float(data["tx_level"])))
            if cfg.get("auto_level", True):
                # Hand-Eingabe gilt als Startwert für das aktuelle Band
                levels = dict(cfg.get("tx_levels") or {})
                levels[cfg.get("band", "")] = cfg["tx_level"]
                cfg["tx_levels"] = levels
        if "auto_level" in data:
            cfg["auto_level"] = bool(data["auto_level"])
        if "wspr_beacon" in data:
            cfg["wspr_beacon"] = bool(data["wspr_beacon"])
            if cfg["wspr_beacon"]:
                self.last_error = None
        if "wspr_pct" in data:
            cfg["wspr_pct"] = max(0, min(100, int(data["wspr_pct"])))
        if "wspr_dbm" in data:
            dbm = int(data["wspr_dbm"])
            if dbm not in WSPR_DBM:
                raise ValueError("WSPR-Leistung muss einer der Werte 0, 3, 7, 10 … 60 dBm sein.")
            cfg["wspr_dbm"] = dbm
        if "tx_enabled" in data:
            cfg["tx_enabled"] = bool(data["tx_enabled"])
            if cfg["tx_enabled"]:
                self.touch()
                self.last_error = None
                self._replan()
            else:
                self.plan = None
        self.e.save()

    # -- Hilfen
    def me(self) -> tuple[str, str]:
        return self.cfg.get("call", ""), (self.cfg.get("grid", "") or "")[:4]

    def period(self) -> float:
        return {"FT8": 15.0, "FT4": 7.5, "WSPR": 120.0}[self.cfg["mode"]]

    def parity(self, slot_start: float) -> int:
        return int(round(slot_start / self.period())) % 2

    def level(self) -> float:
        """Sendepegel: bei Auto-Pegel der gelernte Wert für das Band."""
        if self.cfg.get("auto_level", True):
            return float((self.cfg.get("tx_levels") or {}).get(self.cfg.get("band", ""), self.cfg.get("tx_level", 0.3)))
        return float(self.cfg.get("tx_level", 0.3))

    def _read_meters(self) -> dict | None:
        try:
            with socket.create_connection(self.e.rigctld, timeout=1) as sock:
                sock.settimeout(1)
                sock.sendall(b"l METERS\n")
                parts = sock.recv(128).decode(errors="replace").split()
            if len(parts) >= 4 and all(p.isdigit() for p in parts[:4]):
                return {"ptt": int(parts[0]), "po": int(parts[1]), "alc": int(parts[2]), "swr": int(parts[3]),
                        "age": float(parts[4]) if len(parts) > 4 else 0.0, "t": time.time()}
        except (OSError, ValueError):
            pass
        return None

    def _auto_adjust(self, samples: list[dict]) -> str | None:
        """Pegel nach der Aussendung nachführen: Ziel ist volle Leistung bei
        kaum ausschlagender ALC (wie die Auto-Pegelung in SDR-Control)."""
        if not self.cfg.get("auto_level", True) or len(samples) < 3:
            return None
        alc = [m["alc"] for m in samples]
        alc_avg = sum(alc) / len(alc)
        alc_max = max(alc)
        old = self.level()
        if alc_max > 90 or alc_avg > 40:
            new = old * 0.7
        elif alc_avg > 12:
            new = old * 0.85
        elif alc_max < 2:
            new = old * 1.2
        else:
            return None  # ALC knapp im Bereich – passt
        new = round(max(0.03, min(0.9, new)), 3)
        if abs(new - old) < 0.005:
            return None
        levels = dict(self.cfg.get("tx_levels") or {})
        levels[self.cfg.get("band", "")] = new
        self.cfg["tx_levels"] = levels
        self.e.save()
        return f"Pegel {round(old * 100)} % → {round(new * 100)} %"

    def band_allowed(self) -> bool:
        return self.cfg.get("band") in (self.cfg.get("tx_bands") or [])

    def next_slot(self, parity: int, earliest: float | None = None) -> float:
        p = self.period()
        late = TX_TIMING[self.cfg["mode"]]["late"]
        now = time.time() if earliest is None else earliest
        s = math.floor(now / p) * p
        if now - s > late:
            s += p
        while self.parity(s) != parity:
            s += p
        return s

    def msgs(self) -> dict:
        me, grid4 = self.me()
        q = self.qso or {}
        return messages(me, grid4, q.get("call"), q.get("rep_sent"))

    # -- Bedienung
    def halt(self, reason: str = "STOP") -> None:
        with self.lock:
            self.cfg["tx_enabled"] = False
            self.cfg["wspr_beacon"] = False if reason == "STOP" else self.cfg.get("wspr_beacon")
            self.plan = None
        self.halt_event.set()
        proc = self.proc
        if proc and proc.poll() is None:
            proc.kill()
        self._ptt(False)
        self.last_error = reason
        self.e.save()

    def start_cq(self) -> None:
        self._require_ft()
        me, grid4 = self.me()
        if not me or not grid4:
            raise ValueError("Rufzeichen/Locator fehlen.")
        with self.lock:
            par = self._parity_of_next()
            self.qso = {"call": None, "grid": None, "state": "cq", "tx": "tx6", "parity": par,
                        "rep_sent": None, "rep_rcvd": None, "tries": 0, "started": time.time(),
                        "logged": False, "cq": True}
            self.cfg["tx_enabled"] = True
            self.touch()
            self.last_error = None
            self._replan()

    def _parity_of_next(self) -> int:
        p = self.period()
        now = time.time()
        s = math.floor(now / p) * p
        if now - s > TX_TIMING[self.cfg["mode"]]["late"]:
            s += p
        return self.parity(s)

    def call_station(self, decode: dict) -> None:
        """Antwort auf eine angeklickte Dekodierung (wie Doppelklick in WSJT-X)."""
        self._require_ft()
        me, _ = self.me()
        his = decode.get("call")
        if not his or his == me or decode.get("hashed"):
            raise ValueError("Diese Zeile enthält kein verwendbares Rufzeichen.")
        slot = datetime.fromisoformat(decode["utc"].replace("Z", "+00:00")).timestamp()
        with self.lock:
            q = self.qso
            if q and q.get("call") == his and q["state"] not in ("done",) and decode.get("to") != me:
                # erneuter Doppelklick auf dieselbe Station: QSO nicht von vorn beginnen
                self.cfg["tx_enabled"] = True
                self.touch()
                self.last_error = None
                if not self.plan:
                    self._replan()
                return
            self.qso = {"call": his, "grid": decode.get("grid"), "state": "call", "tx": "tx1",
                        "parity": self.parity(slot) ^ 1, "rep_sent": report(decode["snr"]),
                        "rep_rcvd": None, "tries": 0, "started": time.time(), "logged": False,
                        "cq": False, "freq_hz": decode.get("freq_hz"), "country": decode.get("country"),
                        "rx_snr": decode.get("snr")}
            if decode.get("to") == me:
                self._react(decode)
            self.cfg["tx_enabled"] = True
            self.touch()
            self.last_error = None
            self._replan()

    def choose(self, key: str) -> None:
        if key not in ("tx1", "tx2", "tx3", "tx4", "tx5", "tx6"):
            raise ValueError("unbekannte Nachricht")
        with self.lock:
            if not self.qso:
                raise ValueError("Kein QSO aktiv.")
            self.qso["tx"] = key
            self.qso["tries"] = 0
            self.touch()
            self._replan()

    def clear_qso(self) -> None:
        with self.lock:
            self.qso = None
            self.plan = None

    def _require_ft(self) -> None:
        if not self.cfg.get("running") or self.cfg.get("mode") not in ("FT8", "FT4"):
            raise ValueError("Erst FT8- oder FT4-Empfang starten.")

    # -- QSO-Ablauf
    def _react(self, d: dict) -> None:
        """Nachricht des Partners an mich auswerten -> nächste eigene Nachricht."""
        q = self.qso
        words = d["message"].replace("<", "").replace(">", "").split()
        last = words[2] if len(words) >= 3 else ""
        q["call"] = q.get("call") or d.get("call")
        q["country"] = q.get("country") or d.get("country")
        q["rx_snr"] = d.get("snr")
        if d.get("grid"):
            q["grid"] = d["grid"]
        if q.get("rep_sent") is None:
            q["rep_sent"] = report(d["snr"])
        old = q["tx"]
        if last in ("RR73", "RRR"):                # er bestätigt -> 73 (vor GRID prüfen: RR73 sieht aus wie ein Locator)
            q["tx"], q["state"] = "tx5", "73"
        elif GRID_RE.match(last):                  # er ruft mich (Tx1) -> Rapport
            q["tx"], q["state"] = "tx2", "report"
        elif REPORT_RE.match(last):                # er gibt Rapport -> R+Rapport
            q["rep_rcvd"] = last
            q["tx"], q["state"] = "tx3", "rreport"
        elif RREPORT_RE.match(last):               # er bestätigt -> RR73, QSO fertig
            q["rep_rcvd"] = last[1:]
            q["tx"], q["state"] = "tx4", "rr73"
        elif last == "73":
            if q["state"] in ("rr73", "73", "done"):
                q["state"] = "done"
                self._log_qso()
            else:
                q["tx"], q["state"] = "tx5", "73"
        q["last_heard"] = time.time()
        if q["tx"] != old or q["tx"] in ("tx4", "tx5"):
            q["tries"] = 0  # neue Nachricht oder Wiederholungswunsch des Partners

    def after_cycle(self, slot_start: float, decodes: list[dict]) -> None:
        """Nach jeder (auch übersprungenen) Auswertung einer Periode."""
        if self.cfg.get("mode") not in ("FT8", "FT4"):
            return
        with self.lock:
            q = self.qso
            if not q or q["state"] == "done":
                return
            if self.parity(slot_start) == q["parity"]:
                return  # eigene Sendeperiode
            me, _ = self.me()
            to_me = [d for d in decodes if d.get("to") == me and d.get("call") and not d.get("tx")]
            if q.get("call"):
                to_me = [d for d in to_me if d["call"] == q["call"]]
            if to_me:
                best = max(to_me, key=lambda d: d["snr"])
                if q["state"] == "cq":
                    q["call"] = best["call"]
                    q["cq"] = True
                self._react(best)
            if q["state"] == "done":
                self.plan = None
                return
            if self.tx_enabled():
                self._plan_for(slot_start + self.period())

    def _replan(self) -> None:
        q = self.qso
        if not q or q["state"] == "done" or not self.tx_enabled():
            self.plan = None
            return
        self._plan_for(self.next_slot(q["parity"]))

    def _plan_for(self, slot: float) -> None:
        q = self.qso
        if q["tx"] in ("tx4", "tx5") and q["tries"] >= 1:
            # RR73/73 nur einmal senden (wie WSJT-X); wiederholt der Partner, kommt _react
            self._log_qso()
            q["state"] = "done"
            self.cfg["tx_enabled"] = False
            self.plan = None
            self.last_error = f"QSO mit {q.get('call')} beendet" + ("" if self.cfg.get("dry_run") else " und geloggt") + "."
            return
        if q["tx"] != "tx6" and q["tries"] >= MAX_TRIES:
            self.last_error = f"Keine Antwort von {q.get('call')} nach {MAX_TRIES} Versuchen – TX gestoppt."
            self.cfg["tx_enabled"] = False
            self.plan = None
            return
        msg = self.msgs()[q["tx"]]
        self.plan = {"slot": slot, "mode": self.cfg["mode"], "message": msg, "key": q["tx"],
                     "df": float(self.cfg.get("tx_df", 1500))}

    def _log_qso(self) -> None:
        q = self.qso
        if not q or q.get("logged") or not q.get("call"):
            return
        q["logged"] = True
        if self.cfg.get("dry_run"):
            return  # im Probelauf gibt es keine echten QSOs
        me, _ = self.me()
        now = datetime.now(timezone.utc)
        start = datetime.fromtimestamp(q["started"], timezone.utc)
        dial = int(self.cfg["dial_hz"])
        freq = dial + int(self.cfg.get("tx_df", 1500))
        mode = self.cfg["mode"]
        rec = "".join([
            _adif_field("CALL", q["call"]),
            _adif_field("GRIDSQUARE", q.get("grid") or ""),
            _adif_field("MODE", "FT8") if mode == "FT8" else _adif_field("MODE", "MFSK") + _adif_field("SUBMODE", "FT4"),
            _adif_field("RST_SENT", q.get("rep_sent") or ""),
            _adif_field("RST_RCVD", q.get("rep_rcvd") or ""),
            _adif_field("QSO_DATE", start.strftime("%Y%m%d")),
            _adif_field("TIME_ON", start.strftime("%H%M%S")),
            _adif_field("QSO_DATE_OFF", now.strftime("%Y%m%d")),
            _adif_field("TIME_OFF", now.strftime("%H%M%S")),
            _adif_field("BAND", band_of(dial)),
            _adif_field("FREQ", f"{freq / 1e6:.6f}"),
            _adif_field("STATION_CALLSIGN", me),
            _adif_field("MY_GRIDSQUARE", self.cfg.get("grid", "")),
            "<EOR>\n",
        ])
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.log_path.exists()
        with self.log_path.open("a", encoding="utf-8") as fh:
            if new:
                fh.write("OrbitHub ADIF Export\n" + _adif_field("ADIF_VER", "3.1.4")
                         + _adif_field("PROGRAMID", "OrbitHub") + "<EOH>\n")
            fh.write(rec)

    def log_entries(self) -> list[dict]:
        try:
            text = self.log_path.read_text(encoding="utf-8")
        except OSError:
            return []
        body = text.split("<EOH>", 1)[-1]
        out = []
        for rec in body.split("<EOR>"):
            fields = dict((m.group(1).upper(), m.group(3)) for m in re.finditer(r"<(\w+):(\d+)>([^<]*?)\s*(?=<|$)", rec))
            if fields.get("CALL"):
                out.append(fields)
        return out[::-1]

    # -- Aussenden
    def _ptt(self, on: bool) -> bool:
        for _ in range(2 if not on else 1):
            try:
                with socket.create_connection(self.e.rigctld, timeout=2) as sock:
                    sock.sendall(f"T {1 if on else 0}\n".encode())
                    reply = sock.recv(64).decode(errors="replace").strip()
                ok = reply == "RPRT 0"
                self.ptt = on if ok else self.ptt
                if ok:
                    return True
            except OSError:
                pass
        if not on:
            self.ptt = False
        return False

    def _run(self) -> None:
        while True:
            time.sleep(0.05)
            try:
                self._maybe_wspr()
                plan = self.plan
                if not plan:
                    continue
                t_start = plan["slot"] + TX_TIMING[plan["mode"]]["offset"]
                if time.time() < t_start - PTT_LEAD - 0.05:
                    continue
                with self.lock:
                    if self.plan is not plan:
                        continue
                    self.plan = None
                if time.time() > plan["slot"] + TX_TIMING[plan["mode"]]["late"]:
                    # zu spät für diese Periode -> nächste eigene Periode statt verwerfen
                    if plan["key"] != "wspr" and self.qso and self.tx_enabled():
                        with self.lock:
                            if self.plan is None:
                                self.plan = {**plan, "slot": plan["slot"] + 2 * self.period()}
                    continue
                self._transmit(plan)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"TX-Fehler: {exc} – TX abgeschaltet."
                self.cfg["tx_enabled"] = False
                self.plan = None
                self._ptt(False)

    def _maybe_wspr(self) -> None:
        cfg = self.cfg
        if cfg.get("mode") != "WSPR" or not cfg.get("running") or not cfg.get("wspr_beacon") or self.plan:
            return
        now = time.time()
        nxt = math.floor(now / 120) * 120 + 120
        if nxt - now > 3 or self.wspr_decided == nxt:
            return
        self.wspr_decided = nxt
        if random.random() * 100 >= cfg.get("wspr_pct", 20):
            return
        me, grid4 = self.me()
        df = 1500 + random.randint(-80, 80)
        self.plan = {"slot": nxt, "mode": "WSPR", "message": f"{me} {grid4} {cfg.get('wspr_dbm', 37)}",
                     "key": "wspr", "df": float(df)}

    def _check_allowed(self, plan: dict) -> str | None:
        if not self.cfg.get("running") or self.cfg.get("mode") != plan["mode"]:
            return "Empfang/Betriebsart hat gewechselt."
        if not self.band_allowed():
            return f"Senden auf {self.cfg.get('band') or '?'} nicht freigegeben (Antenne?)."
        if plan["mode"] != "WSPR" and not self.tx_enabled():
            return "TX nicht freigegeben."
        self.e.rig.poll()
        if not self.e.rig.on_frequency(int(self.cfg["dial_hz"])):
            return "IC-705 steht nicht auf der Frequenz in USB-D – nicht gesendet."
        return None

    def _transmit(self, plan: dict) -> None:
        mode = plan["mode"]
        dry = bool(self.cfg.get("dry_run", True))
        reason = None if dry else self._check_allowed(plan)
        if dry and plan["mode"] != "WSPR" and not self.tx_enabled():
            reason = "TX nicht freigegeben."
        if reason:
            self.last_error = reason
            if plan["key"] != "wspr":
                self.cfg["tx_enabled"] = False
            self._record(plan, ok=False, note=reason)
            return
        samples = build_samples(mode, plan["message"], plan["df"], self.level(),
                                self.e.wsjtx_bin, self.e.env())
        if self.qso and plan["key"] != "wspr":
            self.qso["tries"] += 1
            if plan["key"] == "tx4":
                self._log_qso()
        if dry:
            threading.Thread(target=self._selfcheck, args=(plan, samples), daemon=True).start()
            return
        self.halt_event.clear()
        t_audio = plan["slot"] + TX_TIMING[mode]["offset"] - AUDIO_LEAD
        self.transmitting = True
        self.sending = plan["message"]
        self.tx_slots.add(plan["slot"])
        note = "gesendet"
        meters: list[dict] = []
        try:
            if not self._ptt(True):
                raise RuntimeError("PTT ließ sich nicht einschalten.")
            while time.time() < t_audio and not self.halt_event.is_set():
                time.sleep(0.005)
            if self.halt_event.is_set():
                note = "STOP"
                return
            self.proc = subprocess.Popen(
                ["pacat", "--playback", f"--device={TX_SINK}", f"--rate={RATE}", "--channels=1",
                 "--format=s16le", "--raw", "--latency-msec=60", "--client-name=OrbitHub-TX"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert self.proc.stdin is not None
            try:
                self.proc.stdin.write(samples.tobytes())
                self.proc.stdin.close()
            except BrokenPipeError:
                pass
            deadline = time.time() + len(samples) / RATE + 2.0
            next_meter = time.time() + 1.0  # erste Sekunde (Einschwingen) auslassen
            while self.proc.poll() is None and time.time() < deadline and not self.halt_event.is_set():
                if time.time() >= next_meter:
                    m = self._read_meters()
                    next_meter = time.time() + 0.4
                    if m and m["ptt"] and m["age"] < 1.5:
                        meters.append(m)
                        self.meter = meter_reading(m)
                time.sleep(0.02)
            if self.proc.poll() is None:
                self.proc.kill()
                note = "abgebrochen (Zeitlimit)"
            if self.halt_event.is_set():
                note = "STOP – abgebrochen"
        except Exception as exc:  # noqa: BLE001
            note = f"Fehler: {exc}"
            self.last_error = note
        finally:
            self._ptt(False)
            self.transmitting = False
            self.proc = None
            adj = None
            if meters:
                self.last_meters = {
                    "utc": self.e.iso(plan["slot"]), "band": self.cfg.get("band"),
                    "level": round(self.level(), 3), "n": len(meters),
                    "max": meter_reading({"po": max(m["po"] for m in meters), "alc": max(m["alc"] for m in meters),
                                          "swr": max(m["swr"] for m in meters)}),
                    "avg": meter_reading({"po": round(sum(m["po"] for m in meters) / len(meters)),
                                          "alc": round(sum(m["alc"] for m in meters) / len(meters)),
                                          "swr": round(sum(m["swr"] for m in meters) / len(meters))}),
                }
                if note == "gesendet":
                    adj = self._auto_adjust(meters)
                    self.last_meters["adjust"] = adj
            self.meter = None
            self._record(plan, ok=note == "gesendet", note=note + (f" · {adj}" if adj else ""))

    def start_test(self, seconds: float = 5.0) -> None:
        """SWR-Test: ein paar Sekunden Dauerton auf der TX-Frequenz, Po/ALC/SWR messen."""
        seconds = max(2.0, min(10.0, float(seconds)))
        if self.transmitting:
            raise ValueError("Es wird gerade gesendet.")
        if self.cfg.get("dry_run", True):
            raise ValueError("Probelauf ist an – der Test sendet echt. Erst den Probelauf ausschalten.")
        if not self.cfg.get("running"):
            raise ValueError("Empfang ist aus – erst Betriebsart und Band starten.")
        if not self.band_allowed():
            raise ValueError(f"Senden auf {self.cfg.get('band') or '?'} nicht freigegeben (Antenne?).")
        plan = self.plan
        if plan and plan["slot"] - time.time() < seconds + 2:
            raise ValueError("Gleich steht eine Aussendung an – Test danach.")
        self.e.rig.poll()
        if not self.e.rig.on_frequency(int(self.cfg["dial_hz"])):
            raise ValueError("IC-705 steht nicht auf der Frequenz in USB-D.")
        threading.Thread(target=self._run_test, args=(seconds,), daemon=True).start()

    def _run_test(self, seconds: float) -> None:
        df = float(self.cfg.get("tx_df", 1500))
        level = self.level()
        n = int(seconds * RATE)
        ramp = int(0.02 * RATE)
        samples = array.array("h", bytes(2 * n))
        for i in range(n):
            a = min(1.0, i / ramp, (n - 1 - i) / ramp)
            samples[i] = int(32767 * level * a * math.sin(2 * math.pi * df * i / RATE))
        t0 = time.time()
        plan = {"mode": self.cfg.get("mode", "FT8"), "slot": t0, "df": df,
                "message": f"SWR-Test · Dauerton {int(df)} Hz · {seconds:.0f} s", "key": "test"}
        self.halt_event.clear()
        self.transmitting = True
        self.sending = plan["message"]
        note = "SWR-Test gesendet"
        meters: list[dict] = []
        try:
            if not self._ptt(True):
                raise RuntimeError("PTT ließ sich nicht einschalten.")
            time.sleep(0.15)
            self.proc = subprocess.Popen(
                ["pacat", "--playback", f"--device={TX_SINK}", f"--rate={RATE}", "--channels=1",
                 "--format=s16le", "--raw", "--latency-msec=60", "--client-name=OrbitHub-Test"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert self.proc.stdin is not None
            try:
                self.proc.stdin.write(samples.tobytes())
                self.proc.stdin.close()
            except BrokenPipeError:
                pass
            deadline = time.time() + seconds + 2.0
            next_meter = time.time() + 0.8
            while self.proc.poll() is None and time.time() < deadline and not self.halt_event.is_set():
                if time.time() >= next_meter:
                    m = self._read_meters()
                    next_meter = time.time() + 0.3
                    if m and m["ptt"] and m["age"] < 1.5:
                        meters.append(m)
                        self.meter = meter_reading(m)
                time.sleep(0.02)
            if self.proc.poll() is None:
                self.proc.kill()
            if self.halt_event.is_set():
                note = "SWR-Test – STOP"
        except Exception as exc:  # noqa: BLE001
            note = f"SWR-Test Fehler: {exc}"
            self.last_error = note
        finally:
            self._ptt(False)
            self.transmitting = False
            self.sending = None
            self.proc = None
            if meters:
                mx = meter_reading({"po": max(m["po"] for m in meters), "alc": max(m["alc"] for m in meters),
                                    "swr": max(m["swr"] for m in meters)})
                self.last_meters = {
                    "utc": self.e.iso(t0), "band": self.cfg.get("band"), "level": round(level, 3),
                    "n": len(meters), "test": True, "max": mx,
                    "avg": meter_reading({"po": round(sum(m["po"] for m in meters) / len(meters)),
                                          "alc": round(sum(m["alc"] for m in meters) / len(meters)),
                                          "swr": round(sum(m["swr"] for m in meters) / len(meters))}),
                }
                note += f" · SWR {mx['swr']:.1f} : 1 · Po {mx['po_pct']:.0f} % · ALC {mx['alc_pct']:.0f} %".replace(".", ",")
            else:
                note += " · keine Messwerte"
            self.meter = None
            self._record(plan, ok=note.startswith("SWR-Test gesendet"), note=note)

    def _selfcheck(self, plan: dict, samples: array.array) -> None:
        """Probelauf: erzeugte Aussendung mit dem eigenen Decoder zurücklesen."""
        mode = plan["mode"]
        length = 120.0 if mode == "WSPR" else (15.0 if mode == "FT8" else 7.5)
        buf = array.array("h", bytes(int(length * RATE) * 2))
        off = int(TX_TIMING[mode]["offset"] * RATE)
        n = min(len(samples), len(buf) - off)
        buf[off:off + n] = samples[:n]
        st = datetime.fromtimestamp(plan["slot"], timezone.utc)
        name = st.strftime("%y%m%d_%H%M") if mode == "WSPR" else st.strftime("%y%m%d_%H%M%S")
        found = False
        try:
            with tempfile.TemporaryDirectory(dir=str(self.e.work_dir)) as tmp:
                wav = Path(tmp) / f"{name}.wav"
                self.e.write_wav(wav, buf)
                lines = self.e.run_decoder(mode, wav, int(self.cfg["dial_hz"]), "", "")
            want = " ".join(plan["message"].split())
            found = any(want in " ".join(ln.split()) for ln in lines)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"Selbsttest: {exc}"
        self._record(plan, ok=found, note="Probelauf – Selbsttest " + ("bestanden" if found else "NICHT bestanden"))

    def _record(self, plan: dict, ok: bool, note: str) -> None:
        dial = int(self.cfg.get("dial_hz") or 0)
        entry = {
            "tx": True, "mode": plan["mode"], "utc": self.e.iso(plan["slot"]), "snr": 0, "dt": 0.0,
            "df": int(plan["df"]), "freq_hz": dial + int(plan["df"]), "message": plan["message"],
            "call": None, "grid": None, "cq": False, "to": None, "hashed": False,
            "tx_ok": ok, "tx_note": note, "dry_run": bool(self.cfg.get("dry_run", True)),
        }
        self.last_tx = {k: entry[k] for k in ("utc", "message", "tx_ok", "tx_note", "dry_run")}
        self.e.add_entries([entry])

    def status(self) -> dict:
        q = dict(self.qso) if self.qso else None
        plan = self.plan
        return {
            "enabled": self.tx_enabled(),
            "armed_left": max(0, int(self.armed_until - time.time())) if self.cfg.get("tx_enabled") else 0,
            "dry_run": bool(self.cfg.get("dry_run", True)),
            "tx_bands": self.cfg.get("tx_bands", []),
            "band_ok": self.band_allowed(),
            "df": self.cfg.get("tx_df", 1500), "level": round(self.level(), 3),
            "auto_level": bool(self.cfg.get("auto_level", True)),
            "meter": self.meter, "last_meters": self.last_meters,
            "wspr_beacon": bool(self.cfg.get("wspr_beacon")), "wspr_pct": self.cfg.get("wspr_pct", 20),
            "wspr_dbm": self.cfg.get("wspr_dbm", 37),
            "transmitting": self.transmitting, "ptt": self.ptt,
            "sending": self.sending if self.transmitting else None,
            "qso": q, "messages": self.msgs(),
            "next": {"utc": self.e.iso(plan["slot"]), "message": plan["message"], "key": plan["key"]} if plan else None,
            "last": self.last_tx, "error": self.last_error,
        }
