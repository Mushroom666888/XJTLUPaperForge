"""Independent second-pass regressions: real files/DOM, no school materials."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import batch_capture as batch
from capture_canvas import agree_and_search, collect_search_results
from app import Jobs, public_error
from output_preferences import OutputPreferences
from result_audit import audit_files, consume_result, finalize_result, record_id
from result_fixtures import event, plan, verified, summary
from capture_canvas import parse_exam_metadata, resolve_paper_metadata
from test_exam_metadata import FakePdfPage


def row_for(course):
    return dict(course=course, expected=None, papers=[], errors=[], status='pending', message='')


class CompletionBoundaryTests(unittest.TestCase):
    def test_totals_are_driven_by_each_course_including_explicit_zero(self):
        for total in (0, 1, 3, 7):
            with self.subTest(total=total), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                def runner(script, args, receive):
                    if script == 'login.py': return 0
                    items = plan(receive, 'ABC123', total)
                    for item in items: verified(receive, root/'papers', 'ABC123', item)
                    summary(receive, items)
                    return 0
                jobs = Jobs(runner, OutputPreferences(root/'prefs.json', root/'papers'))
                jobs.state['results'] = [row_for('ABC123')]
                jobs.work('export', ['ABC123'], 2)
                row = jobs.snapshot()['results'][0]
                self.assertEqual(row['expected'], total)
                self.assertEqual(len(row['papers']), total)
                self.assertEqual(row['status'], 'complete' if total else 'empty')
                self.assertEqual(row['errors'], [])

    def test_catalog_and_files_cannot_replace_independent_school_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = row_for('ABC123')
            receive = lambda line: Jobs().consume(row, line)
            items = [{'id': record_id('one'), 'label': 'ABC123 exam 1'}]
            event(receive, 'catalog', total=1, items=items)
            verified(receive, root, 'ABC123', items[0])
            summary(receive, items)
            finalize_result(row, 0, audit_files(row, root, 2), public_error)
            self.assertNotEqual(row['status'], 'complete')
            self.assertIn('独立', ' '.join(row['errors']))

    def test_later_course_removes_earlier_output_before_job_finishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = []
            def runner(script, args, receive):
                if script == 'login.py': return 0
                course = args[0]
                items = plan(receive, course, 1)
                saved.append(verified(receive, root/'papers', course, items[0])[0])
                if course == 'DEF456': saved[0].unlink()
                summary(receive, items)
                return 0
            jobs = Jobs(runner, OutputPreferences(root/'prefs.json', root/'papers'))
            jobs.state['results'] = [row_for(code) for code in ('ABC123', 'DEF456')]
            jobs.work('export', ['ABC123', 'DEF456'], 2)
            state = jobs.snapshot()
            self.assertEqual(state['phase'], 'review')
            self.assertIn('1/2', state['message'])
            self.assertEqual(state['results'][0]['papers'], [])
            self.assertIn('文件不存在', ' '.join(state['results'][0]['errors']))

    def test_cli_checks_published_files_again_before_reporting_complete(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            papers = [batch.PaperLink(f'https://fixture.test/{i}', 'ABC123', i, 1) for i in range(2)]
            saved = []
            def collect(_tab, _course, **kwargs):
                kwargs.get('report', batch.emit)('inventory', total=2)
                return papers
            def extract(_context, _tab, paper, *_args):
                item = {'id': record_id(paper.href), 'label': f'ABC123 exam {paper.index + 1}'}
                path, _ = verified(lambda _: None, root, 'ABC123', item)
                saved.append(path)
                if len(saved) == 2: saved[0].unlink()
                return batch.ExtractionResult(paper, path.stem, str(path), 1, True)
            stack.enter_context(patch.object(batch, 'sync_playwright', return_value=MagicMock()))
            opened = MagicMock(); opened.__enter__.return_value = (MagicMock(), True)
            stack.enter_context(patch.object(batch, 'open_chrome', return_value=opened))
            for name in ('login', 'navigate_to_past_exam_papers', 'agree_and_search'):
                stack.enter_context(patch.object(batch, name))
            stack.enter_context(patch.object(batch, 'collect_all_papers', side_effect=collect))
            stack.enter_context(patch.object(batch, 'extract_one_paper', side_effect=extract))
            stack.enter_context(patch('settings.OUTPUT_ROOT', root))
            output = stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertFalse(batch.batch_capture('ABC123'))
            self.assertIn('归档未完成', output.getvalue())

    def test_single_page_total_change_is_not_missed(self):
        items = [{'href': 'https://fixture.test/1', 'text': 'ABC123', 'index': 0}]
        with patch.object(batch, 'read_search_total', side_effect=[1, 2]), \
             patch.object(batch, 'collect_search_results', return_value=items), \
             patch.object(batch, 'has_next_page', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '总数发生变化'):
                batch.collect_all_papers(object(), 'ABC123')

    def test_duplicate_row_cannot_be_silently_collapsed_when_unique_total_matches(self):
        item = {'href': 'https://fixture.test/1', 'text': 'ABC123', 'index': 0}
        with patch.object(batch, 'read_search_total', return_value=1), \
             patch.object(batch, 'collect_search_results', return_value=[item, dict(item, index=1)]), \
             patch.object(batch, 'has_next_page', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '重复'):
                batch.collect_all_papers(object(), 'ABC123')


class IdentityBoundaryTests(unittest.TestCase):
    def test_stale_text_layer_cannot_override_actual_first_page(self):
        page = FakePdfPage(layer_text='ABC123 2024/25 Final', pdf_text='DEF456 2024/25 Final')
        with self.assertRaisesRegex(ValueError, '课程编号'):
            resolve_paper_metadata('ABC123', 'ABC123 2024/25 Final', '', page, 'ABC123')

    def test_wrong_year_or_exam_type_is_not_relabelled_as_requested_paper(self):
        for metadata in (('ABC123', '2023-24', 'F'), ('ABC123', '2024-25', 'R')):
            with self.subTest(metadata=metadata), patch('capture_canvas.parse_exam_metadata', return_value=metadata):
                with self.assertRaisesRegex(ValueError, '不一致'):
                    resolve_paper_metadata('ABC123', 'ABC123 2024/25 Final', '', object(), 'ABC123')


class TemporaryBrowserLifecycleTests(unittest.TestCase):
    def test_exited_launcher_does_not_leave_owned_profile_holder_alive(self):
        import browser_session
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary).resolve()/'profile'; profile.mkdir()
            port = browser_session._reserve_port()
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            command = [sys.executable, '-c',
                       "import sys,time; f=open(sys.argv[1],'w'); print('ready',flush=True); time.sleep(60)",
                       str(profile/'held-file'), f'--remote-debugging-port={port}', f'--user-data-dir={profile}']
            started = time.time()
            child = subprocess.Popen(command, stdout=subprocess.PIPE, creationflags=flags, start_new_session=os.name!='nt')
            foreign = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'], creationflags=flags)
            try:
                self.assertEqual(child.stdout.readline().strip(), b'ready')
                launcher = MagicMock(); launcher.poll.return_value = 0
                browser = MagicMock(); browser.contexts = [object()]
                playwright = MagicMock(); playwright.chromium.connect_over_cdp.return_value = browser
                with patch('browser_session.tempfile.mkdtemp', return_value=str(profile)), \
                     patch('browser_session._reserve_port', return_value=port), \
                     patch('browser_session.subprocess.Popen', return_value=launcher), \
                     patch('browser_session._wait_for_debug_port'), \
                     patch('browser_session._find_chrome', return_value='unused-browser'), \
                     patch('browser_session.time.time', return_value=started):
                    with browser_session.fresh_chrome_context(playwright, headless=True): pass
                child.wait(timeout=5)
                self.assertIsNotNone(child.poll())
                self.assertIsNone(foreign.poll())
                self.assertFalse(profile.exists())
            finally:
                for process in (child, foreign):
                    if process.poll() is None: process.terminate()
                    process.wait(timeout=5)
                child.stdout.close()


class SearchFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from browser_session import _find_chrome
        try: executable = _find_chrome()
        except RuntimeError as exc: raise unittest.SkipTest(str(exc))
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=executable, headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def search_page(self, delay=None, empty=False, unrelated=False):
        fresh = ('<span class="ivu-page-total">Total 0</span>' if empty else
                 '<span class="ivu-page-total">Total 2</span>'
                 '<div><a href="/PaperDetail/1">ABC123 first</a></div>'
                 '<div><a href="/PaperDetail/2">ABC123 second</a></div>')
        update = '' if delay is None else f'setTimeout(() => results.innerHTML = {json.dumps(fresh)}, {delay});'
        if unrelated:
            update = "document.body.insertAdjacentHTML('beforeend', '<p>Search failed</p>');"
        html = '''<input type="text"><button class="search-btn">Search</button>
            <section id="results"><span class="ivu-page-total">Total 1</span>
            <div><a href="/PaperDetail/old">ABC123 old</a></div></section><script>
            document.querySelector('button').onclick = async () => {
                await fetch('/api/v1/Search/Search', {method:'POST', body:document.querySelector('input').value});
                UPDATE
            };</script>'''.replace('UPDATE', update)
        def route(request):
            if '/api/' in request.request.url:
                request.fulfill(content_type='application/json', body='{}')
            else:
                request.fulfill(content_type='text/html', body=html)
        self.page.route('https://freshness.test/**', route)
        self.page.goto('https://freshness.test/SearchDetail/local')

    def test_successful_http_response_with_unchanged_results_is_not_fresh(self):
        self.search_page()
        with self.assertRaisesRegex(RuntimeError, '搜索结果未更新'):
            agree_and_search(self.page, 'ABC123', timeout_ms=2000)

    def test_delayed_dom_update_does_not_freeze_the_old_smaller_inventory(self):
        self.search_page(delay=1200)
        agree_and_search(self.page, 'ABC123', timeout_ms=4000)
        self.assertEqual(len(batch.collect_all_papers(self.page, 'ABC123')), 2)

    def test_error_notice_does_not_make_old_results_fresh(self):
        self.search_page(unrelated=True)
        with self.assertRaisesRegex(RuntimeError, '搜索结果未更新'):
            agree_and_search(self.page, 'ABC123', timeout_ms=2000)

    def test_real_empty_search_is_allowed_after_explicit_refresh(self):
        self.search_page(delay=100, empty=True)
        agree_and_search(self.page, 'ABC123', timeout_ms=3000)
        self.assertEqual(batch.collect_all_papers(self.page, 'ABC123'), [])

    def test_only_visible_result_rows_and_one_link_per_row_are_collected(self):
        self.page.set_content('''<table><tr><td><a href="https://fixture.test/PaperDetail/1">ABC123</a>
            <a href="https://fixture.test/PaperDetail/1">Details</a></td></tr>
            <tr hidden><td><a href="https://fixture.test/PaperDetail/old">ABC123 old</a></td></tr></table>''')
        found = collect_search_results(self.page)
        self.assertEqual([item['href'] for item in found], ['https://fixture.test/PaperDetail/1'])


if __name__ == '__main__':
    unittest.main()
