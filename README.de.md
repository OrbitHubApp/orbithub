# OrbitHub

[🇬🇧 English](README.md) | 🇩🇪 Deutsch

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
- **Einstellungen** – eigener Standort, Rufzeichen, Maidenhead-Locator und zwei getrennte Horizontmasken: eine für Funk (Überflüge, Merkliste, Polarplot, Exporte) und eine für die visuelle Beobachtung (Seite Visuell) – denn Funksignale erreichen dich oft auch dort, wo Bäume oder Dächer den Blick versperren.
- **IC-705** – Steuerung eines ICOM IC-705 über das Netzwerk (mit [kappanhang](https://github.com/nonoo/kappanhang) als rigctld-Brücke): automatische Doppler-Korrektur, passende Betriebsart je Transponder, manuelle Frequenzeingabe, Live-Anzeige des Geräts und Empfangston im Browser. Überflüge lassen sich anklicken und zeigen einen Polarplot mit Einschätzung der Hörbarkeit.
- **AMSAT Live** – aktuelle Hörberichte von [status.amsat.org](https://status.amsat.org/): welche Satelliten zuletzt tatsächlich gehört wurden und in welcher Betriebsart, mit dem nächsten eigenen Überflug und einem Knopf, der den IC-705 auf Frequenz und Betriebsart einstellt. Mit der **Live-Beobachtung** läuft der IC-705 einfach mit: Jeder gemeldete Satellit wird automatisch eingestellt, sobald er über 10° steht – bei mehreren der höchste. Neue Satelliten mit vorläufiger SatNOGS-Nummer werden automatisch zugeordnet.
- **Digitale Betriebsarten** – FT8, FT4 und WSPR mit dem IC-705 empfangen und senden, direkt im Browser. Dekodiert wird mit den WSJT-X-Decodern; QSOs laufen wie in WSJT-X (Doppelklick, Auto-Sequenz bis 73, ADIF-Logbuch). Großes Display mit Frequenz, Po/ALC/SWR, QSO-Feld (Rufzeichen, Land, Entfernung, Rapporte, laufende Aussendung), Bandaktivität mit Bandwechsel-Markierung und Wasserfall. Automatischer Pegel über die ALC je Band, SWR-Test-Knopf, STOP/Esc, Probelauf ohne PTT. Spots gehen auf Wunsch an PSK Reporter und WSPRnet.
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

### Installation auf dem Raspberry Pi

OrbitHub lässt sich direkt auf einem Raspberry Pi installieren. Voraussetzung ist ein Raspberry Pi mit einem aktuellen Raspberry Pi OS sowie eine bestehende Internetverbindung.

1. **System aktualisieren**

   ```bash
   sudo apt update
   sudo apt upgrade -y
   ```

2. **Git installieren** (falls noch nicht installiert)

   ```bash
   sudo apt install git -y
   ```

3. **OrbitHub herunterladen**

   ```bash
   git clone https://github.com/OrbitHubApp/orbithub.git
   cd orbithub
   ```

4. **OrbitHub installieren**

   Folge den oben beschriebenen Installationsschritten, um die benötigten Abhängigkeiten zu installieren und OrbitHub zu konfigurieren. Nach erfolgreicher Einrichtung kann OrbitHub auf dem Raspberry Pi gestartet und über einen Webbrowser im lokalen Netzwerk aufgerufen werden.

Ausführliche Installation, angefangen vom nackten Raspberry Pi: https://orbithubapp.de/installation/

## Digitale Betriebsarten (FT8 / FT4 / WSPR) einrichten

Voraussetzung ist die IC-705-Anbindung über kappanhang (siehe [tools/rig/README.md](tools/rig/README.md)), gebaut mit `tools/rig/kappanhang-fixes.patch` – der Patch bringt u. a. die Messwerte Po, ALC und SWR in den rigctld.

1. **Digimode-Dienst auf dem Host installieren** (ohne sudo, holt nur die WSJT-X-Decoder nach `~/digimode/pkg`):

   ```bash
   sh tools/digimode/install.sh
   ```

   Danach läuft `digimode.service` als Benutzerdienst auf Port 8767; OrbitHub im Container spricht ihn über `host.docker.internal` an.

2. **IC-705 vorbereiten:** Betriebsart USB-D und im Menü **SET › Connectors › MOD Input › DATA MOD = WLAN** – sonst tastet das Gerät, gibt aber keine Leistung ab. Die Sendeleistung wird am Gerät eingestellt.

3. **Rufzeichen und Locator** in den **Einstellungen** eintragen.

4. **Empfang:** Im Menü unter *Funkbetrieb* die Seite **Digitale Betriebsarten** öffnen, Betriebsart und Band wählen, **▶ Empfang**. OrbitHub stellt den IC-705 selbst auf Frequenz und USB-D.

5. **Senden:**
   - Unter *Senden erlaubt auf* nur die Bänder anhaken, für die eine passende Antenne angeschlossen ist.
   - Mit **TEST · SWR** einen 5-Sekunden-Dauerton senden und SWR/Po/ALC prüfen.
   - **Probelauf** abwählen, dann **CQ rufen** oder eine Station in der Liste **doppelt anklicken** – der Rest läuft automatisch.
   - **STOP** oder die **Esc**-Taste beendet jede Aussendung sofort.
   - *Pegel automatisch (ALC)* misst den Audiopegel je Band in den ersten Aussendungen selbst ein.

6. **Verbindung weg?** Der Knopf **⟳ Neu verbinden** (IC-705- und Digital-Seite) startet kappanhang neu und nimmt den Empfang wieder auf.

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).

## Danksagung

Entwickelt von Christian Henkel (DL7AG) für den Einsatz im Amateurfunk. Beiträge und Pull Requests sind willkommen.
