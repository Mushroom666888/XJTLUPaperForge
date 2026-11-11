import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Jobs, Server, validate_export
from install import install_skill


class WorkflowTests(unittest.TestCase):
    def test_courses_are_normalized_and_invalid_inputs_rejected(self):
        self.assertEqual(validate_export({'courses': [' abc123 ', 'ABC123', 'DEF456'], 'scale': 3.125}),
                         (['ABC123', 'DEF456'], 3.125))
        for payload in ({'courses': []}, {'courses': ['../../private']}, {'courses': ['ABC123'], 'scale': True},
                        {'courses': ['ABC123'], 'scale': 100}, {'courses': [None]}):
            with self.assertRaises(ValueError):
                validate_export(payload)

    def test_success_partial_and_zero_results_remain_distinct(self):
        def runner(script, args, consume):
            if script == 'login.py':
                return 0
            code = args[0]
            if code == 'NON000':
                consume('未找到 NON000 的试卷。')
                return 0
            consume('共发现 2 套试卷，开始导出 PDF。')
            consume(f'✓ {code}_2025-26_F.pdf（9 页，已校验）')
            if code == 'DEF456':
                consume('✗ 网站将试卷标记为封存')
                return 1
            consume(f'✓ {code}_2025-26_R.pdf（8 页，已校验）')
            return 0
        jobs = Jobs(runner)
        jobs.state['results'] = [dict(course=code, status='pending', expected=None, papers=[], errors=[], message='')
                                 for code in ['ABC123', 'DEF456', 'NON000']]
        jobs.work('export', ['ABC123', 'DEF456', 'NON000'], 2)
        state = jobs.snapshot()
        self.assertEqual([r['status'] for r in state['results']], ['complete', 'partial', 'empty'])
        self.assertEqual(state['phase'], 'review')
        self.assertFalse(state['active'])
        self.assertIn('封存', state['results'][1]['message'])

    def test_failed_login_does_not_start_an_export(self):
        calls = []
        def runner(script, args, consume):
            calls.append(script)
            return 1
        jobs = Jobs(runner)
        jobs.work('export', ['ABC123'], 2)
        self.assertEqual(calls, ['login.py'])
        self.assertEqual(jobs.snapshot()['phase'], 'error')
        self.assertFalse(jobs.snapshot()['login_ready'])

    def test_running_job_rejects_duplicate_start(self):
        jobs = Jobs()
        jobs.update(active=True)
        with self.assertRaises(RuntimeError):
            jobs.start('login')


class LocalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(jobs=Jobs(lambda *args: 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, payload=None, token=True, **headers):
        if token:
            headers['X-PaperForge-Token'] = self.server.token
        data = json.dumps(payload).encode() if payload is not None else None
        return urlopen(Request(self.base + path, data=data, headers=headers), timeout=3)

    def test_page_and_assets_are_served_but_files_are_not_exposed(self):
        with self.request('/') as response:
            body = response.read().decode()
            self.assertIn('XJTLUPaperForge', body)
            self.assertIn(self.server.token, body)
            self.assertNotIn('__APP_TOKEN__', body)
        with self.request('/api/status') as response:
            self.assertEqual(json.load(response)['phase'], 'idle')
        with self.assertRaises(HTTPError) as error:
            self.request('/../settings.py')
        self.assertEqual(error.exception.code, 404)

    def test_api_rejects_missing_token_cross_origin_and_wrong_host(self):
        for path, payload, token, headers in [('/api/status', None, False, {}),
                                             ('/api/login', {}, True, {'Origin': 'https://example.test'}),
                                             ('/', None, False, {'Host': 'attacker.test'})]:
            with self.assertRaises(HTTPError) as error:
                self.request(path, payload, token, **headers)
            self.assertEqual(error.exception.code, 403)

    def test_invalid_export_does_not_start_job(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/api/export', {'courses': ['../ABC123']})
        self.assertEqual(error.exception.code, 400)
        self.assertFalse(self.server.jobs.snapshot()['active'])


class PortableInstallationTests(unittest.TestCase):
    def test_skill_resolves_checkout_from_installed_location_with_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / 'a different checkout'
            bundle = project / 'skill/xjtlu-paperforge/scripts'
            bundle.mkdir(parents=True)
            real_root = Path(__file__).resolve().parent.parent
            (bundle / 'launch.py').write_bytes((real_root / 'skill/xjtlu-paperforge/scripts/launch.py').read_bytes())
            (bundle.parent / 'SKILL.md').write_text('---\nname: xjtlu-paperforge\n---\n')
            (project / 'app.py').touch()
            (project / 'settings.py').touch()
            installed = install_skill(project, Path(temporary) / 'another codex home/skills')
            spec = importlib.util.spec_from_file_location('installed_launcher', installed / 'scripts/launch.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.find_project(installed), project.resolve())
            self.assertFalse((project / 'exam_pages').exists())


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from browser_session import _find_chrome
        try:
            executable = _find_chrome()
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=executable, headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.calls = []
        def runner(script, args, consume):
            self.calls.append((script, args))
            if script != 'login.py':
                consume('共发现 1 套试卷，开始导出 PDF。')
                consume(f'✓ {args[0]}_2025-26_F.pdf（9 页，已校验）')
            return 0
        self.server = Server(jobs=Jobs(runner))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.page = self.browser.new_page(viewport={'width': 1200, 'height': 850})
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}')

    def tearDown(self):
        self.page.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_course_form_runs_ordered_jobs_and_displays_verified_results(self):
        from playwright.sync_api import expect
        self.page.locator('#courses').fill('abc123, DEF456 abc123')
        self.page.locator('input[value="3.125"]').check()
        self.page.locator('#submit').click()
        expect(self.page.locator('#message')).to_have_text('处理结束，2 份 PDF 已通过校验。')
        expect(self.page.locator('.result.complete')).to_have_count(2)
        expect(self.page.locator('.file-list')).to_contain_text(['ABC123_2025-26_F.pdf', 'DEF456_2025-26_F.pdf'])
        self.assertEqual(self.calls, [('login.py', []), ('batch_capture.py', ['ABC123', '--scale', '3.125']),
                                     ('batch_capture.py', ['DEF456', '--scale', '3.125'])])
        self.assertEqual(self.errors, [])

    def test_invalid_input_is_blocked_and_mobile_layout_fits(self):
        from playwright.sync_api import expect
        self.page.set_viewport_size({'width': 375, 'height': 812})
        self.page.locator('#courses').fill('../../private')
        self.page.locator('#submit').click()
        expect(self.page.locator('#error')).to_be_visible()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
