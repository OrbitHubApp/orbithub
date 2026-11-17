# Changelog

## 4.2.1 „Neptun“ – 17.11.2026

OrbitHub wird zur kleinen Funkstation: digitale Betriebsarten mit dem IC-705 und ein komplett neues Design.

### Neu: Digitale Betriebsarten (FT8, FT4, WSPR)
- Eigene Seite *Digitale Betriebsarten* im neuen Menübereich **Funkbetrieb**, alle Bänder von 160 m bis 70 cm.
- Empfang mit den WSJT-X-Decodern (Host-Dienst `digimode.service`), frühe Auswertung kurz nach Periodenende.
- Senden wie in WSJT-X: Doppelklick auf eine Station, CQ rufen, Auto-Sequenz bis RR73/73, ADIF-Logbuch (die letzten 10 QSOs immer sichtbar), auch Rufzeichen mit Präfix/Suffix.
- Display mit Frequenz, Po/ALC/SWR-Balken (live beim Senden), großem QSO-Feld mit Rufzeichen, Land, Entfernung, Richtung, Rapporten und der gerade laufenden Aussendung; das Gegenrufzeichen wird orange, sobald die Station antwortet.
- Länderzuordnung aus `cty.dat`, Bandwechsel werden in Bandaktivität und „Letzte Periode“ markiert, Rufzeichen im Wasserfall sauber untereinander.
- Automatischer Sendepegel über die ALC, je Band gemerkt.
- **TEST · SWR**: 5 s Dauerton mit Messung von SWR, Po und ALC.
- Sicherheit: Sendefreigabe je Band, QRG-Prüfung vor jeder Aussendung, Probelauf ohne PTT, **STOP** (Esc).
- Spots an PSK Reporter und WSPRnet.

### IC-705
- kappanhang-Erweiterung: Po, ALC und SWR über rigctld (`l METERS`), siehe `tools/rig/kappanhang-fixes.patch`.
- **⟳ Neu verbinden** auf IC-705- und Digital-Seite: startet kappanhang neu und nimmt den Digimode-Empfang wieder auf.
- IC-705-Seite aufgeräumt (gleich breite Spalten, gleich hohe Panels); Relais-Werte werden robust gelesen.

### Design
- Neues Erscheinungsbild im Stil der ISS-Instrumententafeln (US-Segment): rack-weiße Flächen, NASA-Blau, Warnstreifen, dunkle Seitenleiste und Fußzeile, Funk-Panels als dunkle Instrumententafeln.
