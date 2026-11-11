import base64
import io
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import sync_playwright

from browser_session import _find_chrome, fresh_chrome_context
from capture_canvas import _capture_rendered_page, extract_canvas_pages, detect_total_pages


class CanvasRenderingTests(unittest.TestCase):
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
        self.page = self.context.new_page()
        self.page.set_content('<div class="page" data-page-number="1"><canvas width="20" height="30"></canvas></div>')
        self.page.evaluate('''() => {
            const canvas = document.querySelector('canvas');
            const view = {canvas, scale: 2, renderingState: 1};
            window.testView = view;
            window.PDFViewerApplication = {
                page: 1, pdfViewer: {currentScale: 2, getPageView: () => view}
            };
        }''')

    def tearDown(self):
        self.page.close()

    def test_waits_for_slow_render_before_exporting_canvas(self):
        self.page.evaluate('''() => setTimeout(() => {
            const view = window.testView;
            const ctx = view.canvas.getContext('2d');
            ctx.fillStyle = 'red';
            ctx.fillRect(0, 0, 20, 30);
            view.renderingState = 3;
        }, 900)''')
        result = _capture_rendered_page(self.page, 1, 2, timeout_ms=3000)
        self.assertTrue(result['ok'])
        image_data = base64.b64decode(result['dataURL'].split(',', 1)[1])
        with Image.open(io.BytesIO(image_data)) as image:
            self.assertEqual(image.convert('RGB').getpixel((10, 10)), (255, 0, 0))

    def test_rejects_finished_canvas_at_old_scale(self):
        self.page.evaluate('() => { testView.renderingState = 3; testView.scale = 1; }')
        result = _capture_rendered_page(self.page, 1, 2, timeout_ms=200)
        self.assertFalse(result['ok'])

    def test_reports_render_error_instead_of_exporting_blank_canvas(self):
        self.page.evaluate('() => { testView.renderingState = 3; testView._renderError = "Network failure"; }')
        result = _capture_rendered_page(self.page, 1, 2, timeout_ms=200)
        self.assertFalse(result['ok'])
        self.assertIn('Network failure', result['reason'])

    def test_rejects_canvas_smaller_than_requested_viewport(self):
        self.page.evaluate('() => { testView.renderingState = 3; testView.viewport = {width: 40, height: 60}; }')
        result = _capture_rendered_page(self.page, 1, 2, timeout_ms=200)
        self.assertFalse(result['ok'])
        self.assertIn('分辨率', result['reason'])

    def test_missing_page_count_is_not_replaced_with_guessed_count(self):
        with self.assertRaisesRegex(RuntimeError, '无法确认 PDF 总页数'):
            detect_total_pages(self.page)


class IncompleteCaptureTests(unittest.TestCase):
    def test_partial_capture_raises_instead_of_reporting_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('capture_canvas.detect_total_pages', return_value=1), \
                 patch('capture_canvas.preload_pages'), \
                 patch('capture_canvas._capture_rendered_page', return_value={'ok': False, 'reason': 'timeout'}):
                with self.assertRaisesRegex(RuntimeError, '0/1'):
                    extract_canvas_pages(object(), directory)


if __name__ == '__main__':
    unittest.main()
