"""app/services/rig_control.py

Client fuer kappanhangs eingebauten rigctld-kompatiblen TCP-Server, der den
ICOM IC-705 per WLAN fernsteuert. Wird fuer die Doppler-Korrektur waehrend
Satelliten-Ueberfluegen verwendet.

Protokoll: einfaches Hamlib-rigctld-Zeilenprotokoll (siehe `rigctld(8)`).
Verbindung: TCP zu kappanhang, das auf dem Host laeuft (nicht im
Docker-Container) auf Port 4532. Von innerhalb des orbithub-Containers ueber
`host.docker.internal` erreichbar (siehe docker-compose.yml `extra_hosts`).
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Tuple

logger = logging.getLogger(__name__)

RIGCTLD_HOST = os.environ.get("RIGCTLD_HOST", "host.docker.internal")
RIGCTLD_PORT = int(os.environ.get("RIGCTLD_PORT", "4532"))
RIGCTLD_TIMEOUT = float(os.environ.get("RIGCTLD_TIMEOUT", "3"))


class RigControlError(RuntimeError):
    """Fehler bei der Kommunikation mit rigctld / dem Funkgeraet."""


class RigControl:
    """Duenner Client fuer rigctld (kappanhang), Thread-sicher durch einen Lock.

    Oeffnet fuer jeden Befehl eine kurze TCP-Verbindung. Das ist bei rigctld
    ausdruecklich erlaubt und robuster als eine langlebige Verbindung ueber
    den Docker-Netzwerk-Hop hinweg.
    """

    def __init__(
        self,
        host: str = RIGCTLD_HOST,
        port: int = RIGCTLD_PORT,
        timeout: float = RIGCTLD_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._lock = threading.Lock()

    def _command(self, cmd: str) -> str:
        with self._lock:
            try:
                with socket.create_connection(
                    (self._host, self._port), timeout=self._timeout
                ) as sock:
                    sock.sendall((cmd + "\n").encode("ascii"))
                    data = sock.recv(256)
            except OSError as exc:
                raise RigControlError(
                    f"Verbindung zu rigctld ({self._host}:{self._port}) "
                    f"fehlgeschlagen: {exc}"
        ) from exc

        reply = data.decode("ascii", errors="replace").strip()
        if reply.startswith("RPRT") and reply != "RPRT 0":
            raise RigControlError(f"rigctld meldet Fehler fuer '{cmd}': {reply}")
        return reply

    def get_frequency(self) -> int:
        """Aktuelle VFO-Frequenz in Hz."""
        reply = self._command("f")
        try:
            return int(reply)
        except ValueError as exc:
            raise RigControlError(f"Unerwartete Antwort auf 'f': {reply!r}") from exc

    def set_frequency(self, hz: int) -> None:
        """Setzt die VFO-Frequenz in Hz."""
        self._command(f"F {int(hz)}")

    def get_mode(self) -> Tuple[str, int]:
        """Aktueller Modus und Passband-Breite in Hz, z. B. ('FM', 15000)."""
        reply = self._command("m")
        parts = reply.splitlines()
        if len(parts) < 2:
            raise RigControlError(f"Unerwartete Antwort auf 'm': {reply!r}")
        mode = parts[0].strip()
        try:
            passband = int(parts[1].strip())
        except ValueError:
            passband = 0
        return mode, passband

    def set_mode(self, mode: str, passband: int = 3000) -> None:
        """Setzt Modus (z. B. 'FM', 'USB', 'LSB') und Passband-Breite.

        kappanhang waehlt das IC-705-Filter anhand der Breite: <=1800 Hz ->
        FIL3 (schmal), <=2400 Hz -> FIL2, sonst FIL1 (breit). Ein Passband
        von 0 (Hamlib-"Standard") landet bei kappanhang daher auf FIL3 -
        deshalb ist der Default hier 3000 (= FIL1).
        """
        self._command(f"M {mode} {passband}")

    def get_meter(self) -> dict:
        """S-Meter und Rauschsperre (braucht die OrbitHub-Erweiterung von
        kappanhang: l SQL / l RAWSTR / l SQLSTAT)."""
        def level(name: str) -> str:
            return self._command(f"l {name}").splitlines()[0].strip()

        try:
            sql = float(level("SQL"))
            s_raw = int(float(level("RAWSTR")))
            sql_open = level("SQLSTAT") == "1"
        except ValueError as exc:
            raise RigControlError(f"Unerwartete Antwort beim Lesen der Pegel: {exc}") from exc
        return {"sql_raw": round(sql * 255), "s_raw": s_raw, "sql_open": sql_open}

    def set_squelch_raw(self, raw: int) -> None:
        """Rauschsperre in voller IC-705-Aufloesung setzen (0 = offen ... 255)."""
        raw = max(0, min(255, int(raw)))
        self._command(f"L SQL {raw / 255:.6f}")

    def is_reachable(self) -> bool:
        """Prueft ohne Exception, ob rigctld gerade erreichbar ist."""
        try:
            self.get_frequency()
            return True
        except RigControlError:
            return False

    def wait_until_reachable(self, attempts: int = 4, delay_seconds: float = 1.5) -> bool:
        """Versucht mehrfach, rigctld/den IC-705 zu erreichen.

        Gedacht, um dem Funkgeraet ein paar Sekunden Zeit zu geben, aus einem
        Display-Standby aufzuwachen bzw. kappanhang eine kurze Reconnect-Phase
        abzuschliessen, bevor der Aufrufer einen Fehler anzeigt. Kann den echten
        Funkgeraete-Netzwerk-Standby (Geraet komplett ausgeschaltet) nicht
        ueberwinden - dafuer gibt es weder in rigctld noch in kappanhang einen
        Fernstart-Befehl.
        """
        for attempt in range(attempts):
            if self.is_reachable():
                return True
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        return False


# Betriebsarten, die kappanhangs rigctld fuer den IC-705 kennt (civcontrol.go),
# jeweils auch mit "PKT"-Praefix (Datenmodus) zulaessig.
RIG_MODES = ("LSB", "USB", "AM", "CW", "RTTY", "FM", "WFM", "CW-R", "RTTY-R", "DV")

# Umsetzung von SatNOGS-/Benutzer-Modusbezeichnungen auf IC-705-Betriebsarten.
# Schluessel = erstes Wort der SatNOGS-Bezeichnung (z. B. "AFSK S-Net" -> "AFSK").
_MODE_ALIASES = {
    # FM-Demodulator: Sprache und alle FSK-artigen Datensignale
    "FMN": "FM", "NFM": "FM", "AFSK": "FM", "AFSK1K2": "FM", "FFSK": "FM",
    "FSK": "FM", "GFSK": "FM", "GMSK": "FM", "MSK": "FM", "MFSK": "FM",
    "DUV": "FM", "SSTV": "FM", "APT": "FM", "APRS": "FM", "PACKET": "FM",
    # SSB-Empfang fuer PSK-Varianten, Weak-Signal-Modi u. a.
    "BPSK": "USB", "PSK": "USB", "PSK31": "USB", "QPSK": "USB", "QPSK31": "USB",
    "DQPSK": "USB", "OQPSK": "USB", "WSJT": "USB", "FT8": "USB", "FT4": "USB",
    "OFDM": "USB", "SSB": "USB",
    # sonstige Schreibweisen
    "CWR": "CW-R", "RTTYR": "RTTY-R", "DSTAR": "DV", "D-STAR": "DV",
}


def rig_mode_for(requested: str) -> tuple[str, str | None]:
    """Setzt eine Modusbezeichnung auf eine IC-705-Betriebsart um.

    Gibt (rig_mode, hinweis) zurueck. `hinweis` ist None, wenn der Modus
    unveraendert uebernommen werden konnte, sonst ein kurzer deutscher Text
    fuer die Anzeige (z. B. "AFSK → FM").
    """
    raw = (requested or "").strip().upper()
    if not raw:
        return "FM", "Kein Modus angegeben → FM"

    prefix = ""
    base = raw
    if base.startswith("PKT") and base[3:] in RIG_MODES:
        prefix, base = "PKT", base[3:]
    if base in RIG_MODES:
        return prefix + base, None

    first_word = base.replace("_", " ").split()[0]
    mapped = _MODE_ALIASES.get(first_word) or (first_word if first_word in RIG_MODES else None)
    if mapped:
        return mapped, f"{requested.strip()} → {mapped}"
    return "FM", f"{requested.strip()} ist am IC-705 unbekannt → FM"


# Modulweite Standardinstanz fuer einfache Verwendung in main.py & Co.
rig_control = RigControl()
