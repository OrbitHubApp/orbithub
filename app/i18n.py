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
}


def t(key: str) -> str:
    lang_code = get_current_lang()
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang_code) or entry.get(DEFAULT_LANG) or key
