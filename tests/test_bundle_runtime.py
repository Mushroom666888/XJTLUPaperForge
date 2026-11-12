"""Launcher lifecycle and protected application-resource boundaries."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import bundle_entry
import runtime_paths


class BundleRuntimeTests(unittest.TestCase):
    def test_old_running_build_is_not_reported_as_new_build_ready(self):
        from app import existing_url, PROJECT_ROOT
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)/'ui.json'
            state.write_text(json.dumps({'project_root': str(PROJECT_ROOT), 'port': 12345, 'instance': 'same'}))
            for build in ({}, {'version': '0.1-old', 'source_sha256': '0'*64}):
                health = dict(app='XJTLUPaperForge', instance='same', **build)
                with self.subTest(build=build), patch('app.urlopen', return_value=io.BytesIO(json.dumps(health).encode())):
                    with self.assertRaisesRegex(RuntimeError, '其他版本'):
                        existing_url(state)

    def test_repeated_launch_uses_existing_health_without_detached_child(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch('settings.DATA_ROOT', Path(temporary)), \
             patch('app.existing_url', return_value='http://127.0.0.1:12345'), \
             patch('bundle_entry.subprocess.Popen') as spawn, \
             patch('browser_config.detect_browsers', return_value={'chrome': 'chrome.exe', 'edge': 'edge.exe'}), \
             patch('webbrowser.open') as browser, patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(bundle_entry.launch(open_browser=True), 0)
            spawn.assert_called_once()
            self.assertEqual(spawn.call_args.args[0], ['chrome.exe', 'http://127.0.0.1:12345'])
            browser.assert_not_called()
            self.assertIn('"ready": true', out.getvalue())

    def test_unready_launch_reaps_its_own_process(self):
        process = Mock(); process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temporary, \
             patch('settings.DATA_ROOT', Path(temporary)), patch('app.existing_url', return_value=None), \
             patch('bundle_entry.subprocess.Popen', return_value=process), \
             patch('bundle_entry.time.monotonic', side_effect=[0, 21]):
            with self.assertRaisesRegex(RuntimeError, '未能就绪'):
                bundle_entry.launch(open_browser=False)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_whole_macos_bundle_is_protected_from_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()/'PaperForge.app'
            with patch.object(runtime_paths, 'FROZEN', True), \
                 patch.object(runtime_paths, 'INSTALL_ROOT', root/'Contents/MacOS'), \
                 patch.object(runtime_paths, 'RESOURCE_ROOT', root/'Contents/Frameworks'):
                for folder in (root, root/'Contents', root/'Contents/Resources/papers'):
                    with self.assertRaisesRegex(ValueError, '程序目录之外'):
                        runtime_paths.external_directory(folder)
                self.assertEqual(runtime_paths.external_directory(root.parent/'papers'), root.parent/'papers')
