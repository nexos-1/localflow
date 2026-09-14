"""Insertion regression tests without microphone, model loading or OS input."""
import os
import ast
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from localflow.settings import Settings
from localflow.web.app import create_app

# Exercise the actual orchestration method without importing GPU/audio/OS
# dependencies, so this regression test also runs on headless CI runners.
tree = ast.parse((Path(__file__).parents[1] / 'localflow/main.py').read_text(encoding='utf-8'))
app_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LocalFlowApp')
method = next(n for n in app_class.body if isinstance(n, ast.FunctionDef) and n.name == '_process_inner')
namespace = {'log': logging.getLogger(__name__), 'time': Mock()}
exec(compile(ast.Module(body=[method], type_ignores=[]), 'main.py', 'exec'), namespace)
process_inner = namespace['_process_inner']


class TrailingSpaceTests(unittest.TestCase):
    def insert(self, text, enabled=True, type_max=200, commands=()):
        result = SimpleNamespace(status='ok', final_text=text, commands=list(commands),
                                 language='en', total_ms=0)
        inj = SimpleNamespace(PASTE_OK='ok', PASTE_CLIPBOARD_ONLY='clipboard_only',
                              SMART_SPACING_SKIP_APPS=set(),
                              type_text=Mock(return_value='ok'),
                              paste_text=Mock(return_value='ok'), press_keys=Mock())
        app = SimpleNamespace(
            backends=SimpleNamespace(inject=inj),
            models_ready=Mock(wait=Mock(return_value=True)),
            settings={'trailing_space': enabled, 'type_max_chars': type_max,
                      'smart_spacing': True, 'paste_restore_delay': 1}.copy(),
            pipeline=SimpleNamespace(process=Mock(return_value=result), record_history=Mock()),
            _trim_muted_head=lambda audio, ctx: audio,
            _set_overlay_if_current=Mock())
        process_inner(app, 1, [0], 0, 'notepad', '', 123, None)
        self.assertNotIn(unittest.mock.call(1, 'error'), app._set_overlay_if_current.call_args_list)
        self.assertEqual(result.final_text, text, 'History must retain the original transcript')
        return inj

    def test_consecutive_typed_dictations(self):
        output = ''.join(self.insert(t).type_text.call_args.args[0]
                         for t in ('First sentence.', 'Second sentence.'))
        self.assertEqual(output, 'First sentence. Second sentence. ')

    def test_pasted_dictation(self):
        inj = self.insert('Hello.', type_max=0)
        self.assertEqual(inj.paste_text.call_args.args[0], 'Hello. ')
        self.assertTrue(inj.paste_text.call_args.kwargs['smart_spacing'])

    def test_disabled(self):
        for limit in (0, 200):
            inj = self.insert('Hello.', enabled=False, type_max=limit)
            self.assertEqual((inj.paste_text if limit == 0 else inj.type_text).call_args.args[0], 'Hello.')

    def test_existing_whitespace(self):
        for suffix in (' ', '\n', '\t', '\r\n', '\u00a0'):
            self.assertEqual(self.insert('Hello.' + suffix).type_text.call_args.args[0], 'Hello.' + suffix)

    def test_commands_do_not_get_an_extra_space(self):
        for command in ('backspace', 'enter', 'tab', 'delete', 'escape'):
            inj = self.insert('Hello.', commands=[command])
            self.assertEqual(inj.type_text.call_args.args[0], 'Hello.')
            inj.press_keys.assert_called_once_with([command], target_hwnd=123)

    def test_command_only_does_not_insert_text(self):
        inj = self.insert('', commands=['enter'])
        inj.type_text.assert_not_called()
        inj.paste_text.assert_not_called()
        inj.press_keys.assert_called_once()

    def test_typing_threshold_uses_original_length(self):
        inj = self.insert('x' * 200)
        inj.type_text.assert_called_once()
        self.assertEqual(inj.type_text.call_args.args[0], 'x' * 200 + ' ')

    def test_setting_api_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, 'config.json')
            settings = Settings(path=path)
            self.assertIs(settings.get('trailing_space'), False)
            client = create_app(settings, Mock()).test_client()
            headers = {'X-LocalFlow': '1', 'Host': '127.0.0.1:5111'}
            response = client.post('/api/settings', json={'trailing_space': True}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIs(Settings(path=path).get('trailing_space'), True)
            self.assertIs(client.get('/api/settings', headers=headers).json['trailing_space'], True)
            client.post('/api/settings', json={'trailing_space': 'false'}, headers=headers)
            self.assertIs(settings.get('trailing_space'), True)
            client.post('/api/settings', json={'trailing_space': False}, headers=headers)
            self.assertIs(Settings(path=path).get('trailing_space'), False)


if __name__ == '__main__':
    unittest.main()
