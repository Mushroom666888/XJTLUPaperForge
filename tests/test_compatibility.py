"""Host-independent launch and real Chrome/Edge tests. School pages are fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from app import Jobs, Server
from browser_config import BrowserPreferences, detect_browsers, preferred_browser
from install import default_skills_dir
from output_preferences import OutputPreferences
from pdf_quality import verify_pdf
from settings import PROJECT_ROOT
import test_pdf_export as export_tests


class BrowserSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()

    def test_chrome_wins_even_when_a_fallback_was_previously_selected(self):
        prefs = BrowserPreferences(self.root,lambda:{'edge':'edge.exe'})
        prefs.select('edge')
        self.assertEqual(preferred_browser(self.root,{'edge':'edge.exe'}),'edge')
        prefs.detector = lambda:{'chrome':'chrome.exe','edge':'edge.exe'}
        self.assertEqual(prefs.info()['selected'],'chrome')
        with self.assertRaises(ValueError): prefs.select('edge')

    def test_missing_chrome_requires_choice_and_never_runs_arbitrary_path(self):
        prefs = BrowserPreferences(self.root,lambda:{'edge':'edge.exe'})
        self.assertIsNone(prefs.info()['selected'])
        with self.assertRaises(ValueError): prefs.require()
        for value in ('../../evil.exe','firefox',None,True,{'id':'edge'}):
            with self.subTest(value=value), self.assertRaises(ValueError): prefs.select(value)
        prefs.select('edge');self.assertEqual(prefs.require(),'edge')
        self.assertEqual(BrowserPreferences(self.root,lambda:{'edge':'edge.exe'}).require(),'edge')
        prefs.detector=lambda:{}
        with self.assertRaises(ValueError):prefs.require()

    def test_failed_save_keeps_existing_choice(self):
        prefs=BrowserPreferences(self.root,lambda:{'edge':'edge.exe','brave':'brave.exe'})
        prefs.select('edge')
        with patch('browser_config.os.replace',side_effect=OSError('full')):
            with self.assertRaises(OSError):prefs.select('brave')
        self.assertEqual(prefs.require(),'edge')
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_missing_selection_blocks_jobs_and_running_job_keeps_its_browser(self):
        prefs = BrowserPreferences(self.root, lambda: {'edge': 'edge.exe'})
        entered, release = threading.Event(), threading.Event()
        calls = []
        def runner(script, args, consume):
            calls.append(script)
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test worker did not receive release.')
            return 0
        jobs = Jobs(runner=runner, browsers=prefs,
                    preferences=OutputPreferences(self.root/'output.json', self.root/'papers'))
        with self.assertRaises(ValueError): jobs.start('login')
        self.assertEqual(calls, [])
        jobs.update(login_ready=True)
        jobs.select_browser('edge')
        self.assertFalse(jobs.snapshot()['login_ready'])
        try:
            jobs.start('login')
            self.assertTrue(entered.wait(3))
            with self.assertRaises(RuntimeError): jobs.select_browser('edge')
            prefs.detector = lambda: {'chrome': 'chrome.exe', 'edge': 'edge.exe'}
            self.assertEqual(jobs.job_browser, 'edge')
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while jobs.snapshot()['active'] and time.monotonic() < deadline:
                time.sleep(.01)
        self.assertFalse(jobs.snapshot()['active'])
        self.assertEqual(jobs.snapshot()['browser']['selected'], 'chrome')

    def test_browser_profiles_and_sessions_are_isolated(self):
        values=[]
        for browser in ('chrome','edge'):
            env=dict(os.environ,XJTLUPAPERFORGE_BROWSER=browser,XJTLUPAPERFORGE_DATA=str(self.root))
            raw=subprocess.check_output([sys.executable,'-c','import json,settings; print(json.dumps([str(settings.PROFILE_DIR),str(settings.SESSION_FILE)]))'],cwd=PROJECT_ROOT,env=env)
            values.append(json.loads(raw))
        self.assertNotEqual(values[0][0],values[1][0]);self.assertNotEqual(values[0][1],values[1][1])
        self.assertTrue(values[0][0].endswith('chrome_profile'))
        self.assertTrue(values[1][0].endswith('edge_profile'))

    def test_portable_detection_finds_mac_paths_and_linux_commands(self):
        # Discovery tests only; these do not claim full OS compatibility.
        with patch('browser_config.sys.platform','darwin'), patch('browser_config.shutil.which',return_value=None), \
             patch('browser_config.Path.is_file',lambda p:p.as_posix()=='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'):
            self.assertIn('chrome',detect_browsers())
        with patch('browser_config.sys.platform','linux'), patch('browser_config.shutil.which',side_effect=lambda command:'/usr/bin/chromium' if command=='chromium' else None), \
             patch('browser_config.Path.is_file',return_value=True):
            self.assertIn('chromium',detect_browsers())


class SkillPortabilityTests(unittest.TestCase):
    def test_agent_install_locations_and_both_skill_launchers_start_a_real_local_server(self):
        self.assertTrue(str(default_skills_dir('claude')).endswith(str(Path('.claude/skills'))))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            for agent in ('codex','claude'):
                skills=root/f'{agent} with spaces'/'skills'
                result=subprocess.run([sys.executable,str(PROJECT_ROOT/'install.py'),'--agent',agent,'--skills-only','--skills-dir',str(skills)],
                                      cwd=PROJECT_ROOT,capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stderr)
                installed=skills/'xjtlu-paperforge'
                env=dict(os.environ,PYTHONUTF8='1',XJTLUPAPERFORGE_DATA=str(root/f'{agent}-runtime'))
                # Run from an unrelated cwd exactly as an external local agent would.
                launch=subprocess.run([sys.executable,str(installed/'scripts/launch.py'),'--no-browser'],
                                      cwd=root,capture_output=True,text=True,encoding='utf-8',env=env,timeout=20)
                self.assertEqual(launch.returncode,0,launch.stderr)
                state=json.loads((root/f'{agent}-runtime'/'ui.json').read_text())
                base=f'http://127.0.0.1:{state["port"]}'
                with urlopen(base+'/health',timeout=3) as response:
                    self.assertEqual(json.load(response)['app'],'XJTLUPaperForge')
                with urlopen(base,timeout=3) as response: html=response.read().decode('utf-8-sig')
                import re
                token=re.search(r'name="paperforge-token" content="([^"]+)"',html)[1]
                urlopen(Request(base+'/api/shutdown',data=b'{}',headers={'X-PaperForge-Token':token}),timeout=3).close()
            # Detached Windows processes finish their state-file cleanup asynchronously.
            deadline=time.monotonic()+5
            while any(root.glob('*-runtime/ui.json')) and time.monotonic()<deadline:time.sleep(.05)
            self.assertFalse(any(root.glob('*-runtime/ui.json')))
            # Server state is removed just before the process releases its log handle.
            for log in root.glob('*-runtime/logs/app-startup.log'):
                while True:
                    try:log.unlink();break
                    except PermissionError:
                        if time.monotonic()>=deadline:raise
                        time.sleep(.05)


class EdgeExportTests(export_tests.BrowserExportTests):
    """Repeat the real capture/validation tests in actual installed Edge."""
    @classmethod
    def setUpClass(cls):
        edge=detect_browsers().get('edge')
        if not edge:raise unittest.SkipTest('Edge is not installed on this test host.')
        cls.edge_patch=patch('browser_session._find_chrome',return_value=edge)
        cls.edge_patch.start()
        try:super().setUpClass()
        except BaseException:
            if hasattr(cls,'playwright'):cls.playwright.stop()
            cls.edge_patch.stop();raise
    @classmethod
    def tearDownClass(cls):
        try:super().tearDownClass()
        finally:cls.edge_patch.stop()

    def test_actual_browser_pid_is_recorded_for_owned_session(self):
        from browser_session import record_browser_process
        with tempfile.TemporaryDirectory() as folder:
            session_file=Path(folder)/'session.json'
            with patch('browser_session.SESSION_FILE',str(session_file)):
                pid=record_browser_process(self.context.browser,12345,str(Path(folder)/'profile'))
            self.assertGreater(pid,0)
            self.assertEqual(json.loads(session_file.read_text())['pid'],pid)


class FullStackBrowserTests(unittest.TestCase):
    def test_real_edge_ui_to_worker_to_custom_verified_pdf(self):
        self.exercise_browser('edge')

    def test_real_chrome_ui_to_worker_to_custom_verified_pdf(self):
        self.exercise_browser('chrome')

    def exercise_browser(self, browser_id):
        from playwright.sync_api import sync_playwright, expect
        executable=detect_browsers().get(browser_id)
        if not executable:self.skipTest(f'{browser_id} is not installed.')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();output=root/'chosen papers';output.mkdir()
            prefs=OutputPreferences(root/'preferences.json',root/'default')
            # For Edge only, Chrome absence is simulated; browsers/PDFs are real.
            browsers=BrowserPreferences(root,lambda:{browser_id:executable})
            jobs=Jobs(preferences=prefs,browsers=browsers,picker=lambda _:str(output))
            calls=[]
            def runner(script,args,consume):
                calls.append((script,args))
                if script=='login.py':return 0  # Synthetic site requires no school credentials.
                return jobs.run_script('tests/synthetic_export.py',args,consume)
            jobs.runner=runner
            server=Server(jobs=jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch.dict(os.environ,{'XJTLUPAPERFORGE_DATA':str(root/'runtime')}),patch('app.DATA_ROOT',root/'runtime'),sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=executable,headless=True)
                    page=browser.new_page(viewport={'width':1200,'height':900});errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    if browser_id == 'edge':
                        expect(page.locator('#browser-fallback')).to_be_visible()
                        expect(page.locator('#submit')).to_be_disabled()
                        page.locator('#browser-choice').select_option('edge');page.locator('#save-browser').click()
                        expect(page.locator('#browser-help')).to_contain_text('当前使用 Microsoft Edge')
                    else:
                        expect(page.locator('#browser-fallback')).to_be_hidden()
                    page.locator('#change-output').click()
                    expect(page.locator('#output-path')).to_have_text(str(output))
                    page.locator('#courses').fill('CAN209');page.locator('input[value="3.125"]').check()
                    page.locator('#submit').click()
                    try:
                        expect(page.locator('#phase')).to_have_text('归档完成',timeout=60000)
                    except AssertionError as exc:
                        logs = '\n'.join(path.read_text(encoding='utf-8') for path in (root/'runtime/logs').glob('*.log'))
                        self.fail(f'{exc}\nState: {jobs.snapshot()}\nSynthetic worker logs:\n{logs}')
                    expect(page.locator('#progress-count')).to_have_text('1 / 1 门')
                    self.assertEqual(errors,[])
                    expected=output/'CAN209'/'CAN209_2023-24_F.pdf'
                    self.assertEqual(verify_pdf(expected,2,300),2)
                    self.assertEqual(list(output.rglob('*.pdf')),[expected])
                    self.assertEqual(list((root/'runtime').rglob('*.png')),[])
                    self.assertEqual(jobs.job_browser,browser_id)
                    self.assertEqual(BrowserPreferences(root,lambda:{browser_id:executable}).require(),browser_id)
                    # Restoring Chrome availability hides all fallback controls.
                    browsers.detector=lambda:{'chrome':executable}
                    expect(page.locator('#browser-fallback')).to_be_hidden()
                    browser.close()
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
