# OrbitHub

<p align="center">
  <img src="app/static/img/orbithub-mission-logo.png" alt="OrbitHub Logo" width="220">
</p>

Selbst gehostete Webanwendung zur Vorhersage von Satellitenüberflügen für den Einsatz im Amateurfunk. OrbitHub berechnet alle Bahndaten lokal auf eigener Hardware (z. B. einem Raspberry Pi) – ohne dass Beobachtungsstandort oder Nutzungsdaten das eigene Netzwerk verlassen.

Im Zentrum steht die Frage, die sich jeder Satelliten-Beobachter stellt: Wann und wo am Himmel wird ein bestimmter Satellit als Nächstes sichtbar sein, und wie lange? OrbitHub beantwortet das mit präzisen, auf den eigenen Standort zugeschnittenen Vorhersagen.

## Funktionen

- **Übersicht** – Status der Anlage auf einen Blick: nächster Überflug mit Live-Countdown, Zustand der Bahndaten, Systemmetriken des Hosts.
- **Satellitenkatalog** – durchsuchbare Liste aller verfügbaren Satelliten mit NORAD-ID.
- **Überflüge** – Aufgangs-, Kulminations- und Untergangszeiten für einen gewählten Satelliten über einen einstellbaren Zeitraum, inklusive maximaler Elevation und Azimut.
- **Karte** – interaktive Weltkarte mit Live-Position und Bodenspur, eigenem Standort und Sichtbarkeitsradius.
- **Visuell** – Vorhersage sichtbarer Überflüge heller Objekte (z. B. ISS), inklusive Abgleich von Sonnen- und Beobachterstand.
- **Downloads** – Export der Bahndaten als TLE-Datei (2-Zeilen- oder 3-Zeilen-Format), auch als fester Link für den automatischen Import in externe Satellitenprogramme.
- **Statistik** – Verlauf von TLE-Updates und Systemauslastung.
- **Einstellungen** – eigener Standort, Rufzeichen, Maidenhead-Locator und eine benutzerdefinierte Horizontmaske (z. B. bei Abschattung durch Gebäude).
- **Historie** – Änderungsprotokoll der Anwendung selbst.

## Technik

- Backend: [FastAPI](https://fastapi.tiangolo.com/) mit Jinja2-Templates
- Bahnberechnung: [Skyfield](https://rhodesmill.org/skyfield/)
- Bahndaten-Quellen: [CelesTrak](https://celestrak.org/) und [SatNOGS](https://db.satnogs.org/) (automatischer Fallback)
- Bereitstellung: Docker / Docker Compose

## Voraussetzungen

- Docker und Docker Compose
- Getestet auf einem Raspberry Pi 3B, läuft aber auf jedem Docker-Host (auch x86)

## Installation

```bash
git clone <repo-url> orbithub
cd orbithub
cp data/observer-settings.example.json data/observer-settings.json
```

Trage in `data/observer-settings.json` deinen eigenen Standort ein (Rufzeichen, Maidenhead-Locator oder Breiten-/Längengrad). Alternativ lässt sich das nach dem Start bequem über die Seite **Einstellungen** in der Weboberfläche erledigen.

```bash
docker compose up -d --build
```

Anschließend ist OrbitHub unter `http://<host>:8765` erreichbar.

### Konfiguration

| Umgebungsvariable | Standard | Bedeutung |
| --- | --- | --- |
| `ORBITHUB_REFRESH_HOURS` | `6` | Intervall für den automatischen Abruf frischer Bahndaten |

Der Port lässt sich in `docker-compose.yml` über den `ports`-Eintrag anpassen. Alle Laufzeitdaten (Bahndaten, Einstellungen, Verlauf) liegen im Verzeichnis `data/`, das als Volume eingebunden ist und Neustarts sowie Updates übersteht.

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).

## Danksagung

Entwickelt von Christian Henkel (DL7AG) für den Einsatz im Amateurfunk. Beiträge und Pull Requests sind willkommen.




## Installation

Hier ist eine kurze Version, die sich gut für die Webseite oder direkt für die GitHub-README eignet:

OrbitHub auf dem Raspberry Pi installieren

OrbitHub lässt sich direkt auf einem Raspberry Pi installieren. Voraussetzung ist ein Raspberry Pi mit einem aktuellen Raspberry Pi OS sowie eine bestehende Internetverbindung.

1. System aktualisieren

Öffne ein Terminal und aktualisiere zunächst das System:

sudo apt update
sudo apt upgrade -y

2. Git installieren

Falls Git noch nicht installiert ist:

sudo apt install git -y

3. OrbitHub herunterladen

Klone das OrbitHub-Repository von GitHub:

git clone https://github.com/OrbitHubApp/orbithub.git

Wechsle anschließend in das Projektverzeichnis:

cd orbithub

4. OrbitHub installieren

Folge nun den Installationsschritten des Projekts, um die benötigten Abhängigkeiten zu installieren und OrbitHub zu konfigurieren.

Nach erfolgreicher Einrichtung kann OrbitHub auf dem Raspberry Pi gestartet und über einen Webbrowser im lokalen Netzwerk aufgerufen werden.

Projekt auf GitHub:
https://github.com/OrbitHubApp/orbithub

---

Ausführliche Installation, angefangen vom nackten RaspberryPi:
https://orbithubapp.de/installation/



