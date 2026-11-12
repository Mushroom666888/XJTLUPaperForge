import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Jobs, Server, validate_export
from output_preferences import OutputPreferences
from unittest.mock import patch
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
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.calls = []
        def runner(script, args, consume):
            self.calls.append((script, args))
            if script != 'login.py':
                consume('共发现 1 套试卷，开始导出 PDF。')
                consume(f'✓ {args[0]}_2025-26_F.pdf（9 页，已校验）')
            return 0
        self.server = Server(jobs=Jobs(runner, OutputPreferences(self.root/'preferences.json', self.root/'output')))
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
        self.temp.cleanup()

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

    def test_empty_input_and_standard_quality(self):
        from playwright.sync_api import expect
        self.page.locator('#submit').click()
        expect(self.page.locator('#courses')).to_be_focused()
        expect(self.page.locator('#courses')).to_have_attribute('aria-invalid', 'true')
        self.assertEqual(self.calls, [])
        self.page.locator('#courses').fill('CAN209')
        self.page.locator('#submit').click()
        expect(self.page.locator('.result.complete')).to_have_count(1)
        self.assertEqual(self.calls[-1][1], ['CAN209','--scale','2.0'])

    def test_manual_login_event_prompts_user_then_clears_after_connection(self):
        from playwright.sync_api import expect
        from task_events import PREFIX
        release = threading.Event()
        def runner(script, args, consume):
            consume(PREFIX + json.dumps({'event': 'phase', 'phase': 'waiting'}))
            if not release.wait(15): raise RuntimeError('Login test did not release worker.')
            return 0
        self.server.jobs.runner = runner
        try:
            self.page.locator('#login').click()
            expect(self.page.locator('#mood-title')).to_have_text('请去登录哦')
            expect(self.page.locator('#message')).to_contain_text('Google Chrome 学校页面完成登录')
            expect(self.page.locator('#message')).to_contain_text('登录后会自动继续')
            expect(self.page.locator('#account-label')).to_have_text('学校账号 · 等待登录')
            expect(self.page.locator('#submit')).to_have_text('正在等待登录…')
            self.assertFalse(self.server.jobs.snapshot()['login_ready'])
            self.assertEqual(self.page.locator('#progress').evaluate('node => node.value'), 0)
            self.page.set_viewport_size({'width': 320, 'height': 800})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            release.set()
            expect(self.page.locator('#phase')).to_have_text('账号已连接')
            expect(self.page.locator('#mood-title')).not_to_have_text('请去登录哦')
            expect(self.page.locator('#message')).to_have_text('学校账号已连接，可以开始导出。')
            self.assertEqual(self.errors, [])
        finally:
            release.set()

    def test_native_folder_buttons_persist_cancel_reset_and_open(self):
        from playwright.sync_api import expect
        custom = self.root / '试卷 folder'; custom.mkdir()
        self.server.jobs.picker = lambda _: str(custom)
        self.page.locator('#change-output').click()
        expect(self.page.locator('#output-path')).to_have_text(str(custom))
        self.assertEqual(OutputPreferences(self.root/'preferences.json', self.root/'output').path, custom)
        self.server.jobs.picker = lambda _: None
        self.page.locator('#change-output').click()
        expect(self.page.locator('#toast')).to_contain_text('保留原来')
        expect(self.page.locator('#output-path')).to_have_text(str(custom))
        with patch('app.os.startfile', create=True) as open_folder:
            self.page.locator('#open-output').click()
            expect(self.page.locator('#open-output')).to_be_enabled()
            open_folder.assert_called_with(str(custom))
        self.page.locator('#reset-output').click()
        expect(self.page.locator('#output-path')).to_have_text(str(self.root/'output'))

    def test_moods_follow_actual_stages_without_false_progress(self):
        from playwright.sync_api import expect
        jobs = self.server.jobs
        rows = [dict(course=code, status='pending', expected=None, papers=[], errors=[], message='等待处理') for code in ['CAN209','EEE211']]
        jobs.update(active=True, results=rows, kind='export')
        for phase,mood,moving in [('starting','starting',True),('waiting','idle',False),('searching','searching',True),
                                  ('downloading','downloading',True),('validating','validating',True)]:
            jobs.update(phase=phase, message=phase, current_course='CAN209')
            expect(self.page.locator('body')).to_have_attribute('data-phase',phase)
            expect(self.page.locator('#companion')).to_have_attribute('src',f'/assets/{mood}.png')
            self.assertEqual(self.page.locator('#progress').evaluate('(node) => node.value'), 0)
            animation = self.page.locator('#companion').evaluate('(node) => getComputedStyle(node).animationName')
            self.assertEqual(animation != 'none',moving)
        rows[0].update(status='complete',expected=1,papers=[{'name':'CAN209_2025_F.pdf','pages':3}])
        rows[1].update(status='working',expected=6)
        jobs.update(results=rows,phase='downloading')
        expect(self.page.locator('#progress-count')).to_have_text('1 / 2 门')
        for phase in ('error','review','cancelled'):
            jobs.update(active=False,phase=phase)
            expect(self.page.locator('body')).to_have_attribute('data-phase',phase)
            self.assertEqual(self.page.locator('#progress').evaluate('(node) => node.value'),1)
            self.assertEqual(self.page.locator('#companion').evaluate('(node) => getComputedStyle(node).animationName'),'none')
        rows[1].update(status='complete',papers=[{'name':'EEE211_2025_F.pdf','pages':2}],expected=1)
        jobs.update(results=rows,phase='done')
        expect(self.page.locator('#companion')).to_have_attribute('src','/assets/success.png')
        expect(self.page.locator('#progress-count')).to_have_text('2 / 2 门')
        expect(self.page.locator('#open-results')).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_partial_failure_is_visible_and_retry_resets_progress(self):
        from playwright.sync_api import expect
        def runner(script,args,consume):
            if script == 'login.py': return 0
            consume('共发现 2 套试卷')
            consume('✓ CAN209_2025_F.pdf（3 页，已校验）')
            consume('✗ 网站将试卷标记为封存')
            return 1
        self.server.jobs.runner = runner
        self.page.locator('#courses').fill('CAN209');self.page.locator('#submit').click()
        expect(self.page.locator('.result.partial')).to_have_count(1)
        expect(self.page.locator('#phase')).to_have_text('需要核对')
        expect(self.page.locator('#progress-count')).to_have_text('0 / 1 门')
        expect(self.page.locator('#submit')).to_contain_text('重新整理')
        self.server.jobs.runner = lambda *args: 1
        self.page.locator('#submit').click()
        expect(self.page.locator('#phase')).to_have_text('未完成')
        expect(self.page.locator('.result.partial')).to_have_count(0)
        expect(self.page.locator('#open-results')).to_be_hidden()

    def test_cancel_button_reaches_cooperative_worker(self):
        from playwright.sync_api import expect
        release = threading.Event()
        def runner(*args):
            release.wait(4)
            return 0
        self.server.jobs.runner = runner
        self.page.locator('#courses').fill('CAN209');self.page.locator('#submit').click()
        try:
            expect(self.page.locator('#cancel')).to_be_visible()
            self.page.locator('#cancel').click()
            expect(self.page.locator('#phase')).to_have_text('正在停止')
            self.assertTrue(self.server.jobs.cancel_requested.is_set())
        finally:
            release.set()
        expect(self.page.locator('#phase')).to_have_text('已取消')
        expect(self.page.locator('#submit')).to_be_enabled()
        self.assertEqual(self.page.locator('#progress').evaluate('(node) => node.value'),0)

    def test_reduced_motion_keyboard_focus_and_responsive_sizes(self):
        from playwright.sync_api import expect
        self.page.emulate_media(reduced_motion='reduce')
        self.server.jobs.update(active=True,phase='downloading')
        expect(self.page.locator('body')).to_have_attribute('data-phase','downloading')
        self.assertEqual(self.page.locator('#companion').evaluate('(node) => getComputedStyle(node).animationName'),'none')
        self.server.jobs.update(active=False,phase='idle')
        expect(self.page.locator('#submit')).to_be_enabled()
        self.page.locator('#courses').focus()
        self.page.keyboard.press('Tab')
        expect(self.page.locator('input[value="2"]')).to_be_focused()
        self.page.keyboard.press('ArrowRight')
        expect(self.page.locator('input[value="3.125"]')).to_be_checked()
        for width in (320,375,740,960,1440):
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
