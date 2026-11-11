#!/usr/bin/env python3
"""OrbitHub – IC-705-Empfangston als MP3-Livestream über HTTP.

Läuft auf dem HOST (nicht im Docker-Container), weil nur dort die
PipeWire/PulseAudio-Quelle von kappanhang („kappanhang-IC-705“) erreichbar
ist. Jeder Client bekommt eine eigene ffmpeg-Instanz, die beim Trennen der
Verbindung beendet wird.

Endpunkte:
  GET/HEAD /stream.mp3  – Livestream (audio/mpeg, chunked)
  GET      /health      – {"ok": true, "source": ...}

Konfiguration über Umgebungsvariablen:
  AUDIO_SOURCE  (Standard: kappanhang-IC-705)
  AUDIO_PORT    (Standard: 8766)
  AUDIO_BITRATE (Standard: 64k)

Nur Python-Standardbibliothek + ffmpeg (mit PulseAudio-Eingang) nötig.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE = os.environ.get("AUDIO_SOURCE", "kappanhang-IC-705")
PORT = int(os.environ.get("AUDIO_PORT", "8766"))
BITRATE = os.environ.get("AUDIO_BITRATE", "64k")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("audio-stream")


def ffmpeg_command() -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-fflags", "nobuffer",
        "-f", "pulse", "-i", SOURCE,
        "-ac", "1", "-ar", "24000",
        "-c:a", "libmp3lame", "-b:a", BITRATE,
        "-f", "mp3", "-flush_packets", "1",
        "pipe:1",
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OrbitHubAudio/1.0"

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _stream_headers(self, chunked: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._path() != "/stream.mp3":
            self.send_error(404)
            return
        self._stream_headers(chunked=False)

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        if path == "/health":
            body = json.dumps({"ok": True, "source": SOURCE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path != "/stream.mp3":
            self.send_error(404)
            return

        client = f"{self.client_address[0]}:{self.client_address[1]}"
        try:
            proc = subprocess.Popen(ffmpeg_command(), stdout=subprocess.PIPE)
        except OSError as exc:
            log.error("ffmpeg konnte nicht gestartet werden: %s", exc)
            self.send_error(503, "ffmpeg nicht verfügbar")
            return

        log.info("Stream gestartet für %s (Quelle %s)", client, SOURCE)
        self._stream_headers(chunked=True)
        try:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read1(4096)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info("Stream beendet für %s (ffmpeg rc=%s)", client, proc.returncode)
        self.close_connection = True

    def log_message(self, fmt: str, *args) -> None:  # leiser als Standard
        log.debug("%s - " + fmt, self.address_string(), *args)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    log.info("Audio-Stream lauscht auf :%d (Quelle %s, %s)", PORT, SOURCE, BITRATE)
    server.serve_forever()


if __name__ == "__main__":
    main()
