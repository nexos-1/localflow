"""Interface messages. Speech recognition settings are deliberately independent.

The dashboard catalog contains trusted template fragments, never user content.
JavaScript messages use Jinja tojson; HTML messages are escaped except the
few explicitly trusted markup fragments. Never put user content in this catalog.
"""
import json
from pathlib import Path

_CATALOG = json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))


def language(value):
    return value if value in ('de', 'en') else 'de'


def dashboard_messages(value):
    return {key: translations[language(value)]
            for key, translations in _CATALOG['dashboard'].items()}


def translate(message, value='de', **values):
    text = _CATALOG['native'].get(message, message) if language(value) == 'en' else message
    return text.format(**values) if values else text
