"""Directory, event and cancellation integration tests. No real school data."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Jobs, Server
from output_preferences import OutputPreferences, validate_directory, course_directory
from task_events import PREFIX, check_cancelled, emit, TaskCancelled


def wait_finished(jobs):
    deadline = time.monotonic() + 5
    while jobs.snapshot()['active'] and time.monotonic() < deadline:
        time.sleep(.01)
    if jobs.snapshot()['active']:
        raise AssertionError('Worker did not finish within five seconds')


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.default = self.root / 'default'
        self.custom = self.root / '试卷 archive'
        self.custom.mkdir()
        self.file = self.root / 'settings' / 'preferences.json'
        self.prefs = OutputPreferences(self.file, self.default)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_selection_persists_after_restart_and_reset(self):
        jobs = Jobs(preferences=self.prefs, picker=lambda _: str(self.custom))
        self.assertEqual(jobs.snapshot()['output_dir'], str(self.default))
        self.assertTrue(jobs.change_output())
        self.assertEqual(OutputPreferences(self.file, self.default).path, self.custom)
        self.assertEqual(list(self.custom.iterdir()), [])
        jobs.change_output(reset=True)
        self.assertEqual(OutputPreferences(self.file, self.default).path, self.default)
        self.assertTrue(self.default.is_dir())
        self.assertEqual(list(self.file.parent.glob('*.tmp')), [])

    def test_cancelled_picker_keeps_old_preference_and_unlocks(self):
        self.prefs.save(self.custom)
        before = self.file.read_bytes()
        jobs = Jobs(preferences=self.prefs, picker=lambda _: None)
        self.assertFalse(jobs.change_output())
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse(jobs.snapshot()['folder_busy'])

    def test_unwritable_selection_and_failed_save_do_not_change_preference(self):
        jobs = Jobs(preferences=self.prefs, picker=lambda _: str(self.custom))
        with patch('output_preferences.tempfile.TemporaryFile', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                jobs.change_output()
        self.assertEqual(jobs.snapshot()['output_dir'], str(self.default))
        self.assertFalse(jobs.snapshot()['folder_busy'])
        with patch('output_preferences.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.prefs.save(self.custom)
        self.assertEqual(self.prefs.path, self.default)
        self.assertEqual(list(self.file.parent.glob('*.tmp')), [])

    def test_missing_invalid_and_file_paths_are_rejected(self):
        regular_file = self.root / 'document'; regular_file.touch()
        for value in ('', '../relative', str(self.root / 'missing'), str(regular_file), '\x00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_directory(value)
        if os.name == 'nt':
            for value in ('D:relative', r'\\.\device', r'D:\CON', r'D:\folder:stream', 'D:\\bad. ', r'D:\a?b'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    validate_directory(value)

    def test_corrupt_settings_report_fallback(self):
        self.file.parent.mkdir()
        self.file.write_text('{broken')
        preferences = OutputPreferences(self.file, self.default)
        self.assertEqual(preferences.path, self.default)
        self.assertTrue(preferences.warning)

    def test_course_junction_escape_is_rejected(self):
        link = self.custom / 'ABC123'
        outside = self.root / 'outside'; outside.mkdir()
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(ValueError):
                course_directory(self.custom, 'ABC123')
        finally:
            # Only remove the known junction, never recurse through its target.
            if os.name == 'nt':
                link.rmdir()
            else:
                link.unlink()

    def test_job_freezes_destination_and_blocks_concurrent_picker(self):
        self.prefs.save(self.custom)
        entered, release = threading.Event(), threading.Event()
        def runner(script, args, consume):
            entered.set(); release.wait(4)
            return 1
        jobs = Jobs(runner, self.prefs)
        jobs.start('export', ['ABC123'], 2)
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(RuntimeError):
                jobs.change_output(reset=True)
            self.assertEqual(jobs.snapshot()['job_output_dir'], str(self.custom))
        finally:
            release.set(); wait_finished(jobs)
        jobs.change_output(reset=True)
        self.assertEqual(jobs.snapshot()['job_output_dir'], str(self.custom))
        self.assertEqual(jobs.snapshot()['output_dir'], str(self.default))

    def test_picker_blocks_job_start(self):
        jobs = Jobs(preferences=self.prefs)
        jobs.update(folder_busy=True)
        with self.assertRaises(RuntimeError):
            jobs.start('export', ['ABC123'])

    def test_worker_process_gets_frozen_directory_and_cancel_marker(self):
        jobs = Jobs(preferences=self.prefs)
        jobs.update(job_output_dir=str(self.custom), output_dir=str(self.default))
        jobs.cancel_file = self.root / 'cancel'
        process = MagicMock(); process.__enter__.return_value = process
        process.stdout = io.StringIO(''); process.wait.return_value = 0
        with patch('app.subprocess.Popen', return_value=process) as popen, patch('app.DATA_ROOT', self.root):
            self.assertEqual(jobs.run_script('batch_capture.py', ['ABC123'], lambda _: None), 0)
        environment = popen.call_args.kwargs['env']
        self.assertEqual(environment['XJTLUPAPERFORGE_OUTPUT'], str(self.custom))
        self.assertEqual(environment['XJTLUPAPERFORGE_CANCEL_FILE'], str(jobs.cancel_file))
        self.assertEqual(environment['XJTLUPAPERFORGE_EVENTS'], '1')


class ProgressTests(unittest.TestCase):
    def test_structured_events_are_factual_and_duplicate_verified_events_are_ignored(self):
        jobs = Jobs()
        row = dict(course='ABC123', expected=None, papers=[], errors=[], status='working', message='')
        def event(kind, **kwargs):
            jobs.consume(row, PREFIX + json.dumps(dict(event=kind, **kwargs)))
        event('phase', phase='searching')
        self.assertIsNone(row['expected'])
        event('catalog', total=2)
        event('paper', name='ABC123_2025_F.pdf', retry=True)
        event('paper', name='ABC123_2025_F.pdf')
        self.assertTrue(jobs.snapshot()['retrying'])
        event('phase', phase='validating')
        for i in range(1000):
            event('pages', done=i, total=1000)
        self.assertEqual(jobs.snapshot()['pages_done'], 999)
        self.assertEqual(row['papers'], [])
        for _ in range(2):
            event('verified', name='ABC123_2025_F.pdf', pages=1000)
        self.assertEqual(len(row['papers']), 1)
        jobs.cancel_requested.set()
        jobs.update(phase='cancelling')
        event('phase', phase='downloading')
        self.assertEqual(jobs.snapshot()['phase'], 'cancelling')

    def test_cancel_stops_later_courses_preserves_verified_results_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prefs = OutputPreferences(root/'preferences.json', root/'output')
            calls = []
            def runner(script, args, consume):
                calls.append(script)
                if script == 'login.py': return 0
                consume('共发现 2 套试卷')
                consume('✓ ABC123_2025_F.pdf（2 页，已校验）')
                jobs.cancel()
                self.assertTrue(jobs.cancel_file.exists())
                return 2
            jobs = Jobs(runner, prefs)
            jobs.start('export', ['ABC123','DEF456'])
            wait_finished(jobs)
            state = jobs.snapshot()
            self.assertEqual(state['phase'], 'cancelled')
            self.assertEqual(len(state['results'][0]['papers']), 1)
            self.assertEqual([r['status'] for r in state['results']], ['cancelled','cancelled'])
            self.assertEqual(calls, ['login.py','batch_capture.py'])
            self.assertFalse(jobs.cancel_file.exists())
            jobs.runner = lambda *a: 0
            jobs.start('login'); wait_finished(jobs)
            self.assertEqual(jobs.snapshot()['phase'], 'connected')
            self.assertFalse(jobs.cancel_requested.is_set())

    def test_cancel_signal_is_cooperative_and_events_are_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder)/'cancel'
            with patch.dict(os.environ, {'XJTLUPAPERFORGE_CANCEL_FILE':str(marker)}):
                check_cancelled(); marker.touch()
                with self.assertRaises(TaskCancelled): check_cancelled()
        with patch.dict(os.environ, {'XJTLUPAPERFORGE_EVENTS':'0'}), patch('sys.stdout', new_callable=io.StringIO) as out:
            emit('phase', phase='searching')
            self.assertEqual(out.getvalue(), '')


class OutputApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.custom = self.root/'selected'; self.custom.mkdir()
        self.jobs = Jobs(lambda *a: 0, OutputPreferences(self.root/'settings.json',self.root/'default'), lambda _:str(self.custom))
        self.server = Server(jobs=self.jobs)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def post(self, path, payload=None):
        request = Request(self.url+path, data=json.dumps(payload or {}).encode(), headers={'X-PaperForge-Token':self.server.token})
        with urlopen(request, timeout=5) as response: return json.load(response)

    def test_browser_cannot_supply_arbitrary_path_and_open_uses_actual_destination(self):
        result = self.post('/api/output/select', {'path':str(self.root/'injected')})
        self.assertTrue(result['changed'])
        self.assertEqual(self.jobs.snapshot()['output_dir'], str(self.custom))
        with patch('app.open_directory') as open_folder:
            self.post('/api/open-output');open_folder.assert_called_once_with(str(self.custom))
        previous = self.root/'previous'; previous.mkdir()
        self.jobs.update(job_output_dir=str(previous))
        with patch('app.open_directory') as open_folder:
            self.post('/api/open-output', {'job':True});open_folder.assert_called_once_with(str(previous))
        self.assertFalse((self.root/'injected').exists())

    def test_picker_cancel_and_permission_errors_are_truthful(self):
        self.jobs.picker = lambda _: None
        self.assertFalse(self.post('/api/output/select')['changed'])
        self.jobs.picker = lambda _: str(self.custom)
        with patch('output_preferences.tempfile.TemporaryFile', side_effect=PermissionError()):
            with self.assertRaises(HTTPError) as failure:
                self.post('/api/output/select')
        self.assertEqual(failure.exception.code, 500)
        self.assertFalse(self.jobs.snapshot()['folder_busy'])


if __name__ == '__main__':
    unittest.main()
