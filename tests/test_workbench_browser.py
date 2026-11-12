"""The desktop workbench must not bypass Chrome-first browser selection."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
from browser_config import BrowserPreferences


class WorkbenchBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root/'ui.json'
        self.server = Mock(server_port=12345, instance='workbench')
        self.url = 'http://127.0.0.1:12345'

    def tearDown(self):
        self.temporary.cleanup()

    def exercise(self, available, previous=None, existing=None):
        if previous:
            BrowserPreferences(self.root, lambda: {previous: previous+'.exe'}).select(previous)
        with patch('app.DATA_ROOT', self.root), patch('app.Server', return_value=self.server), \
             patch('browser_config.detect_browsers', return_value=available), \
             patch('subprocess.Popen') as spawn, patch('webbrowser.open', return_value=True) as default:
            if existing is None:
                app.serve_workbench(self.state, open_browser=True)
                self.server.server_close.assert_called_once()
                self.assertFalse(self.state.exists())
            else:
                with patch('sys.argv', ['app.py', '--open']), \
                     patch('app.workbench_lock', return_value=nullcontext(existing)), \
                     patch('app.existing_url', return_value=self.url):
                    app.main()
                self.server.server_close.assert_not_called()
        return spawn, default

    def test_fresh_workbench_uses_chrome_even_with_edge_default_and_saved_choice(self):
        spawn, default = self.exercise({'chrome': 'installed chrome.exe', 'edge': 'edge.exe'}, 'edge')
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0], ['installed chrome.exe', self.url])
        default.assert_not_called()

    def test_both_duplicate_source_launch_paths_use_chrome(self):
        for acquired in (True, False):
            with self.subTest(lock_acquired=acquired):
                spawn, default = self.exercise({'chrome': 'chrome.exe', 'edge': 'edge.exe'}, existing=acquired)
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.args[0], ['chrome.exe', self.url])
                default.assert_not_called()

    def test_no_chrome_uses_explicitly_saved_fallback(self):
        spawn, default = self.exercise({'edge': 'edge.exe'}, 'edge')
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0], ['edge.exe', self.url])
        default.assert_not_called()

    def test_system_browser_only_bootstraps_choice_when_chrome_and_choice_absent(self):
        spawn, default = self.exercise({'edge': 'edge.exe'})
        spawn.assert_not_called()
        default.assert_called_once_with(self.url)
        self.assertFalse((self.root/'browser.json').exists())
        with self.assertRaisesRegex(ValueError, '选择'):
            BrowserPreferences(self.root, lambda: {'edge': 'edge.exe'}).require()

    def test_chrome_launch_failure_never_silently_opens_edge_and_cleans_server(self):
        with patch('app.DATA_ROOT', self.root), patch('app.Server', return_value=self.server), \
             patch('browser_config.detect_browsers', return_value={'chrome': 'chrome.exe', 'edge': 'edge.exe'}), \
             patch('subprocess.Popen', side_effect=OSError('blocked')), patch('webbrowser.open') as default:
            with self.assertRaisesRegex(RuntimeError, 'Google Chrome'):
                app.serve_workbench(self.state, open_browser=True)
        default.assert_not_called()
        self.server.server_close.assert_called_once()
        self.assertFalse(self.state.exists())

    def test_no_browser_mode_does_not_open_any_browser(self):
        with patch('app.Server', return_value=self.server), patch('subprocess.Popen') as spawn, \
             patch('webbrowser.open') as default:
            app.serve_workbench(self.state, open_browser=False)
        spawn.assert_not_called()
        default.assert_not_called()


if __name__ == '__main__':
    unittest.main()
