import contextvars
from typing import Dict

DEFAULT_LANG = "de"
SUPPORTED_LANGS = ("de", "en")

_current_lang: contextvars.ContextVar[str] = contextvars.ContextVar("current_lang", default=DEFAULT_LANG)


def set_current_lang(lang_code: str) -> None:
    if lang_code not in SUPPORTED_LANGS:
        lang_code = DEFAULT_LANG
    _current_lang.set(lang_code)


def get_current_lang() -> str:
    return _current_lang.get()


TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "nav.dashboard": {"de": "Übersicht", "en": "Dashboard"},
    "nav.satellites": {"de": "Satelliten", "en": "Satellites"},
    "satellites.eyebrow": {"de": "SATELLITENKATALOG", "en": "SATELLITE CATALOG"},
    "satellites.heading": {"de": "Alle geladenen Satelliten", "en": "All loaded satellites"},
    "satellites.intro": {"de": "Vollständige Liste aller Satelliten aus der aktuell geladenen TLE-Datei. Name oder NORAD-ID durchsuchen und direkt zu den nächsten Überflügen springen.", "en": "Full list of all satellites from the currently loaded TLE file. Search by name or NORAD ID and jump straight to the next passes."},
    "satellites.loaded_label": {"de": "Satelliten geladen", "en": "satellites loaded"},
    "satellites.search_label": {"de": "Suche", "en": "Search"},
    "satellites.search_placeholder": {"de": "Name oder NORAD-ID ...", "en": "Name or NORAD ID ..."},
    "satellites.sort_label": {"de": "Sortierung", "en": "Sort"},
    "satellites.sort_name": {"de": "Name (A-Z)", "en": "Name (A-Z)"},
    "satellites.sort_norad": {"de": "NORAD-ID", "en": "NORAD ID"},
    "satellites.shown_label": {"de": "Angezeigt", "en": "Shown"},
    "satellites.total_label": {"de": "Gesamt", "en": "Total"},
    "satellites.col_name": {"de": "Name", "en": "Name"},
    "satellites.col_norad": {"de": "NORAD-ID", "en": "NORAD ID"},
    "satellites.col_action": {"de": "Aktion", "en": "Action"},
    "satellites.view_passes": {"de": "Überflüge anzeigen", "en": "View passes"},
    "satellites.no_search_results": {"de": "Keine Satelliten für diese Suche gefunden.", "en": "No satellites found for this search."},
    "satellites.no_tle_title": {"de": "Keine TLE-Daten verfügbar", "en": "No TLE data available"},
    "satellites.no_tle_desc": {"de": "Es wurden noch keine Satellitendaten geladen.", "en": "No satellite data has been loaded yet."},
    "nav.new_satellites": {"de": "Neue Satelliten", "en": "New Satellites"},
    "nav.map": {"de": "Karte", "en": "Map"},
    "nav.sources": {"de": "Daten & Quellen", "en": "Data & Sources"},
    "nav.passes": {"de": "Überflüge", "en": "Passes"},
    "nav.visibility": {"de": "Visuell", "en": "Visual"},
    "nav.downloads": {"de": "Downloads", "en": "Downloads"},
    "nav.statistics": {"de": "Statistik", "en": "Statistics"},
    "nav.settings": {"de": "Einstellungen", "en": "Settings"},
    "nav.history": {"de": "Historie", "en": "History"},
    "nav.about": {"de": "Über OrbitHub", "en": "About OrbitHub"},
    "nav.info": {"de": "Info & Kontakt", "en": "Info & Contact"},
    "nav.support": {"de": "Unterstützung", "en": "Support"},
    "nav.open": {"de": "Navigation öffnen", "en": "Open navigation"},
    "nav.home_aria": {"de": "OrbitHub Startseite", "en": "OrbitHub home"},
    "nav.main_aria": {"de": "Hauptnavigation", "en": "Main navigation"},
    "loading.text": {"de": "Wird geladen – Berechnung läuft, bitte kurz warten…", "en": "Loading – calculation in progress, please wait…"},
    "sidebar.locator": {"de": "Locator", "en": "Locator"},
    "sidebar.check_updates": {"de": "Nach Updates suchen", "en": "Check for updates"},
    "header.welcome": {"de": "Willkommen zurück,", "en": "Welcome back,"},
    "header.local_time": {"de": "Ortszeit", "en": "Local time"},
    "lang.switch_aria": {"de": "Sprache", "en": "Language"},
    "dashboard.eyebrow": {"de": "SYSTEMSTATUS", "en": "SYSTEM STATUS"},
    "dashboard.tle_title": {"de": "TLE-Datendienst", "en": "TLE Data Service"},
    "dashboard.tle_desc": {"de": "Automatische Bereitstellung aktueller Satellitenbahndaten für Amateurfunkanwendungen.", "en": "Automatic delivery of up-to-date satellite orbit data for amateur radio use."},
    "dashboard.all_nominal": {"de": "Alle Systeme nominal", "en": "All systems nominal"},
    "dashboard.station_link": {"de": "Zur Station", "en": "Go to station"},
    "dashboard.active_source": {"de": "Aktive Quelle", "en": "Active source"},
    "dashboard.orbit_data": {"de": "Satellitenbahndaten", "en": "Orbit data"},
    "dashboard.records": {"de": "Datensätze", "en": "Records"},
    "dashboard.records_total": {"de": "Satelliten insgesamt", "en": "Satellites total"},
    "dashboard.file_size": {"de": "Dateigröße", "en": "File size"},
    "dashboard.last_update": {"de": "Letzte Aktualisierung", "en": "Last update"},
    "dashboard.calculating": {"de": "wird berechnet …", "en": "calculating …"},
    "dashboard.preferred_source": {"de": "Bevorzugte Quelle", "en": "Preferred source"},
    "dashboard.user_config": {"de": "Benutzerkonfiguration", "en": "User configuration"},
    "dashboard.fallback_used": {"de": "Fallback verwendet", "en": "Fallback used"},
    "dashboard.fallback_note": {"de": "Ersatzquelle bei Ausfall", "en": "Backup source on failure"},
    "dashboard.update_duration": {"de": "Aktualisierungsdauer", "en": "Update duration"},
    "dashboard.last_error": {"de": "Letzter Fehler", "en": "Last error"},
    "dashboard.new_satellites": {"de": "Neue Satelliten", "en": "New satellites"},
    "dashboard.since_last_update": {"de": "seit letztem Update", "en": "since last update"},
    "dashboard.updated_satellites": {"de": "Aktualisierte Satelliten", "en": "Updated satellites"},
    "dashboard.removed_satellites": {"de": "Entfernte Satelliten", "en": "Removed satellites"},
    "dashboard.unchanged_satellites": {"de": "Unveränderte Satelliten", "en": "Unchanged satellites"},
    "dashboard.services_aria": {"de": "OrbitHub Dienste", "en": "OrbitHub services"},
    "dashboard.update_dataset": {"de": "Datensätze aktualisieren", "en": "Update datasets"},
    "dashboard.website": {"de": "Webseite", "en": "Website"},
    "dashboard.info_contact": {"de": "Info & Kontakt", "en": "Info & Contact"},
    "dashboard.refresh_prefix": {"de": "Nächster automatischer Reload in", "en": "Next automatic reload in"},
    "status.no_error": {"de": "Kein Fehler", "en": "No error"},
    "state.online": {"de": "ONLINE", "en": "ONLINE"},
    "state.error": {"de": "FEHLER", "en": "ERROR"},
    "value.none": {"de": "Keine", "en": "None"},
    "value.yes": {"de": "Ja", "en": "Yes"},
    "value.no": {"de": "Nein", "en": "No"},
    "status.never": {"de": "Noch nie", "en": "Never"},
    "unit.min": {"de": "Min.", "en": "min"},
    "unit.sec": {"de": "Sek.", "en": "sec"},
    "relative.just_now": {"de": "vor weniger als 1 Min.", "en": "less than 1 min ago"},
    "relative.min_one": {"de": "vor 1 Min.", "en": "1 min ago"},
    "relative.min_n": {"de": "vor {n} Min.", "en": "{n} min ago"},
    "relative.hour_one": {"de": "vor 1 Std.", "en": "1 hour ago"},
    "relative.hour_n": {"de": "vor {n} Std.", "en": "{n} hours ago"},
    "relative.day_one": {"de": "vor 1 Tag", "en": "1 day ago"},
    "relative.day_n": {"de": "vor {n} Tagen", "en": "{n} days ago"},
    "relative.unavailable": {"de": "Zeitabstand nicht verfügbar", "en": "Time gap unavailable"},
    "header.local_time_zone": {"de": "Ortszeit ({zone})", "en": "Local time ({zone})"},
    "update.dataset_loading": {"de": "Datensätze werden geladen …", "en": "Loading datasets …"},
    "update.dataset_running": {"de": "OrbitHub lädt aktuelle TLE-Daten von der Quelle. Dies kann etwa ein bis zwei Minuten dauern.", "en": "OrbitHub is loading current TLE data from the source. This can take about one to two minutes."},
    "update.dataset_success": {"de": "Aktualisierung erfolgreich abgeschlossen. Das Dashboard wird neu geladen.", "en": "Update completed successfully. The dashboard will reload."},
    "update.dataset_done": {"de": "Aktualisierung abgeschlossen", "en": "Update complete"},
    "update.dataset_retry": {"de": "Erneut aktualisieren", "en": "Retry update"},
    "update.dataset_failed_prefix": {"de": "Aktualisierung fehlgeschlagen: ", "en": "Update failed: "},
    "update.http_error_prefix": {"de": "HTTP-Fehler ", "en": "HTTP error "},
    "update.check_failed": {"de": "Pruefung nicht moeglich.", "en": "Check not possible."},
    "update.check_failed_offline": {"de": "Pruefung nicht moeglich - keine Verbindung zu GitHub.", "en": "Check not possible - no connection to GitHub."},
    "update.available_prefix": {"de": "Update verfuegbar: v", "en": "Update available: v"},
    "update.new_version_prefix": {"de": "Neue Version verfuegbar: v", "en": "New version available: v"},
    "update.view_instructions": {"de": "Anleitung ansehen", "en": "View instructions"},
    "update.follow_steps": {"de": ". Folge den Schritten unten, um zu aktualisieren.", "en": ". Follow the steps below to update."},
    "update.up_to_date_prefix": {"de": "Du hast die aktuellste Version (v", "en": "You have the latest version (v"},
    "update.already_up_to_date_prefix": {"de": "Du hast bereits die aktuellste Version (v", "en": "You already have the latest version (v"},
}


def t(key: str) -> str:
    lang_code = get_current_lang()
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang_code) or entry.get(DEFAULT_LANG) or key
