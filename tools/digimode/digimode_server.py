#!/usr/bin/env python3
"""OrbitHub – Digimode-Dienst für FT8, FT4 und WSPR (Empfang).

Läuft auf dem HOST (nicht im Docker-Container), weil nur dort die
PipeWire-Quelle von kappanhang („kappanhang-IC-705“) und rigctld (:4532)
direkt erreichbar sind – gleiches Muster wie audio_stream_server.py.

Ablauf:
  parec (12 kHz, mono) -> Ringpuffer mit Zeitbezug -> am Ende jeder
  Periode (FT8 15 s, FT4 7,5 s, WSPR 120 s) eine WAV-Datei -> WSJT-X-
  Decoder jt9 bzw. wsprd -> Liste der Dekodierungen (+ Tageslog JSONL)
  -> optional Spots an PSK Reporter (FT8/FT4) und WSPRnet (WSPR).

Spots werden nur gemeldet, wenn der IC-705 laut rigctld wirklich auf der
eingestellten Frequenz in USB/USB-D steht (sonst wären die QRG falsch).

HTTP-API (JSON, Port 8767):
  GET  /status                 Zustand, Audio, Gerät, Upload-Zähler
  GET  /decodes?since=N        Dekodierungen mit seq > N (max. 500)
  POST /start  {mode, dial_hz, band, call, grid, upload_psk, upload_wsprnet}
  POST /stop
  POST /config {upload_psk, upload_wsprnet, call, grid}

Nur Python-Standardbibliothek. WSJT-X-Programme (jt9, wsprd) aus
WSJTX_BIN (Standard: ~/digimode/pkg/root/usr/bin, siehe install.sh).
"""
from __future__ import annotations

import array
import collections
import glob
import json
import logging
import math
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import digimode_cty
import digimode_tx

VERSION = "1.1"
HOME = Path.home()
BASE_DIR = Path(os.environ.get("DIGIMODE_DIR", str(HOME / "digimode")))
WSJTX_BIN = Path(os.environ.get("WSJTX_BIN", str(BASE_DIR / "pkg/root/usr/bin")))
WSJTX_LIB = os.environ.get("WSJTX_LIB") or ":".join(
    sorted({str(Path(p).parent) for p in glob.glob(str(BASE_DIR / "pkg/root/usr/lib/*/libgfortran.so*"))})
)
SOURCE = os.environ.get("AUDIO_SOURCE", "kappanhang-IC-705")
PORT = int(os.environ.get("DIGIMODE_PORT", "8767"))
RIGCTLD = (os.environ.get("RIGCTLD_HOST", "127.0.0.1"), int(os.environ.get("RIGCTLD_PORT", "4532")))
STATE_FILE = BASE_DIR / "state.json"
LOG_DIR = BASE_DIR / "log"
WORK_DIR = BASE_DIR / "work"

RATE = 12000
LATENCY = 0.10  # parec --latency-msec, Näherung für die Verzögerung im Puffer
RING_SECONDS = 150

MODES = {
    # Periode, Länge der Aufnahme, Auswertung ab Sekunde x der Periode (früh,
    # damit eine Antwort noch in der nächsten Periode gesendet werden kann)
    "FT8": {"period": 15.0, "length": 15.0, "decode_at": 13.3},
    "FT4": {"period": 7.5, "length": 7.5, "decode_at": 6.0},
    "WSPR": {"period": 120.0, "length": 120.0, "decode_at": 120.0},
}

PSK_HOST = ("report.pskreporter.info", 4739)
PSK_FLUSH_SECONDS = 300
PSK_DEDUP_SECONDS = 1800
WSPRNET_URL = "http://wsprnet.org/post"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("digimode")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- Audio ---

class AudioRing:
    """Ringpuffer der letzten RING_SECONDS Sekunden mit Abbildung Zeit -> Sample."""

    def __init__(self) -> None:
        self.cap = RATE * RING_SECONDS
        self.buf = array.array("h", bytes(self.cap * 2))
        self.total = 0  # bisher geschriebene Samples
        self.lock = threading.Lock()
        self._t0_window: collections.deque = collections.deque()
        self.t0: float | None = None  # Systemzeit von Sample 0
        self.last_chunk = 0.0
        self.level_dbfs: float | None = None
        self.proc: subprocess.Popen | None = None
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- Lesen von parec
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()

    def _run(self) -> None:
        while not self._stop.is_set():
            cmd = [
                "parec", f"--device={SOURCE}", f"--rate={RATE}", "--channels=1",
                "--format=s16le", "--raw", f"--latency-msec={int(LATENCY * 1000)}",
                "--client-name=OrbitHub-Digimode",
            ]
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as exc:
                self.error = f"parec nicht startbar: {exc}"
                log.error(self.error)
                self._stop.wait(5)
                continue
            with self.lock:
                # neuer Datenstrom: Zeitbezug neu aufbauen (Lücke bleibt Stille)
                self._t0_window.clear()
            stream = self.proc.stdout
            assert stream is not None
            chunk_bytes = RATE // 10 * 2  # 100 ms
            pending = b""
            while not self._stop.is_set():
                data = stream.read1(chunk_bytes) if hasattr(stream, "read1") else stream.read(chunk_bytes)
                if not data:
                    break
                data = pending + data
                if len(data) % 2:
                    pending, data = data[-1:], data[:-1]
                else:
                    pending = b""
                self._write(data, time.time())
            err = b""
            try:
                self.proc.terminate()
                err = self.proc.stderr.read() if self.proc.stderr else b""
            except Exception:  # noqa: BLE001
                pass
            if not self._stop.is_set():
                self.error = "Audio-Strom abgebrochen" + (f": {err.decode(errors='replace').strip()[:200]}" if err else "")
                log.warning(self.error)
                self._stop.wait(3)

    def _write(self, data: bytes, arrival: float) -> None:
        samples = array.array("h")
        samples.frombytes(data)
        n = len(samples)
        if not n:
            return
        with self.lock:
            pos = self.total % self.cap
            first = min(n, self.cap - pos)
            self.buf[pos:pos + first] = samples[:first]
            if first < n:
                self.buf[0:n - first] = samples[first:]
            self.total += n
            # Zeit von Sample 0 schätzen; Minimum über 20 s = am wenigsten verspätet
            est = arrival - LATENCY - self.total / RATE
            win = self._t0_window
            win.append((arrival, est))
            while win and win[0][0] < arrival - 20:
                win.popleft()
            self.t0 = min(e for _a, e in win)
            self.last_chunk = arrival
        # Pegel (grob, nur für die Anzeige)
        step = max(1, n // 400)
        acc = 0.0
        cnt = 0
        for i in range(0, n, step):
            v = samples[i]
            acc += v * v
            cnt += 1
        rms = math.sqrt(acc / cnt) if cnt else 0.0
        level = 20 * math.log10(rms / 32768) if rms > 0 else -120.0
        self.level_dbfs = level if self.level_dbfs is None else 0.8 * self.level_dbfs + 0.2 * level
        self.error = None

    def extract(self, t_start: float, seconds: float) -> tuple[array.array, float]:
        """Samples ab Systemzeit t_start. Fehlende Teile = Stille.
        Gibt (samples, Anteil vorhandener Daten 0..1) zurück."""
        n = int(round(seconds * RATE))
        out = array.array("h", bytes(n * 2))
        with self.lock:
            if self.t0 is None or self.total == 0:
                return out, 0.0
            start = int(round((t_start - self.t0) * RATE))
            oldest = max(0, self.total - self.cap)
            lo = max(start, oldest)
            hi = min(start + n, self.total)
            have = max(0, hi - lo)
            idx = lo
            while idx < hi:
                pos = idx % self.cap
                run = min(hi - idx, self.cap - pos)
                out[idx - start:idx - start + run] = self.buf[pos:pos + run]
                idx += run
        return out, have / n

    def status(self) -> dict:
        age = time.time() - self.last_chunk if self.last_chunk else None
        return {
            "ok": age is not None and age < 2.0,
            "age_s": None if age is None else round(age, 1),
            "level_dbfs": None if self.level_dbfs is None else round(self.level_dbfs, 1),
            "error": self.error,
            "source": SOURCE,
        }


# ----------------------------------------------------------------- Rig ----

class RigWatch:
    """Fragt rigctld alle 5 s nach Frequenz und Modus (nur lesend)."""

    def __init__(self) -> None:
        self.freq_hz: int | None = None
        self.mode: str | None = None
        self.reachable = False
        self.checked = 0.0
        threading.Thread(target=self._run, name="rig", daemon=True).start()

    @staticmethod
    def _cmd(cmd: str) -> str:
        with socket.create_connection(RIGCTLD, timeout=2) as sock:
            sock.settimeout(2)
            sock.sendall((cmd + "\n").encode())
            data = sock.recv(256)
        return data.decode(errors="replace")

    def poll(self) -> None:
        try:
            f = self._cmd("f").strip()
            m = self._cmd("m").split("\n")[0].strip()
            self.freq_hz = int(f) if f.isdigit() and int(f) > 0 else None
            self.mode = m if m and not m.startswith("RPRT") else None
            self.reachable = self.freq_hz is not None
        except (OSError, ValueError):
            self.reachable = False
            self.freq_hz = None
            self.mode = None
        self.checked = time.time()

    def _run(self) -> None:
        while True:
            self.poll()
            time.sleep(5)

    def on_frequency(self, dial_hz: int) -> bool:
        return (
            self.reachable
            and self.freq_hz is not None
            and abs(self.freq_hz - dial_hz) <= 50
            and (self.mode or "") in ("USB", "PKTUSB")
        )


# ------------------------------------------------------------ Decoding ---

FT_LINE = re.compile(r"^(\d{6})\s+(-?\d+)\s+(-?\d+\.\d)\s+(\d+)\s+([~+])\s+(.*?)\s*$")
WSPR_LINE = re.compile(r"^(\d{4})\s+(-?\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(-?\d+)\s+(.+?)\s*$")
GRID4 = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$", re.I)
CALL = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{1,4}(/[A-Z0-9]{1,4})?[A-Z0-9]*(/[A-Z0-9]{1,4})?$")
CQ_MODIFIERS = re.compile(r"^([A-Z]{1,4}|\d{3})$")


def _is_call(token: str) -> bool:
    return bool(CALL.match(token)) and 3 <= len(token) <= 13 and not GRID4.match(token)


def parse_ft_message(msg: str) -> dict:
    """Sender-Rufzeichen und Locator aus einer FT8/FT4-Nachricht."""
    words = msg.replace("<", "").replace(">", "").split()
    info: dict = {"call": None, "grid": None, "cq": False, "to": None}
    if not words:
        return info
    if words[0] == "CQ":
        info["cq"] = True
        rest = words[1:]
        if len(rest) >= 2 and CQ_MODIFIERS.match(rest[0]) and _is_call(rest[1]):
            rest = rest[1:]
        if rest and _is_call(rest[0]):
            info["call"] = rest[0]
            if len(rest) >= 2 and GRID4.match(rest[1]) and rest[1] != "RR73":
                info["grid"] = rest[1].upper()
        return info
    if len(words) >= 2 and _is_call(words[1]):
        info["to"] = words[0] if _is_call(words[0]) else None
        info["call"] = words[1]
        if len(words) >= 3 and GRID4.match(words[2]) and words[2] != "RR73":
            info["grid"] = words[2].upper()
    if "<" in msg:  # gehashte Rufzeichen nicht als sicher betrachten
        info["hashed"] = True
    return info


def write_wav(path: Path, samples: array.array) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


def _env() -> dict:
    env = dict(os.environ)
    if WSJTX_LIB:
        env["LD_LIBRARY_PATH"] = WSJTX_LIB + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def run_decoder(mode: str, wav: Path, dial_hz: int, call: str, grid: str) -> list[str]:
    data_dir = WORK_DIR / mode.lower()
    data_dir.mkdir(parents=True, exist_ok=True)
    if mode == "WSPR":
        cmd = [str(WSJTX_BIN / "wsprd"), "-a", str(data_dir), "-f", f"{dial_hz / 1e6:.6f}", str(wav)]
    else:
        flag = "-8" if mode == "FT8" else "-5"
        cmd = [str(WSJTX_BIN / "jt9"), flag, "-d", "3", "-a", str(data_dir), "-t", str(data_dir),
               "-L", "200", "-H", "3000"]
        if call:
            cmd += ["-c", call]
        if grid:
            cmd += ["-G", grid[:4]]
        cmd.append(str(wav))
    if shutil.which("nice"):
        cmd = ["nice", "-n", "10"] + cmd
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=110, env=_env(), cwd=str(data_dir))
    if res.returncode != 0 and not res.stdout:
        raise RuntimeError((res.stderr or f"Decoder-Fehler {res.returncode}").strip()[:300])
    return res.stdout.splitlines()


# ------------------------------------------------------------- Uploads ---

def _varlen(text: str) -> bytes:
    raw = text.encode("utf-8")[:254]
    return bytes([len(raw)]) + raw


def _padded(data: bytes) -> bytes:
    return data + b"\0" * ((-len(data)) % 4)


ENTERPRISE = 30351


def _ent_field(field_id: int, length: int) -> bytes:
    return struct.pack(">HHI", field_id, length, ENTERPRISE)


class PskReporter:
    """Meldet FT8/FT4-Spots per IPFIX/UDP an report.pskreporter.info (wie WSJT-X)."""

    RX_TEMPLATE_ID = 0x50E2
    TX_TEMPLATE_ID = 0x50E3

    def __init__(self) -> None:
        self.queue: list[dict] = []
        self.recent: dict[tuple, float] = {}
        self.sent = 0
        self.packets = 0
        self.last_flush: float | None = None
        self.last_error: str | None = None
        self.lock = threading.Lock()
        self.domain = random.getrandbits(32)
        self.sequence = 0
        self.templates_sent = 0
        self.templates_at = 0.0
        threading.Thread(target=self._run, name="pskreporter", daemon=True).start()

    def add(self, spot: dict) -> bool:
        key = (spot["call"], spot["mode"], int(spot["freq_hz"]) // 1_000_000)
        now = time.time()
        with self.lock:
            if now - self.recent.get(key, 0) < PSK_DEDUP_SECONDS:
                return False
            self.recent[key] = now
            for k in [k for k, t in self.recent.items() if now - t > PSK_DEDUP_SECONDS]:
                del self.recent[k]
            self.queue.append(spot)
        return True

    def pending(self) -> int:
        with self.lock:
            return len(self.queue)

    def _templates(self) -> bytes:
        rx_fields = (_ent_field(0x8002, 0xFFFF) + _ent_field(0x8004, 0xFFFF)
                     + _ent_field(0x8008, 0xFFFF) + _ent_field(0x8009, 0xFFFF))
        rx_body = struct.pack(">HHH", self.RX_TEMPLATE_ID, 4, 0) + rx_fields
        rx_set = _padded(struct.pack(">HH", 3, 0) + rx_body)
        rx_set = struct.pack(">HH", 3, len(rx_set)) + rx_set[4:]
        tx_fields = (_ent_field(0x8001, 0xFFFF) + _ent_field(0x8005, 5) + _ent_field(0x8006, 1)
                     + _ent_field(0x800A, 0xFFFF) + _ent_field(0x8003, 0xFFFF) + _ent_field(0x800B, 1)
                     + struct.pack(">HH", 0x0096, 4))
        tx_body = struct.pack(">HH", self.TX_TEMPLATE_ID, 7) + tx_fields
        tx_set = _padded(struct.pack(">HH", 2, 0) + tx_body)
        tx_set = struct.pack(">HH", 2, len(tx_set)) + tx_set[4:]
        return rx_set + tx_set

    def _packet(self, rx_call: str, rx_grid: str, spots: list[dict], with_templates: bool) -> bytes:
        body = self._templates() if with_templates else b""
        rx_rec = (_varlen(rx_call) + _varlen(rx_grid) + _varlen(f"OrbitHub Digimode {VERSION} (WSJT-X jt9)")
                  + _varlen(os.environ.get("DIGIMODE_ANTENNA", "")))
        rx_set = _padded(struct.pack(">HH", self.RX_TEMPLATE_ID, 0) + rx_rec)
        body += struct.pack(">HH", self.RX_TEMPLATE_ID, len(rx_set)) + rx_set[4:]
        recs = b""
        for s in spots:
            f = int(s["freq_hz"])
            recs += (_varlen(s["call"]) + bytes([(f >> 32) & 0xFF]) + struct.pack(">I", f & 0xFFFFFFFF)
                     + struct.pack(">b", max(-128, min(127, int(s["snr"])))) + _varlen(s["mode"])
                     + _varlen(s.get("grid") or "") + bytes([1]) + struct.pack(">I", int(s["time"])))
        tx_set = _padded(struct.pack(">HH", self.TX_TEMPLATE_ID, 0) + recs)
        body += struct.pack(">HH", self.TX_TEMPLATE_ID, len(tx_set)) + tx_set[4:]
        header = struct.pack(">HHIII", 10, 16 + len(body), int(time.time()), self.sequence, self.domain)
        self.sequence += len(spots)
        return header + body

    def flush(self, rx_call: str, rx_grid: str) -> None:
        with self.lock:
            spots, self.queue = self.queue, []
        if not spots:
            self.last_flush = time.time()
            return
        try:
            addr = socket.getaddrinfo(PSK_HOST[0], PSK_HOST[1], socket.AF_INET, socket.SOCK_DGRAM)[0][4]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for i in range(0, len(spots), 25):
                    batch = spots[i:i + 25]
                    with_t = self.templates_sent < 3 or time.time() - self.templates_at > 3600
                    sock.sendto(self._packet(rx_call, rx_grid, batch, with_t), addr)
                    if with_t:
                        self.templates_sent += 1
                        self.templates_at = time.time()
                    self.packets += 1
                    self.sent += len(batch)
            self.last_error = None
        except OSError as exc:
            self.last_error = f"PSK Reporter nicht erreichbar: {exc}"
            log.warning(self.last_error)
            with self.lock:
                self.queue = spots + self.queue
        self.last_flush = time.time()

    def _run(self) -> None:
        while True:
            time.sleep(PSK_FLUSH_SECONDS)
            cfg = engine.cfg
            if cfg.get("call") and cfg.get("grid"):
                self.flush(cfg["call"], cfg["grid"])

    def status(self) -> dict:
        return {"sent": self.sent, "pending": self.pending(), "packets": self.packets,
                "last_flush": self.last_flush, "error": self.last_error}


class WsprNet:
    """Meldet WSPR-Spots per HTTP an wsprnet.org (Schnittstelle wie WSJT-X)."""

    def __init__(self) -> None:
        self.queue: collections.deque = collections.deque(maxlen=2000)
        self.sent = 0
        self.last_error: str | None = None
        self.event = threading.Event()
        threading.Thread(target=self._run, name="wsprnet", daemon=True).start()

    def add(self, spot: dict) -> None:
        self.queue.append(spot)
        self.event.set()

    def _run(self) -> None:
        while True:
            self.event.wait(60)
            self.event.clear()
            while self.queue:
                spot = self.queue[0]
                try:
                    query = urllib.parse.urlencode({
                        "function": "wspr", "rcall": spot["rcall"], "rgrid": spot["rgrid"],
                        "rqrg": f"{spot['dial_hz'] / 1e6:.6f}", "date": spot["date"], "time": spot["hhmm"],
                        "sig": spot["snr"], "dt": f"{spot['dt']:.1f}", "drift": spot["drift"],
                        "tqrg": f"{spot['freq_hz'] / 1e6:.6f}", "tcall": spot["call"],
                        "tgrid": spot.get("grid") or "", "dbm": spot["dbm"],
                        "version": f"OrbitHub-{VERSION}", "mode": "2",
                    })
                    with urllib.request.urlopen(f"{WSPRNET_URL}?{query}", timeout=20) as resp:
                        resp.read(2000)
                    self.queue.popleft()
                    self.sent += 1
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"WSPRnet nicht erreichbar: {exc}"
                    log.warning(self.last_error)
                    time.sleep(30)
                    break

    def status(self) -> dict:
        return {"sent": self.sent, "pending": len(self.queue), "error": self.last_error}


# --------------------------------------------------------------- Engine ---

class Engine:
    def __init__(self) -> None:
        self.cfg: dict = {
            "running": False, "mode": "FT8", "band": "", "dial_hz": 0,
            "call": "", "grid": "", "upload_psk": True, "upload_wsprnet": True,
            # Senden (Voreinstellung: Probelauf, nur 2 m / 70 cm freigegeben)
            "tx_bands": ["2m", "70cm"], "dry_run": True, "tx_df": 1500, "tx_level": 0.3,
            "wspr_beacon": False, "wspr_pct": 20, "wspr_dbm": 37, "tx_enabled": False,
            "auto_level": True, "tx_levels": {},
        }
        self.audio = AudioRing()
        self.rig = RigWatch()
        self.decodes: collections.deque = collections.deque(maxlen=3000)
        self.seq = 0
        self.lock = threading.Lock()
        self.last_cycle: dict = {}
        self.busy = False
        self.started_at: float | None = None
        self._gen = 0
        self.psk: PskReporter | None = None
        self.wsprnet: WsprNet | None = None
        self.log_dir = LOG_DIR
        self.work_dir = WORK_DIR
        self.wsjtx_bin = WSJTX_BIN
        self.rigctld = RIGCTLD
        self._load()
        # nach einem Neustart nie von selbst senden
        self.cfg["tx_enabled"] = False
        self.cfg["wspr_beacon"] = False
        self.tx = digimode_tx.Transmitter(self)
        self.cty = digimode_cty.Cty(BASE_DIR / "cty.dat")

    # -- Hilfen für den Sender
    env = staticmethod(lambda: _env())
    write_wav = staticmethod(lambda path, samples: write_wav(path, samples))
    run_decoder = staticmethod(lambda *a: run_decoder(*a))

    def save(self) -> None:
        self._save()

    def iso(self, ts: float) -> str:
        return self._iso(ts)

    def add_entries(self, entries: list[dict]) -> None:
        with self.lock:
            for d in entries:
                self.seq += 1
                d["seq"] = self.seq
                d.setdefault("dial_hz", int(self.cfg.get("dial_hz") or 0))
                self.decodes.append(d)
        self._log(entries)

    # -- Zustand
    def _load(self) -> None:
        try:
            self.cfg.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cfg, indent=1), encoding="utf-8")
        tmp.replace(STATE_FILE)

    def configure(self, data: dict) -> None:
        for key in ("upload_psk", "upload_wsprnet"):
            if key in data:
                self.cfg[key] = bool(data[key])
        for key in ("call", "grid"):
            if data.get(key):
                self.cfg[key] = str(data[key]).strip().upper()[:12]
        self._save()

    def start(self, data: dict) -> None:
        mode = str(data.get("mode", "")).upper()
        if mode not in MODES:
            raise ValueError("Betriebsart muss FT8, FT4 oder WSPR sein.")
        dial = int(data.get("dial_hz") or 0)
        if not 100_000 <= dial <= 500_000_000:
            raise ValueError("Ungültige Frequenz.")
        self.configure(data)
        if mode != self.cfg.get("mode") or dial != self.cfg.get("dial_hz"):
            self.tx.halt("Band/Betriebsart gewechselt")
            self.tx.clear_qso()
        self.cfg.update({"running": True, "mode": mode, "dial_hz": dial, "band": str(data.get("band", ""))})
        self._save()
        self.rig.poll()  # gleich frisch, damit die Anzeige nicht kurz „falsche QRG“ meldet
        self._begin()

    def stop(self) -> None:
        self.tx.halt("Empfang gestoppt")
        self.tx.clear_qso()
        self.cfg["running"] = False
        self._save()
        self._gen += 1
        self.audio.stop()
        self.started_at = None

    def _begin(self) -> None:
        self._gen += 1
        gen = self._gen
        self.audio.start()
        self.started_at = time.time()
        self.last_cycle = {}
        threading.Thread(target=self._loop, args=(gen,), name="slots", daemon=True).start()

    def resume(self) -> None:
        if self.cfg.get("running"):
            log.info("setze %s auf %d Hz fort", self.cfg["mode"], self.cfg["dial_hz"])
            self._begin()

    # -- Periodenschleife
    def _loop(self, gen: int) -> None:
        mode = self.cfg["mode"]
        spec = MODES[mode]
        period = spec["period"]
        last_slot = 0.0
        while gen == self._gen:
            now = time.time()
            slot_start = math.floor(now / period) * period
            if slot_start <= last_slot:  # diese Periode ist schon ausgewertet
                time.sleep(0.1)
                continue
            last_slot = slot_start
            wake = slot_start + spec["decode_at"] + LATENCY + 0.15
            while gen == self._gen and time.time() < wake:
                time.sleep(min(0.25, max(0.0, wake - time.time())))
            if gen != self._gen:
                return
            # nur vollständig mitgeschnittene Perioden dekodieren
            if self.started_at and slot_start < self.started_at - 0.5:
                continue
            if slot_start in self.tx.tx_slots:
                self.tx.tx_slots.discard(slot_start)
                self.last_cycle = {"utc": self._iso(slot_start), "mode": mode, "skipped": True,
                                   "reason": "eigene Aussendung"}
                self.tx.after_cycle(slot_start, [])
                continue
            part, have = self.audio.extract(slot_start, spec["decode_at"])
            samples = array.array("h", bytes(int(spec["length"] * RATE) * 2))
            samples[:len(part)] = part
            if have < 0.8:
                self.last_cycle = {"utc": self._iso(slot_start), "mode": mode, "skipped": True,
                                   "reason": "zu wenig Audio" if have else "kein Audio", "have": round(have, 2)}
                self.tx.after_cycle(slot_start, [])
                continue
            if self.busy:
                self.last_cycle = {"utc": self._iso(slot_start), "mode": mode, "skipped": True,
                                   "reason": "Decoder noch beschäftigt"}
                self.tx.after_cycle(slot_start, [])
                continue
            threading.Thread(target=self._decode, args=(gen, mode, slot_start, samples), daemon=True).start()

    @staticmethod
    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def _decode(self, gen: int, mode: str, slot_start: float, samples: array.array) -> None:
        self.busy = True
        t0 = time.time()
        dial = int(self.cfg["dial_hz"])
        call, grid = self.cfg.get("call", ""), self.cfg.get("grid", "")
        on_freq = self.rig.on_frequency(dial)
        st = datetime.fromtimestamp(slot_start, timezone.utc)
        name = st.strftime("%y%m%d_%H%M") if mode == "WSPR" else st.strftime("%y%m%d_%H%M%S")
        found: list[dict] = []
        error = None
        try:
            with tempfile.TemporaryDirectory(dir=str(WORK_DIR)) as tmp:
                wav = Path(tmp) / f"{name}.wav"
                write_wav(wav, samples)
                lines = run_decoder(mode, wav, dial, call, grid)
            for line in lines:
                d = self._parse(mode, line, dial, slot_start)
                if d:
                    found.append(d)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]
            log.warning("Dekodierung %s fehlgeschlagen: %s", mode, error)
        finally:
            self.busy = False
        if gen != self._gen:
            return
        # Duplikate (gleiche Nachricht in derselben Periode) entfernen
        seen = set()
        unique = []
        for d in found:
            key = (d["message"], d.get("df"))
            if key not in seen:
                seen.add(key)
                unique.append(d)
        for d in unique:
            hit = self.cty.lookup(d.get("call"))
            if hit:
                d["country"] = hit["country"]
                d["cont"] = hit["cont"]
        with self.lock:
            for d in unique:
                self.seq += 1
                d["seq"] = self.seq
                d["on_freq"] = on_freq
                d["dial_hz"] = dial
                self.decodes.append(d)
        self.last_cycle = {"utc": self._iso(slot_start), "mode": mode, "count": len(unique),
                           "seconds": round(time.time() - t0, 1), "error": error, "on_freq": on_freq}
        self._log(unique)
        try:
            self.tx.after_cycle(slot_start, unique)
        except Exception as exc:  # noqa: BLE001
            log.warning("QSO-Ablauf: %s", exc)
        if on_freq and call and grid:
            self._upload(mode, unique, dial, call, grid, st)

    def _parse(self, mode: str, line: str, dial: int, slot_start: float) -> dict | None:
        utc = self._iso(slot_start)
        if mode == "WSPR":
            m = WSPR_LINE.match(line.strip())
            if not m:
                return None
            words = m.group(6).split()
            call = words[0] if words else ""
            grid = words[1] if len(words) >= 3 and GRID4.match(words[1]) else None
            dbm = words[-1] if words and words[-1].lstrip("-").isdigit() else None
            freq_hz = round(float(m.group(4)) * 1e6)
            return {
                "mode": mode, "utc": utc, "snr": int(m.group(2)), "dt": float(m.group(3)),
                "freq_hz": freq_hz, "df": freq_hz - dial, "drift": int(m.group(5)),
                "message": m.group(6).strip(), "call": call.strip("<>") if not call.startswith("<.") else None,
                "grid": grid.upper() if grid else None, "dbm": int(dbm) if dbm else None,
                "hashed": call.startswith("<"),
            }
        m = FT_LINE.match(line.rstrip())
        if not m:
            return None
        msg = re.sub(r"(\s+(a\d+|\?))+\s*$", "", m.group(6)).strip()  # AP-/Unsicher-Markierungen
        info = parse_ft_message(msg)
        df = int(m.group(4))
        return {
            "mode": mode, "utc": utc, "snr": int(m.group(2)), "dt": float(m.group(3)),
            "df": df, "freq_hz": dial + df, "message": msg, "call": info["call"], "grid": info["grid"],
            "cq": info["cq"], "to": info["to"], "hashed": bool(info.get("hashed")),
        }

    def _log(self, decodes: list[dict]) -> None:
        if not decodes:
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"decodes-{utcnow():%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for d in decodes:
                fh.write(json.dumps({**d, "dial_hz": self.cfg["dial_hz"]}, ensure_ascii=False) + "\n")

    def _upload(self, mode: str, decodes: list[dict], dial: int, call: str, grid: str, st: datetime) -> None:
        for d in decodes:
            if d.get("tx") or not d.get("call") or d.get("hashed") or d["call"] == call:
                continue
            if mode == "WSPR":
                if self.cfg.get("upload_wsprnet") and self.wsprnet and d.get("dbm") is not None:
                    self.wsprnet.add({**d, "rcall": call, "rgrid": grid, "dial_hz": dial,
                                      "date": st.strftime("%y%m%d"), "hhmm": st.strftime("%H%M")})
                    d["uploaded"] = True
            elif self.cfg.get("upload_psk") and self.psk:
                if self.psk.add({"call": d["call"], "freq_hz": d["freq_hz"], "snr": d["snr"], "mode": mode,
                                 "grid": d.get("grid"), "time": int(st.timestamp())}):
                    d["uploaded"] = True

    # -- Ausgabe
    def status(self) -> dict:
        with self.lock:
            count = len(self.decodes)
        cfg = dict(self.cfg)
        return {
            "ok": True, "version": VERSION, **cfg,
            "server_time": time.time(),
            "period": MODES[cfg["mode"]]["period"] if cfg["mode"] in MODES else None,
            "busy": self.busy, "last_cycle": self.last_cycle, "decode_count": count, "seq": self.seq,
            "audio": self.audio.status() if cfg["running"] else {"ok": False, "idle": True, "source": SOURCE},
            "rig": {"reachable": self.rig.reachable, "freq_hz": self.rig.freq_hz, "mode": self.rig.mode,
                    "on_freq": self.rig.on_frequency(int(cfg["dial_hz"] or 0)) if cfg["dial_hz"] else False},
            "upload": {
                "psk": self.psk.status() if self.psk else None,
                "wsprnet": self.wsprnet.status() if self.wsprnet else None,
            },
            "tx": self.tx.status(),
            "decoders": {
                "jt9": (WSJTX_BIN / "jt9").exists(), "wsprd": (WSJTX_BIN / "wsprd").exists(),
            },
        }

    def decodes_since(self, since: int, limit: int = 500) -> list[dict]:
        with self.lock:
            items = [d for d in self.decodes if d["seq"] > since]
        return items[-limit:]


engine = Engine()


# ----------------------------------------------------------------- HTTP ---

class Handler(BaseHTTPRequestHandler):
    server_version = f"OrbitHubDigimode/{VERSION}"

    def log_message(self, fmt: str, *args) -> None:  # leise
        pass

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/status", "/health"):
            self._json(200, engine.status())
        elif url.path == "/decodes":
            q = urllib.parse.parse_qs(url.query)
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            self._json(200, {"seq": engine.seq, "decodes": engine.decodes_since(since)})
        elif url.path == "/log":
            self._json(200, {"qsos": engine.tx.log_entries()})
        elif url.path == "/log.adi":
            try:
                body = engine.tx.log_path.read_bytes()
            except OSError:
                body = b""
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(404, {"error": "unbekannt"})

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        data = self._body()
        try:
            if path == "/start":
                engine.start(data)
            elif path == "/stop":
                engine.stop()
            elif path == "/config":
                engine.configure(data)
            elif path == "/tx/config":
                engine.tx.configure(data)
            elif path == "/tx/cq":
                engine.tx.start_cq()
            elif path == "/tx/call":
                seq = int(data.get("seq") or 0)
                with engine.lock:
                    d = next((x for x in engine.decodes if x["seq"] == seq), None)
                if not d:
                    raise ValueError("Dekodierung nicht mehr vorhanden.")
                engine.tx.call_station(d)
            elif path == "/tx/next":
                engine.tx.choose(str(data.get("key", "")))
            elif path == "/tx/halt":
                engine.tx.halt("STOP")
            elif path == "/tx/clear":
                engine.tx.clear_qso()
            elif path == "/flush":
                if engine.psk and engine.cfg.get("call") and engine.cfg.get("grid"):
                    engine.psk.flush(engine.cfg["call"], engine.cfg["grid"])
            else:
                self._json(404, {"error": "unbekannt"})
                return
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(200, engine.status())


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    for old in WORK_DIR.glob("tmp*"):
        shutil.rmtree(old, ignore_errors=True)
    engine.psk = PskReporter()
    engine.wsprnet = WsprNet()
    if not (WSJTX_BIN / "jt9").exists():
        log.error("jt9 nicht gefunden unter %s – bitte tools/digimode/install.sh ausführen", WSJTX_BIN)
    engine.resume()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Digimode-Dienst auf Port %d (Quelle %s, Decoder %s)", PORT, SOURCE, WSJTX_BIN)
    try:
        server.serve_forever()
    finally:
        engine.audio.stop()  # Zustand bleibt gespeichert -> Fortsetzung nach Neustart


if __name__ == "__main__":
    main()
