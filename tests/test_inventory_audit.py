"""Adversarial INT305 5->4 reconciliation with real generated output files."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from app import Jobs
from output_preferences import OutputPreferences
from batch_capture import collect_all_papers
from result_audit import file_sha256
from result_fixtures import event, plan, verified, summary


class InventoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root/'output'

    def run_case(self, count=4, after=None, terminal=True, code=0):
        def runner(script, args, consume):
            if script == 'login.py': return 0
            self.items = plan(consume, 'INT305', 5)
            self.outputs = [verified(consume, self.output, 'INT305', item) for item in self.items[:count]]
            if after: after(consume)
            if terminal: summary(consume, self.items, self.items[:count])
            return code
        jobs = Jobs(runner, OutputPreferences(self.root/'prefs.json', self.output))
        jobs.state['results'] = [dict(course='INT305', status='pending', expected=None, papers=[], errors=[], message='')]
        jobs.work('export', ['INT305'], 3.125)
        self.state = jobs.snapshot()
        self.row = self.state['results'][0]
        return self.row

    def assert_incomplete(self, valid=4):
        self.assertEqual(self.row['expected'], 5)
        self.assertEqual(len(self.row['papers']), valid)
        self.assertEqual(self.state['phase'], 'review')
        self.assertNotEqual(self.row['status'], 'complete')
        self.assertTrue(self.row['errors'])
        self.assertIn(f'{valid}/5', self.state['message'])

    def test_five_expected_four_results_with_zero_exit_is_incomplete(self):
        self.run_case()
        self.assert_incomplete()
        self.assertEqual([item['label'] for item in self.row['missing']], ['INT305 exam 5'])
        self.assertIn('没有收到成功或失败结果', ' '.join(self.row['errors']))

    def test_five_real_files_and_matching_summary_can_complete(self):
        self.run_case(count=5)
        self.assertEqual(self.state['phase'], 'done')
        self.assertEqual(self.row['status'], 'complete')
        self.assertEqual(self.row['errors'], [])

    def test_reduced_total_in_events_or_log_never_rewrites_five(self):
        for source in ('catalog', 'inventory', 'log', 'empty_log'):
            with self.subTest(source=source):
                def change(consume):
                    if source == 'log': consume('共发现 4 套试卷')
                    elif source == 'empty_log': consume('未找到 INT305 的试卷。')
                    else: event(consume, source, total=4, items=self.items[:4])
                self.run_case(after=change)
                self.assert_incomplete()

    def test_missing_terminal_event_never_completes_even_with_five_files(self):
        self.run_case(count=5, terminal=False)
        self.assert_incomplete(valid=5)
        self.assertIn('结束记录', ' '.join(self.row['errors']))

    def test_reported_file_deleted_before_final_audit_is_not_success(self):
        self.run_case(count=5, after=lambda consume: self.outputs[-1][0].unlink())
        self.assert_incomplete()
        self.assertIn('文件不存在', ' '.join(self.row['errors']))

    def test_file_corrupted_after_success_event_is_not_success(self):
        self.run_case(count=5, after=lambda consume: self.outputs[-1][0].write_bytes(b'broken pdf'))
        self.assert_incomplete()

    def test_intact_file_from_other_record_cannot_satisfy_missing_record(self):
        def change(consume):
            path, fields = self.outputs[0]
            target = self.output/'INT305/INT305_5_F.pdf'
            target.write_bytes(path.read_bytes())
            event(consume, 'verified', id=self.items[4]['id'], name=target.name, pages=1, sha256=file_sha256(target))
        self.run_case(after=change)
        self.assert_incomplete()

    def test_duplicate_names_and_unknown_record_are_rejected(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                def change(consume):
                    fields = dict(self.outputs[0][1], id='f'*64 if unknown else self.items[-1]['id'])
                    event(consume, 'verified', **fields)
                self.run_case(after=change)
                self.assert_incomplete()

    def test_failure_reason_is_visible_even_if_process_returns_zero(self):
        def change(consume):
            event(consume, 'paper_failed', id=self.items[-1]['id'], error='网站将试卷标记为封存')
            summary(consume, self.items, self.items[:4], self.items[4:])
        self.run_case(after=change, terminal=False)
        self.assert_incomplete()
        self.assertIn('INT305 exam 5：网站将部分试卷封存', ' '.join(self.row['errors']))

    def test_fatal_or_nonzero_exit_vetoes_complete_inventory(self):
        for code in (0, 1):
            with self.subTest(code=code):
                self.run_case(count=5, code=code,
                              after=(lambda consume: event(consume, 'fatal', error='网络超时')) if code == 0 else None)
                self.assert_incomplete(valid=5)

    def test_legacy_success_text_alone_cannot_create_verified_files(self):
        def runner(script, args, consume):
            if script == 'login.py': return 0
            consume('共发现 5 套试卷')
            for i in range(5): consume(f'✓ INT305_{i}_F.pdf（1 页，已校验）')
            return 0
        jobs = Jobs(runner, OutputPreferences(self.root/'prefs.json', self.output))
        jobs.state['results'] = [dict(course='INT305',status='pending',expected=None,papers=[],errors=[],message='')]
        jobs.work('export', ['INT305'], 2)
        self.assertEqual(jobs.snapshot()['results'][0]['papers'], [])
        self.assertEqual(jobs.snapshot()['phase'], 'review')

    def test_collector_cannot_lose_fifth_link_or_hide_duplicate(self):
        items = [{'href':f'https://fixture.test/{i}', 'text':'INT305','index':i} for i in range(4)]
        for found in (items, items + [items[0]]):
            with self.subTest(count=len(found)), patch('batch_capture.read_search_total',return_value=5), \
                 patch('batch_capture.collect_search_results',return_value=found), \
                 patch('batch_capture.has_next_page',return_value=False):
                with self.assertRaisesRegex(RuntimeError, '学校显示 5 份，实际收集 4 份'):
                    collect_all_papers(object(), 'INT305')

    def test_unknown_school_total_fails_explicitly(self):
        with patch('batch_capture.read_search_total', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '无法确认学校网站'):
                collect_all_papers(object(), 'INT305')


class SearchDomTests(unittest.TestCase):
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
        cls.browser.close(); cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def test_independent_total_parser_and_conflicting_totals(self):
        from capture_canvas import read_search_total
        for text in ('Total 5', '共 5 条', '1-4 of 5 items'):
            self.page.set_content(f'<span class="ivu-page-total">{text}</span>')
            self.assertEqual(read_search_total(self.page), 5)
        self.page.set_content('<span class="ivu-page-total">Total 5</span><span class="el-pagination__total">共 4 条</span>')
        with self.assertRaisesRegex(RuntimeError, '矛盾'): read_search_total(self.page)
        self.page.set_content('<p>INT305 2025</p>')
        self.assertIsNone(read_search_total(self.page))

    def test_iview_pagination_waits_for_new_links_then_observes_disabled(self):
        from capture_canvas import has_next_page
        self.page.set_content('''<span class="ivu-page-total">Total 5</span><div id="items">
            <a href="https://fixture.test/PaperDetail/1">INT305 first</a>
            <a href="https://fixture.test/PaperDetail/2">INT305 second</a>
            <a href="https://fixture.test/PaperDetail/3">INT305 third</a>
            <a href="https://fixture.test/PaperDetail/4">INT305 fourth</a></div>
            <li class="ivu-page-next">Next</li>
            <script>document.querySelector('.ivu-page-next').addEventListener('click', function () {
                setTimeout(() => {
                    document.querySelector('#items').innerHTML='<a href="https://fixture.test/PaperDetail/5">INT305 fifth</a>';
                    this.classList.add('ivu-page-disabled');
                }, 250);
            });</script>''')
        self.assertTrue(has_next_page(self.page))
        papers = collect_all_papers(self.page, 'INT305')
        self.assertEqual(len(papers), 5)
        self.assertFalse(has_next_page(self.page))

    def test_click_without_changed_results_is_an_error(self):
        from capture_canvas import go_to_next_page
        self.page.set_content('<a href="https://fixture.test/PaperDetail/1">INT305</a><li class="ivu-page-next">Next</li>')
        with self.assertRaisesRegex(RuntimeError, '未更新'):
            go_to_next_page(self.page, timeout_ms=250)
