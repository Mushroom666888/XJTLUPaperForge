"""Fault and concurrency checks against local fixtures; no school requests."""
import concurrent.futures
import importlib.util
import io
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from app import Jobs, existing_url
from browser_config import detect_browsers
from browser_session import (read_session, fresh_chrome_context, _reserve_port,
                             browser_process_id, close_recorded_browser, connect_recorded_browser,
                             _cdp_port_alive)
from capture_canvas import (parse_exam_metadata, resolve_paper_metadata, agree_and_search,
                            _is_logged_in, login)
from output_preferences import OutputPreferences
from pdf_quality import verify_pdf, page_fingerprint
from merge_png_to_pdf import merge_png_to_pdf
from settings import PROJECT_ROOT
from task_events import TaskCancelled
from test_exam_metadata import FakePdfPage
from test_pdf_export import make_pages


class MetadataBoundaryTests(unittest.TestCase):
    def test_other_course_suffix_cannot_supply_metadata(self):
        with patch('capture_canvas.parse_exam_metadata', return_value=('MTH102TC', '2024-25', 'F')):
            with self.assertRaisesRegex(ValueError, '课程编号与请求不一致'):
                resolve_paper_metadata('MTH102', 'MTH102TC 2024/25 Final', '', object(), 'MTH102')

    def test_fallback_never_borrows_year_from_another_courses_pdf(self):
        with patch('capture_canvas.parse_exam_metadata', return_value=('EEE211', '2024-25', 'F')):
            with self.assertRaisesRegex(ValueError, '课程编号与请求不一致'):
                resolve_paper_metadata('CAN209', 'CAN209 Final', '', object(), 'CAN209')

    def test_ambiguous_cover_type_remains_unknown(self):
        page = FakePdfPage(pdf_text='CAN209 2024/25 Final / Resit')
        with patch('capture_canvas._ocr_image_text', return_value='CAN209 2024/25 Final / Resit'):
            self.assertEqual(parse_exam_metadata(page)[2], 'unknown')

    def test_cancel_during_pdf_verification_stops_between_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_pages(root)
            pdf = root/'exam.pdf'
            merge_png_to_pdf(root, pdf)
            original = pdf.read_bytes()
            marker = root/'cancel'
            def fingerprint(*args, **kwargs):
                value = page_fingerprint(*args, **kwargs)
                marker.touch()
                return value
            with patch.dict(os.environ, {'XJTLUPAPERFORGE_CANCEL_FILE': str(marker)}), \
                    patch('pdf_quality.page_fingerprint', side_effect=fingerprint) as checked:
                with self.assertRaises(TaskCancelled): verify_pdf(pdf, 2, 192)
            self.assertEqual(checked.call_count, 1)
            self.assertEqual(pdf.read_bytes(), original)


class LifecycleBoundaryTests(unittest.TestCase):
    def test_shutdown_reserves_idle_state_against_new_jobs_and_picker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            jobs = Jobs(preferences=OutputPreferences(root/'preferences.json', root/'papers'))
            jobs.update(active=True)
            with self.assertRaises(RuntimeError): jobs.prepare_shutdown()
            self.assertFalse(jobs.closing)
            jobs.update(active=False)
            jobs.prepare_shutdown()
            for action in (lambda: jobs.start('login'), jobs.change_output, lambda: jobs.select_browser('edge')):
                with self.assertRaises(RuntimeError): action()
            self.assertFalse(jobs.snapshot()['active'])

    def test_malformed_session_never_contacts_a_port(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'session.json'
            for value in ([], {}, {'port': True, 'pid': 4, 'user_data_dir': folder},
                          {'port': 999999, 'pid': 4, 'user_data_dir': folder},
                          {'port': 9222, 'pid': -1, 'user_data_dir': folder},
                          {'port': 9222, 'pid': 4, 'user_data_dir': '../outside'}):
                with self.subTest(value=value):
                    file.write_text(json.dumps(value))
                    with patch('browser_session.SESSION_FILE', str(file)), patch('browser_session._cdp_port_alive') as probe:
                        self.assertIsNone(read_session())
                        probe.assert_not_called()
                    self.assertFalse(file.exists())

    def test_corrupt_ui_state_and_installation_record_allow_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root/'ui.json'
            state.write_text('[]')
            self.assertIsNone(existing_url(state))
            skill = root/'skill'; skill.mkdir()
            (skill/'installation.json').write_text('{broken')
            source = PROJECT_ROOT/'skill/xjtlu-paperforge/scripts/launch.py'
            spec = importlib.util.spec_from_file_location('audit_launcher', source)
            launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
            with patch.dict(os.environ, {'XJTLUPAPERFORGE_HOME': str(PROJECT_ROOT)}):
                self.assertEqual(launcher.find_project(skill), PROJECT_ROOT)

    def test_simultaneous_launches_share_one_real_workbench(self):
        # Slow server creation widens the race after both processes have started.
        code = ('import app,time\nOriginal=app.Server\nclass SlowServer(Original):\n'
                ' def __init__(self,*a,**kw):\n  time.sleep(.7)\n  super().__init__(*a,**kw)\n'
                'app.Server=SlowServer\napp.main()')
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, PYTHONUTF8='1', XJTLUPAPERFORGE_DATA=folder)
            processes, urls = [], []
            try:
                for _ in range(2):
                    processes.append(subprocess.Popen([sys.executable, '-u', '-c', code], cwd=PROJECT_ROOT,
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8'))
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    futures = [pool.submit(process.stdout.readline) for process in processes]
                    urls = [future.result(timeout=15).strip() for future in futures]
                if not all(url.startswith('http://127.0.0.1:') for url in urls):
                    diagnostics = []
                    for url, process in zip(urls, processes):
                        if not url:
                            process.wait(timeout=3)
                            diagnostics.append(process.stderr.read())
                    self.fail(f'Launch failed: {urls}; {diagnostics}')
                self.assertEqual(len(set(urls)), 1)
                deadline = time.monotonic() + 3
                while all(process.poll() is None for process in processes) and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual(sum(process.poll() is None for process in processes), 1)
                with urlopen(urls[0]+'/health', timeout=3) as response:
                    old_instance = json.load(response)['instance']
                owner = next(process for process in processes if process.poll() is None)
                owner.terminate(); owner.wait(timeout=4)
                restart = subprocess.Popen([sys.executable, '-u', '-c', code], cwd=PROJECT_ROOT,
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
                processes.append(restart)
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    restarted = pool.submit(restart.stdout.readline).result(timeout=15).strip()
                urls = [restarted]
                self.assertTrue(restarted.startswith('http://127.0.0.1:'), restarted)
                with urlopen(restarted+'/health', timeout=3) as response:
                    self.assertNotEqual(json.load(response)['instance'], old_instance)
            finally:
                for base in set(urls):
                    if not base.startswith('http://127.0.0.1:'): continue
                    try:
                        with urlopen(base, timeout=3) as response: html = response.read().decode('utf-8-sig')
                        token = re.search(r'name="paperforge-token" content="([^"]+)"', html)[1]
                        urlopen(Request(base+'/api/shutdown', data=b'{}', headers={'X-PaperForge-Token': token}), timeout=3).close()
                    except OSError:
                        pass
                for process in processes:
                    try: process.wait(timeout=4)
                    except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=4)
                    process.stdout.close(); process.stderr.close()


class RealBrowserBoundaryTests(unittest.TestCase):
    def test_auth_requires_positive_marker_and_accepts_automatic_sso(self):
        from playwright.sync_api import sync_playwright
        if 'chrome' not in detect_browsers(): self.skipTest('Chrome is not installed.')
        with sync_playwright() as p, fresh_chrome_context(p, headless=True) as context:
            page = context.new_page()
            def homepage(route):
                route.fulfill(content_type='text/html', body='''<div>Past Exam Papers</div>
                    <button onclick="this.remove(); document.body.insertAdjacentHTML('beforeend',
                    '<a>Logout</a>')">Login</button>''')
            context.route('https://etd.xjtlu.edu.cn/**', homepage)
            page.goto('https://etd.xjtlu.edu.cn')
            page.set_content('<div>Past Exam Papers</div>')
            self.assertFalse(_is_logged_in(page), 'Partly rendered public homepage is not authenticated.')
            page.set_content('<div>Past Exam Papers</div><a hidden>Logout</a>')
            self.assertFalse(_is_logged_in(page), 'Hidden template controls are not authentication evidence.')
            page.set_content('<div>Past Exam Papers</div><a>Logout</a>')
            self.assertTrue(_is_logged_in(page))
            login(page, allow_manual=False)
            self.assertTrue(_is_logged_in(page), 'Automatic SSO should not require manual login.')

    def test_login_diagnostics_do_not_log_query_or_fragment_secrets(self):
        from unittest.mock import Mock
        page = Mock()
        page.url = 'https://etd.xjtlu.edu.cn/?ticket=private-query#/index?code=private-fragment'
        page.wait_for_function.side_effect = RuntimeError('timeout')
        output = io.StringIO()
        with patch('capture_canvas._is_logged_in', return_value=False), redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, '登录状态已失效'):
                login(page, allow_manual=False)
        self.assertIn('https://etd.xjtlu.edu.cn/', output.getvalue())
        self.assertNotIn('private-query', output.getvalue())
        self.assertNotIn('private-fragment', output.getvalue())

    def test_stale_pid_cannot_close_a_different_browser(self):
        from playwright.sync_api import sync_playwright
        available = detect_browsers()
        if 'chrome' not in available: self.skipTest('Chrome is not installed.')
        with sync_playwright() as p:
            for key in ('chrome', 'edge'):
                if key not in available: continue
                with self.subTest(browser=key):
                    port = _reserve_port()
                    with patch('browser_session._reserve_port', return_value=port), \
                         patch('browser_session._find_chrome', return_value=available[key]), \
                         fresh_chrome_context(p, headless=True) as context:
                        page = context.new_page()
                        actual = browser_process_id(context.browser)
                        with self.assertRaisesRegex(RuntimeError, '会话记录已失效'):
                            connect_recorded_browser(p, {'port': port, 'pid': actual + 1000000})
                        with self.assertRaisesRegex(RuntimeError, '会话记录已失效'):
                            close_recorded_browser(p, {'port': port, 'pid': actual + 1000000})
                        self.assertEqual(page.evaluate('6 * 7'), 42)
                        close_recorded_browser(p, {'port': port, 'pid': actual})
                        deadline = time.monotonic() + 3
                        while _cdp_port_alive(port) and time.monotonic() < deadline: time.sleep(.05)
                        self.assertFalse(_cdp_port_alive(port))

    def test_never_resolving_pdf_text_is_bounded(self):
        from playwright.sync_api import sync_playwright
        if 'chrome' not in detect_browsers(): self.skipTest('Chrome is not installed.')
        with sync_playwright() as p, fresh_chrome_context(p, headless=True) as context:
            page = context.new_page()
            page.set_content('<main>local viewer</main>')
            page.evaluate('''() => { window.PDFViewerApplication = {pdfDocument: {
                getPage: async () => ({getTextContent: () => new Promise(() => {})})
            }}; }''')
            import base64
            canvas = {'ok': True, 'dataURL': 'data:image/png;base64,' + base64.b64encode(b'fixture').decode()}
            started = time.monotonic()
            with patch('capture_canvas._capture_rendered_page', return_value=canvas), \
                 patch('capture_canvas._ocr_image_text', return_value='CAN209 2024/25 Final'):
                self.assertEqual(parse_exam_metadata(page, timeout_ms=200), ('CAN209', '2024-25', 'F'))
            self.assertLess(time.monotonic() - started, 3)

    def test_search_does_not_hang_when_response_body_stalls(self):
        from playwright.sync_api import sync_playwright, TimeoutError
        if 'chrome' not in detect_browsers(): self.skipTest('Chrome is not installed.')
        body = b'{"items":[]}'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                html = b'''<input type="text"><button class="search-btn" onclick="fetch('/api/v1/Search/Search',{
                    method:'POST',body:document.querySelector('input').value}).then(r=>r.json())">Search</button>'''
                self.send_response(200); self.send_header('Content-Length', str(len(html))); self.end_headers(); self.wfile.write(html)
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.flush()
                time.sleep(1)
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p, fresh_chrome_context(p, headless=True) as context:
                page = context.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/SearchDetail/local')
                page.wait_for_load_state('networkidle')
                started = time.monotonic()
                with self.assertRaises(TimeoutError): agree_and_search(page, 'CAN209', timeout_ms=300)
                self.assertLess(time.monotonic() - started, 3)
        finally:
            server.shutdown(); server.server_close(); thread.join()
