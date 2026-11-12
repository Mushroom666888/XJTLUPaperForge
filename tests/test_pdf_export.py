import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

import pdf_output
from batch_capture import PaperLink, collect_all_papers, extract_one_paper
from browser_session import _find_chrome, fresh_chrome_context
from merge_png_to_pdf import merge_png_to_pdf
from pdf_quality import inspect_png_pages, verify_pdf
from login import _check_logged_in
from capture_canvas import agree_and_search


def make_pages(folder):
    for number in (1, 2):
        image = Image.new('RGB', (160, 240), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((10, 10), f'Exam page {number}', fill='black')
        draw.line((10, 30, 130, 50 * number), fill='blue', width=3)
        image.save(Path(folder) / f'pdf_page_{number:03d}.png')


class PdfQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        make_pages(self.root)
        self.pdf = self.root / 'exam.pdf'

    def tearDown(self):
        self.temp.cleanup()

    def test_lossless_pdf_has_matching_pixels_order_and_resolution(self):
        records = inspect_png_pages(self.root, 2)
        merge_png_to_pdf(self.root, self.pdf, dpi=192)
        self.assertEqual(verify_pdf(self.pdf, 2, 192, records), 2)
        self.assertTrue(pdf_output.pdf_is_complete(self.pdf, 2, 192))
        self.assertFalse(pdf_output.pdf_is_complete(self.pdf, 3, 192))
        self.assertFalse(pdf_output.pdf_is_complete(self.pdf, 2, 300))

    def test_reordered_pages_fail_pixel_verification(self):
        merge_png_to_pdf(self.root, self.pdf)
        reader = PdfReader(self.pdf)
        writer = PdfWriter()
        writer.add_page(reader.pages[1])
        writer.add_page(reader.pages[0])
        writer.add_metadata(reader.metadata)
        reordered = self.root / 'reordered.pdf'
        writer.write(reordered)
        with self.assertRaisesRegex(ValueError, '像素不一致'):
            verify_pdf(reordered, 2)

    def test_intact_image_cannot_hide_missing_shifted_or_cropped_page_content(self):
        from pypdf.generic import DecodedStreamObject, NameObject, RectangleObject, NumberObject
        merge_png_to_pdf(self.root, self.pdf)
        for damage in ('empty', 'shifted', 'cropped', 'rotated'):
            with self.subTest(damage=damage):
                writer = PdfWriter(clone_from=self.pdf)
                page = writer.pages[0]
                if damage in ('empty', 'shifted'):
                    content = DecodedStreamObject()
                    content.set_data(b'' if damage == 'empty' else b'q 60 0 0 90 600 0 cm /Im0 Do Q')
                    page[NameObject('/Contents')] = writer._add_object(content)
                elif damage == 'cropped':
                    page.cropbox = RectangleObject([0, 0, 30, 45])
                else:
                    page[NameObject('/Rotate')] = NumberObject(90)
                damaged = self.root / f'{damage}.pdf'
                writer.write(damaged)
                with self.assertRaisesRegex(ValueError, '页面绘制|页面裁切'):
                    verify_pdf(damaged, 2, 192)
                self.assertFalse(pdf_output.pdf_is_complete(damaged, 2, 192))

    def test_missing_and_blank_pages_are_rejected(self):
        (self.root / 'pdf_page_002.png').unlink()
        with self.assertRaisesRegex(ValueError, '页码不完整'):
            inspect_png_pages(self.root, 2)
        Image.new('RGB', (160, 240), 'white').save(self.root / 'pdf_page_002.png')
        with self.assertRaisesRegex(ValueError, '空白页'):
            inspect_png_pages(self.root, 2)

    def test_duplicate_pages_are_rejected(self):
        (self.root / 'pdf_page_002.png').write_bytes((self.root / 'pdf_page_001.png').read_bytes())
        with self.assertRaisesRegex(ValueError, '完全相同'):
            inspect_png_pages(self.root, 2)

    def test_merge_error_preserves_existing_file_and_removes_partial_pdf(self):
        self.pdf.write_bytes(b'previous-file')
        with patch('merge_png_to_pdf.img2pdf.convert', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                merge_png_to_pdf(self.root, self.pdf)
        self.assertEqual(self.pdf.read_bytes(), b'previous-file')
        self.assertEqual(list(self.root.glob('*.pdf')), [self.pdf])

    def test_failed_capture_is_not_published_and_temporary_pngs_are_removed(self):
        output = self.root / 'output'
        scratch = self.root / 'scratch'
        def partial_capture(viewer, folder, scale):
            make_pages(folder)
            return 1
        with patch.object(pdf_output, 'OUTPUT_ROOT', output), patch.object(pdf_output, 'WORK_ROOT', scratch), \
             patch.object(pdf_output, 'extract_canvas_pages', side_effect=partial_capture):
            with self.assertRaisesRegex(RuntimeError, '页数不完整'):
                pdf_output.save_paper_pdf(object(), 'CAN209', 'CAN209_2023-24_F', 2, 2)
        self.assertFalse(output.exists())
        self.assertEqual(list(scratch.iterdir()), [])

    def test_existing_invalid_file_is_never_overwritten(self):
        output = self.root / 'output'
        target = output / 'CAN209' / 'CAN209_2023-24_F.pdf'
        target.parent.mkdir(parents=True); target.write_bytes(b'precious existing file')
        with patch.object(pdf_output, 'OUTPUT_ROOT', output), patch.object(pdf_output, 'extract_canvas_pages') as capture:
            with self.assertRaises(FileExistsError):
                pdf_output.save_paper_pdf(object(), 'CAN209', 'CAN209_2023-24_F', 2, 2)
            capture.assert_not_called()
        self.assertEqual(target.read_bytes(), b'precious existing file')

    def test_cancelled_validation_never_publishes_and_cleans_staging(self):
        from task_events import TaskCancelled
        output = self.root / 'output'
        def capture(viewer, folder, scale):
            make_pages(folder); return 2
        with patch.object(pdf_output, 'OUTPUT_ROOT', output), patch.object(pdf_output, 'WORK_ROOT', self.root/'scratch'), \
             patch.object(pdf_output, 'extract_canvas_pages', side_effect=capture), \
             patch.object(pdf_output, 'check_cancelled', side_effect=[None, None, TaskCancelled()]):
            with self.assertRaises(TaskCancelled):
                pdf_output.save_paper_pdf(object(), 'CAN209', 'CAN209_2023-24_F', 2, 2)
        self.assertEqual(list(output.rglob('*.pdf')), [])
        self.assertEqual(list(output.rglob('.paperforge-*')), [])
        self.assertEqual(list((self.root/'scratch').iterdir()), [])


VIEWER_HTML = '''<div class="page" data-page-number="1"><canvas></canvas></div>
<div class="page" data-page-number="2"><canvas></canvas></div><script>
let current = 1, scale = 1.25;
const views = [...document.querySelectorAll('canvas')].map(canvas =>
    ({canvas, scale: 0, renderingState: 0, viewport: {width: 0, height: 0}, generation: 0}));
function render(number) {
    const view = views[number - 1];
    if (view.scale === scale && view.renderingState === 3) return;
    const token = ++view.generation;
    view.scale = scale; view.renderingState = 1;
    view.canvas.width = Math.round(160 * scale);
    view.canvas.height = Math.round(230 * scale);
    view.viewport = {width: view.canvas.width, height: view.canvas.height};
    setTimeout(() => {
        if (token !== view.generation) return;
        const ctx = view.canvas.getContext('2d');
        ctx.fillStyle = 'white'; ctx.fillRect(0, 0, view.canvas.width, view.canvas.height);
        ctx.fillStyle = 'black'; ctx.font = '24px Arial';
        ctx.fillText('CAN209 page ' + number, 20, 50);
        ctx.strokeStyle = number === 1 ? 'blue' : 'red';
        ctx.beginPath(); ctx.moveTo(20, 100); ctx.lineTo(200, 110 * number); ctx.stroke();
        view.renderingState = 3;
    }, 800);
}
window.PDFViewerApplication = {
    pdfDocument: {numPages: 2}, pagesCount: 2,
    get page() {return current;}, set page(n) {current = n; render(n);},
    pdfViewer: {
        get currentScale() {return scale;},
        set currentScale(n) {if (n !== scale) {scale = n; render(current);}},
        getPageView: index => views[index]
    }
}; render(1);
</script>'''


class BrowserExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            _find_chrome()
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))
        cls.playwright = sync_playwright().start()
        cls.browser_context = fresh_chrome_context(cls.playwright, headless=True)
        cls.context = cls.browser_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.browser_context.__exit__(None, None, None)
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.output_patch = patch.object(pdf_output, 'OUTPUT_ROOT', self.root / 'output')
        self.work_patch = patch.object(pdf_output, 'WORK_ROOT', self.root / 'scratch')
        self.output_patch.start()
        self.work_patch.start()
        self.user_tab = self.context.new_page()
        self.user_tab.set_content('Unrelated user tab')
        def respond(route):
            html = VIEWER_HTML if route.request.url.endswith('/viewer') else (
                '<main>CAN209 2023/24 Final</main><a href="/viewer" target="_blank">View Online</a>'
            )
            route.fulfill(content_type='text/html', body=html)
        self.route_handler = respond
        self.context.route('https://export.test/**', respond)
        self.paper = PaperLink('https://export.test/detail', 'CAN209', 0, 1, 'CAN209 2023/24 Final')

    def tearDown(self):
        self.context.unroute('https://export.test/**', self.route_handler)
        self.user_tab.close()
        self.output_patch.stop()
        self.work_patch.stop()
        self.temp.cleanup()

    def test_export_to_course_folder_and_reuse_verified_pdf_without_pngs(self):
        before = set(self.context.pages)
        result = extract_one_paper(self.context, self.user_tab, self.paper, 2, 'CAN209')
        self.assertTrue(result.success, result.error)
        expected = self.root / 'output' / 'CAN209' / 'CAN209_2023-24_F.pdf'
        self.assertEqual(Path(result.output_file), expected)
        self.assertEqual(verify_pdf(expected, 2, 192), 2)
        self.assertEqual(list(expected.parent.iterdir()), [expected])
        self.assertEqual(list(self.root.rglob('*.png')), [])
        self.assertEqual(set(self.context.pages), before)
        original = expected.read_bytes()
        with patch.object(pdf_output, 'extract_canvas_pages', side_effect=AssertionError('should reuse PDF')):
            again = extract_one_paper(self.context, self.user_tab, self.paper, 2, 'CAN209')
        self.assertTrue(again.success, again.error)
        self.assertEqual(expected.read_bytes(), original)

    def test_pdf_failure_is_reported_and_only_owned_tabs_are_closed(self):
        before = set(self.context.pages)
        with patch.object(pdf_output, 'merge_png_to_pdf', side_effect=OSError('simulated disk failure')):
            result = extract_one_paper(self.context, self.user_tab, self.paper, 2, 'CAN209')
        self.assertFalse(result.success)
        self.assertIn('simulated disk failure', result.error)
        self.assertEqual(list(self.root.rglob('*.png')), [])
        self.assertEqual(list(self.root.rglob('*.pdf')), [])
        self.assertEqual(set(self.context.pages), before)

    def test_two_distinct_catalog_entries_cannot_reuse_one_archive_name(self):
        paper_names = {}
        first = extract_one_paper(self.context, self.user_tab, self.paper, 2, 'CAN209', paper_names)
        self.assertTrue(first.success, first.error)
        original = Path(first.output_file).read_bytes()
        other = PaperLink('https://export.test/another-detail', 'CAN209', 1, 1, 'CAN209 2023/24 Final')
        second = extract_one_paper(self.context, self.user_tab, other, 2, 'CAN209', paper_names)
        self.assertFalse(second.success)
        self.assertIn('名称冲突', second.error)
        self.assertEqual(Path(first.output_file).read_bytes(), original)
        self.assertEqual(list((self.root/'output').rglob('*.pdf')), [Path(first.output_file)])

    def test_custom_destination_on_project_volume_has_verified_300_dpi_pdf(self):
        # The current Windows checkout is on D:, while capture scratch uses C:.
        # CI uses its own available volume; neither case touches actual school papers.
        from settings import PROJECT_ROOT
        from output_preferences import OutputPreferences
        work = PROJECT_ROOT / 'work'; work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='export-integration-', dir=work) as destination:
            preferences = OutputPreferences(self.root/'settings.json', self.root/'default')
            selected = preferences.save(destination)
            with patch.object(pdf_output, 'OUTPUT_ROOT', selected):
                result = extract_one_paper(self.context, self.user_tab, self.paper, 3.125, 'CAN209')
            self.assertTrue(result.success, result.error)
            expected = selected/'CAN209'/'CAN209_2023-24_F.pdf'
            self.assertEqual(Path(result.output_file), expected)
            self.assertEqual(verify_pdf(expected, 2, 300), 2)
            self.assertEqual(list(selected.rglob('*.png')), [])
            self.assertEqual(list(selected.rglob('.paperforge-*')), [])

    def test_embargo_is_reported_without_trying_to_open_viewer(self):
        def blocked(route):
            route.fulfill(content_type='text/html', body='Access to this file is embargoed until : 2025/12/17')
        self.context.route('https://blocked.test/**', blocked)
        try:
            paper = PaperLink('https://blocked.test/detail', 'CAN209', 0, 1, 'CAN209 2024/25 Final')
            before = set(self.context.pages)
            result = extract_one_paper(self.context, self.user_tab, paper, 2, 'CAN209')
            self.assertFalse(result.success)
            self.assertIn('标记为封存', result.error)
            self.assertEqual(set(self.context.pages), before)
        finally:
            self.context.unroute('https://blocked.test/**', blocked)

    def test_public_homepage_is_not_mistaken_for_logged_in_session(self):
        def respond(route):
            route.fulfill(content_type='text/html', body='<div>Past Exam Papers</div><button>Login</button>')
        self.context.route('https://etd.xjtlu.edu.cn/**', respond)
        try:
            self.assertFalse(_check_logged_in(self.user_tab))
        finally:
            self.context.unroute('https://etd.xjtlu.edu.cn/**', respond)

    def test_search_waits_for_initialization_and_requested_course_response(self):
        html = '''<button id="agree">Agree</button><script>
        agree.onclick = () => {
            history.replaceState(null, '', '#/SearchDetail/EXAMXJTLU');
            document.body.innerHTML = '<input type="text" id="query"><button class="search-btn" id="submitSearch">Search</button><table><tbody id="rows"></tbody></table>';
            async function search(value) {
                const response = await fetch('/api/v1/Search/Search', {
                    method: 'POST', body: JSON.stringify({value})
                });
                const data = await response.json(); rows.innerHTML = data.html;
            }
            query.onkeydown = event => {if (event.key === 'Enter') search(query.value);};
            submitSearch.onclick = () => search(query.value);
            fetch('/api/v1/Search/EXAMXJTLU').then(() => {query.value = ''; search('');});
        };
        </script>'''
        def respond(route):
            if '/api/v1/Search/Search' in route.request.url:
                course = 'CAN209' if 'CAN209' in (route.request.post_data or '') else 'EEE201'
                body = json.dumps({'html': f'<tr><td><a href="#/PaperDetail/1">{course}</a></td></tr>'})
                route.fulfill(content_type='application/json', body=body)
            elif '/api/' in route.request.url:
                route.fulfill(content_type='application/json', body='{}')
            else:
                route.fulfill(content_type='text/html', body=html)
        self.context.route('https://search.test/**', respond)
        try:
            self.user_tab.goto('https://search.test/index.html#/Policy/EXAMXJTLU')
            agree_and_search(self.user_tab, 'CAN209')
            self.assertEqual(self.user_tab.locator('input').input_value(), 'CAN209')
            self.assertEqual(self.user_tab.locator("a[href*='PaperDetail']").all_text_contents(), ['CAN209'])
        finally:
            self.context.unroute('https://search.test/**', respond)


class PaginationTests(unittest.TestCase):
    def test_only_exact_course_results_are_returned(self):
        items = [
            {'href': f'https://example.test/{i}', 'text': 'Course title', 'site_text': code, 'index': i}
            for i, code in enumerate(('EEE201', 'CAN209TC', 'CAN209'))
        ]
        with patch('batch_capture.collect_search_results', return_value=items), \
             patch('batch_capture.has_next_page', return_value=False):
            papers = collect_all_papers(object(), 'CAN209')
        self.assertEqual([paper.site_text for paper in papers], ['CAN209'])

    def test_repeated_search_page_stops_instead_of_looping_forever(self):
        item = {'href': 'https://example.test/1', 'text': 'CAN209', 'index': 0}
        with patch('batch_capture.collect_search_results', return_value=[item]), \
             patch('batch_capture.has_next_page', return_value=True), \
             patch('batch_capture.go_to_next_page', return_value=True):
            with self.assertRaisesRegex(RuntimeError, '没有新的搜索结果'):
                collect_all_papers(object())

    def test_failed_next_page_click_stops_with_error(self):
        item = {'href': 'https://example.test/1', 'text': 'CAN209', 'index': 0}
        with patch('batch_capture.collect_search_results', return_value=[item]), \
             patch('batch_capture.has_next_page', return_value=True), \
             patch('batch_capture.go_to_next_page', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '无法进入下一页'):
                collect_all_papers(object())


if __name__ == '__main__':
    unittest.main()
