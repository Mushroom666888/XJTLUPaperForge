"""Bundled acceptance worker: generated pages, never an authenticated school site."""
import argparse
from playwright.sync_api import sync_playwright
from browser_session import fresh_chrome_context
from batch_capture import PaperLink,extract_one_paper
from synthetic_pages import VIEWER_HTML
from task_events import emit
from result_audit import catalog_items, verified_fields, record_id


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('course',choices=['CAN209'])
    parser.add_argument('--scale',type=float,default=2)
    args=parser.parse_args()
    with sync_playwright() as p, fresh_chrome_context(p,headless=True) as context:
        def route(request):
            if not request.request.url.startswith('https://export.test/'):
                request.abort();return
            html=VIEWER_HTML if request.request.url.endswith('/viewer') else '<main>CAN209 2023/24 Final</main><a href="/viewer" target="_blank">View Online</a>'
            request.fulfill(content_type='text/html',body=html)
        context.route('**/*',route)
        page=context.new_page()
        emit('phase',phase='searching');emit('inventory',total=1)
        paper=PaperLink('https://export.test/detail','CAN209',0,1,'CAN209 2023/24 Final')
        emit('catalog',total=1,items=catalog_items([paper]))
        result=extract_one_paper(context,page,paper,args.scale,args.course)
        if result.success:
            emit('verified',**verified_fields(result))
            emit('summary',total=1,succeeded=[record_id(paper.href)],failed=[])
            return 0
        print('✗ '+str(result.error));return 1


if __name__=='__main__':raise SystemExit(main())
