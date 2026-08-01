# OrbitHub

🇬🇧 English | [🇩🇪 Deutsch](README.de.md)

<p align="center">
  <img src="app/static/img/orbithub-mission-logo.png" alt="OrbitHub Logo" width="220">
</p>

Self-hosted web application for predicting satellite passes for amateur radio use. OrbitHub computes all orbital data locally on your own hardware (e.g. a Raspberry Pi) — your observation location and usage data never leave your own network.

At the heart of it is the question every satellite observer asks: when and where in the sky will a given satellite next be visible, and for how long? OrbitHub answers this with precise predictions tailored to your own location.

## Features

- **Dashboard** – status of the setup at a glance: next pass with a live countdown, orbital data freshness, host system metrics.
- **Satellite catalog** – searchable list of all available satellites with NORAD ID.
- **Passes** – rise, culmination, and set times for a chosen satellite over an adjustable time range, including maximum elevation and azimuth.
- **Map** – interactive world map with live position and ground track, your own location, and visibility radius.
- **Visual** – prediction of visible passes of bright objects (e.g. the ISS), including sun and observer position matching.
- **Downloads** – export orbital data as a TLE file (2-line or 3-line format), also available as a fixed link for automatic import into external satellite tracking software.
- **Statistics** – history of TLE updates and system load.
- **Settings** – your own location, callsign, Maidenhead locator, and a custom horizon mask (e.g. for obstruction by buildings).
- **History** – changelog of the application itself.

## Technology

- Backend: [FastAPI](https://fastapi.tiangolo.com/) with Jinja2 templates
- Orbit calculation: [Skyfield](https://rhodesmill.org/skyfield/)
- Orbital data sources: [CelesTrak](https://celestrak.org/) and [SatNOGS](https://db.satnogs.org/) (automatic fallback)
- Deployment: Docker / Docker Compose

## Requirements

- Docker and Docker Compose
- Tested on a Raspberry Pi 3B, but runs on any Docker host (including x86)

## Installation

```bash
git clone <repo-url> orbithub
cd orbithub
cp data/observer-settings.example.json data/observer-settings.json
```

Enter your own location in `data/observer-settings.json` (callsign, Maidenhead locator, or latitude/longitude). Alternatively, this can be done conveniently after startup via the **Settings** page in the web interface.

```bash
docker compose up -d --build
```

OrbitHub is then reachable at `http://<host>:8765`.

### Configuration

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ORBITHUB_REFRESH_HOURS` | `6` | Interval for automatically fetching fresh orbital data |

The port can be changed in `docker-compose.yml` via the `ports` entry. All runtime data (orbital data, settings, history) lives in the `data/` directory, which is mounted as a volume and survives restarts and updates.

### Installing on a Raspberry Pi

OrbitHub can be installed directly on a Raspberry Pi. You'll need a Raspberry Pi running a current Raspberry Pi OS and an existing internet connection.

1. **Update the system**

   ```bash
   sudo apt update
   sudo apt upgrade -y
   ```

2. **Install Git** (if not already installed)

   ```bash
   sudo apt install git -y
   ```

3. **Download OrbitHub**

   ```bash
   git clone https://github.com/OrbitHubApp/orbithub.git
   cd orbithub
   ```

4. **Install OrbitHub**

   Follow the installation steps above to install the required dependencies and configure OrbitHub. Once set up, OrbitHub can be started on the Raspberry Pi and accessed via a web browser on the local network.

Full installation guide, starting from a bare Raspberry Pi: https://orbithubapp.de/installation/

## License

Released under the [MIT license](LICENSE).

## Acknowledgments

Developed by Christian Henkel (DL7AG) for amateur radio use. Contributions and pull requests are welcome.

