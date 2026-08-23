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

    def set_mode(self, mode: str, passband: int = 0) -> None:
        """Setzt Modus (z. B. 'FM', 'USB', 'LSB') und optional Passband-Breite."""
        self._command(f"M {mode} {passband}")

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


# Modulweite Standardinstanz fuer einfache Verwendung in main.py & Co.
rig_control = RigControl()
