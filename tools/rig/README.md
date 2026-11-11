# IC-705 Rig-Control – Host-Dienste

OrbitHub steuert den ICOM IC-705 per WLAN über [kappanhang](https://github.com/nonoo/kappanhang).
kappanhang und der Audio-Stream laufen auf dem **Host** (nicht im Docker-Container),
weil sie PipeWire/PulseAudio brauchen. Der Container erreicht rigctld über
`host.docker.internal:4532` (siehe `extra_hosts` in `docker-compose.yml`).

| Dienst | Port | Zweck |
|---|---|---|
| kappanhang (rigctld) | 4532 | Frequenz/Modus setzen (Doppler-Tracking) |
| audio-stream | 8766 | Empfangston als MP3 für den Umschalter „Hören: Mac“ |

## Einrichtung (Linux, z. B. Ubuntu auf dem Radxa Q8B)

```bash
sudo apt install -y golang-go pulseaudio-utils libpulse-dev ffmpeg netcat-openbsd
sudo loginctl enable-linger "$USER"

git clone https://github.com/nonoo/kappanhang.git ~/kappanhang
(cd ~/kappanhang && go build .)

cp ~/orbithub/tools/rig/kappanhang.env.example ~/kappanhang/kappanhang.env
chmod 600 ~/kappanhang/kappanhang.env   # Passwort eintragen

mkdir -p ~/.config/systemd/user
cp ~/orbithub/tools/rig/kappanhang.service ~/orbithub/tools/rig/audio-stream.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kappanhang.service audio-stream.service
```

## Test

```bash
echo f | nc -w2 localhost 4532                 # aktuelle Frequenz in Hz
curl -s localhost:8766/health                  # {"ok": true, ...}
curl -s localhost:8765/api/rig/status          # {"reachable": true}
```

## Wichtig: kappanhang-Korrekturen einspielen

Der Original-kappanhang (Stand 2021) hat zwei Fehler in `rigctld.go`, die OrbitHub trifft:

1. **Absturz bei `M FM …`** – `mode[:3] == "PKT"` läuft bei zweibuchstabigen Modi (FM, AM, CW, DV)
   über das String-Ende hinaus → Go-Panic, kappanhang beendet sich, der IC-705 ist kurz weg.
2. **Modus wird ignoriert** – an den IC-705 geht der Filter-*Index* (0/1/2) statt des CI-V-Filtercodes
   (01/02/03). Filter 0 gibt es nicht, das Funkgerät verwirft den Befehl kommentarlos.

Vor dem `go build .` deshalb einspielen:

```bash
cd ~/kappanhang && git apply ~/orbithub/tools/rig/kappanhang-fixes.patch && go build .
```
