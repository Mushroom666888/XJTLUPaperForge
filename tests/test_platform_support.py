"""OS adapters: unit contracts everywhere, native process/AppleScript checks on POSIX."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import browser_session
import folder_picker
import platform_support as desktop
from output_preferences import choose_directory


class DesktopTests(unittest.TestCase):
    def test_data_locations_use_os_conventions_and_ignore_relative_xdg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch('platform_support.Path.home', return_value=root), patch.dict(os.environ, {}, clear=True):
                for platform, suffix in [('win32', 'AppData/Local'), ('darwin', 'Library/Application Support'), ('linux', '.local/share')]:
                    with self.subTest(platform=platform), patch('platform_support.sys.platform', platform):
                        self.assertEqual(desktop.default_data_root(), root/suffix/'XJTLUPaperForge')
                with patch('platform_support.sys.platform', 'linux'):
                    with patch.dict(os.environ, {'XDG_DATA_HOME': str(root/'custom data')}):
                        self.assertEqual(desktop.default_data_root(), root/'custom data/XJTLUPaperForge')
                    with patch.dict(os.environ, {'XDG_DATA_HOME': 'relative'}):
                        self.assertEqual(desktop.default_data_root(), root/'.local/share/XJTLUPaperForge')
                with patch('platform_support.sys.platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': str(root/'local')}):
                    self.assertEqual(desktop.default_data_root(), root/'local/XJTLUPaperForge')

    def test_headless_linux_has_actionable_error_and_wayland_is_accepted(self):
        with patch('platform_support.sys.platform', 'linux'), patch.dict(os.environ, {}, clear=True):
            self.assertFalse(desktop.desktop_available())
            with self.assertRaisesRegex(RuntimeError, '图形桌面'):
                desktop.require_desktop()
            with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}):
                self.assertTrue(desktop.desktop_available())

    def test_picker_prefers_native_tools_and_has_explicit_missing_state(self):
        for platform, installed, expected in [('darwin', {'osascript'}, 'osascript'), ('linux', {'zenity', 'kdialog'}, 'zenity'), ('linux', {'kdialog'}, 'kdialog')]:
            with self.subTest(platform=platform, installed=installed), patch('platform_support.sys.platform', platform), \
                 patch('platform_support.shutil.which', side_effect=lambda name: name if name in installed else None):
                self.assertEqual(desktop.picker_backend(), expected)
        with patch('platform_support.sys.platform', 'linux'), patch('platform_support.shutil.which', return_value=None):
            with patch('platform_support.importlib.util.find_spec', return_value=None):
                self.assertIsNone(desktop.picker_backend())
            with patch('platform_support.importlib.util.find_spec', return_value=object()):
                self.assertEqual(desktop.picker_backend(), 'tkinter')

    def test_open_directory_uses_argv_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()/'试卷 & $(touch sentinel)'; folder.mkdir()
            for platform, command in [('darwin', 'open'), ('linux', 'xdg-open')]:
                with self.subTest(platform=platform), patch('platform_support.sys.platform', platform), \
                     patch('platform_support.require_desktop'), patch('platform_support.shutil.which', return_value=command), \
                     patch('platform_support.subprocess.run') as run:
                    desktop.open_directory(folder)
                    self.assertEqual(run.call_args.args[0], [command, str(folder)])
                    self.assertNotIn('shell', run.call_args.kwargs)
                    run.side_effect = subprocess.CalledProcessError(1, command)
                    with self.assertRaisesRegex(RuntimeError, '文件管理器'):
                        desktop.open_directory(folder)
            with patch('platform_support.sys.platform', 'linux'), patch('platform_support.require_desktop'), \
                 patch('platform_support.shutil.which', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'xdg-open'):
                    desktop.open_directory(folder)
            with self.assertRaises(ValueError):
                desktop.open_directory(folder/'missing')

    def test_native_picker_path_is_data_and_cancellation_is_not_an_error(self):
        initial = Path('/archive/试卷 $(x)')
        chosen = '/archive/试卷 with trailing space '
        for backend in ('osascript', 'zenity', 'kdialog'):
            with self.subTest(backend=backend), patch('folder_picker.subprocess.run') as run:
                run.return_value = subprocess.CompletedProcess([], 0, chosen+'\n', '')
                self.assertEqual(folder_picker.native_choice(initial, backend), chosen)
                command = run.call_args.args[0]
                self.assertTrue(any(str(initial) in arg for arg in command))
                self.assertNotIn('shell', run.call_args.kwargs)
                if backend == 'osascript':
                    self.assertNotIn(str(initial), command[2])
                run.return_value = subprocess.CompletedProcess([], 0 if backend == 'osascript' else 1, '', '')
                self.assertIsNone(folder_picker.native_choice(initial, backend))
                run.return_value = subprocess.CompletedProcess([], 2, '', 'system error')
                with self.assertRaises(RuntimeError):
                    folder_picker.native_choice(initial, backend)
                run.side_effect = FileNotFoundError()
                with self.assertRaises(RuntimeError):
                    folder_picker.native_choice(initial, backend)

    def test_picker_errors_are_forwarded_without_raw_stderr(self):
        for stderr, message in [('PAPERFORGE_PICKER_ERROR:请安装桌面组件\n', '请安装桌面组件'), ('traceback: private data', '系统文件夹选择器未能打开')]:
            with self.subTest(stderr=stderr), patch('output_preferences.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', stderr)):
                with self.assertRaisesRegex(RuntimeError, message):
                    choose_directory(Path.home())

    @unittest.skipUnless(sys.platform == 'darwin', 'AppleScript compilation requires macOS.')
    def test_macos_picker_script_compiles_without_opening_a_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['osacompile', '-o', str(Path(directory)/'picker.scpt'), '-e', folder_picker.MAC_PICKER_SCRIPT], check=True, capture_output=True)


class ProcessTests(unittest.TestCase):
    def test_posix_cleanup_never_signals_the_parent_group(self):
        process = MagicMock(pid=456)
        process.poll.return_value = None
        with patch('browser_session.sys.platform', 'linux'), \
             patch('browser_session.os.getpgid', return_value=123, create=True), \
             patch('browser_session.os.killpg', create=True) as kill_group:
            browser_session._terminate_process_tree(process)
            kill_group.assert_not_called()
            process.terminate.assert_called_once()

    @unittest.skipIf(os.name == 'nt', 'POSIX process groups require a native POSIX runner.')
    def test_owned_posix_process_exits_without_affecting_test_runner(self):
        # A real disposable child in its own session. No browser/user PID is used.
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            self.assertEqual(os.getpgid(process.pid), process.pid)
            self.assertNotEqual(os.getpgrp(), process.pid)
            browser_session._terminate_process_tree(process)
            self.assertEqual(process.returncode, -signal.SIGTERM)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
