"""Local E2E worker: real browser/PDF pipeline, synthetic school page only."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from browser_session import fresh_chrome_context
from batch_capture import extract_one_paper, PaperLink
from task_events import emit
from test_pdf_export import VIEWER_HTML


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('course')
    parser.add_argument('--scale',type=float,default=2)
    args = parser.parse_args()
    if args.course != 'CAN209':
        raise ValueError('This synthetic fixture only contains CAN209.')
    with sync_playwright() as p, fresh_chrome_context(p,headless=True) as context:
        def respond(route):
            if route.request.url.endswith('/viewer'):
                html = VIEWER_HTML
            else:
                html = '<main>CAN209 2023/24 Final</main><a href="/viewer" target="_blank">View Online</a>'
            route.fulfill(content_type='text/html',body=html)
        context.route('https://export.test/**',respond)
        page = context.new_page()
        emit('phase',phase='searching');emit('catalog',total=1)
        paper = PaperLink('https://export.test/detail','CAN209',0,1,'CAN209 2023/24 Final')
        result = extract_one_paper(context,page,paper,args.scale,args.course)
        if result.success:
            emit('verified',name=result.paper_name+'.pdf',pages=result.page_count)
            return 0
        print('✗ '+str(result.error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
