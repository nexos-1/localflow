import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localflow.settings import Settings
from localflow.web.app import create_app
with tempfile.TemporaryDirectory() as tmp:
    s = Settings(str(Path(tmp) / 'config.json'))
    assert s.get('ui_language') == 'de'
    app = create_app(s, None)
    client = app.test_client()
    def page():
        return client.get('/', base_url='http://127.0.0.1:5111').get_data(as_text=True)
    assert 'Einstellungen' in page()
    s.set('ui_language', 'en')
    assert 'Settings' in page() and '<html lang="en">' in page()
    assert 'en-US' in page() and 'No dictations yet.' in page()
    assert s.get('language') == 'auto'
    assert Settings(s.path).get('ui_language') == 'en'
print('Interface localization tests passed')
from localflow.i18n import translate, dashboard_messages
from localflow.web.app import _coerce_setting
assert translate('Lade Modelle …', 'en') == 'Loading models …'
assert translate('Beenden', 'en') == 'Quit'
assert translate('Maximale Dauer ({duration} s) erreicht.', 'en', duration=300) == 'Maximum duration (300 s) reached.'
assert dashboard_messages('unknown') == dashboard_messages('de')
for invalid in ('fr', '', None, 3, {}, ['en']):
    try:
        _coerce_setting('ui_language', invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted invalid interface language')
with tempfile.TemporaryDirectory() as tmp:
    s = Settings(str(Path(tmp) / 'config.json'))
    app = create_app(s, None)
    client = app.test_client()
    for lang in ('en', 'de'):
        response = client.post('/api/settings', json={'ui_language': lang},
                               base_url='http://127.0.0.1:5111', headers={'X-LocalFlow': '1'})
        assert response.status_code == 200
        assert Settings(s.path).get('ui_language') == lang
        assert s.get('language') == 'auto'
    response = client.post('/api/settings', json={'ui_language': '<script>alert(1)</script>'},
                           base_url='http://127.0.0.1:5111', headers={'X-LocalFlow': '1'})
    assert s.get('ui_language') == 'de'
    assert 'ui_language' in response.json['ignored']
print('Validation, persistence and native translations passed')

# Parse rendered scripts if Node is available (also catches quoting regressions).
import re
import shutil
import subprocess
from unittest.mock import patch
from localflow.i18n import _CATALOG
with tempfile.TemporaryDirectory() as tmp:
    s = Settings(str(Path(tmp) / 'config.json'))
    app = create_app(s, None)
    app.testing = True
    client = app.test_client()
    for lang in ('de', 'en'):
        s.set('ui_language', lang)
        text = client.get('/', base_url='http://127.0.0.1:5111').get_data(as_text=True)
        assert '{{' not in text
        assert 'ui_language: $("#s-ui_language").value' in text
        if shutil.which('node'):
            for script in re.findall(r'<script>(.*?)</script>', text, re.S):
                subprocess.run(['node', '--check'], input=script, text=True, encoding="utf-8", check=True, timeout=15,
                               capture_output=True)
    malicious = '\"\'` ${alert(1)} </script><script>alert(1)</script>'
    with patch.dict(_CATALOG['dashboard']['copied'], en=malicious):
        text = client.get('/', base_url='http://127.0.0.1:5111').get_data(as_text=True)
        assert '</script><script>alert(1)</script>' not in text
        if shutil.which('node'):
            for script in re.findall(r'<script>(.*?)</script>', text, re.S):
                subprocess.run(['node', '--check'], input=script, text=True, encoding="utf-8", check=True, timeout=15,
                               capture_output=True)
print('Rendered scripts and hostile translation escaping passed')


from types import SimpleNamespace
from localflow.web.app import _apply_runtime_changes
calls = []
main = SimpleNamespace(
    overlay=SimpleNamespace(set_language=lambda value: calls.append(value)),
    tray=SimpleNamespace(update_menu=lambda: calls.append('menu')))
_apply_runtime_changes(main, s, {'ui_language'})
assert calls == ['en', 'menu']
print('Runtime language change updates overlay and tray')
