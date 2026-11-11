"""Capture labelled synthetic UI states for review; never contacts the school."""
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Jobs, Server
from browser_session import _find_chrome
from output_preferences import OutputPreferences
from playwright.sync_api import sync_playwright, expect


def main():
    review = ROOT / '.impeccable/review'; review.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        prefs = OutputPreferences(Path(temporary)/'preferences.json', ROOT.parent/'XJTLUPaperForge-Output')
        jobs = Jobs(lambda *args: 0, prefs)
        server = Server(jobs=jobs)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=_find_chrome(), headless=True)
                page = browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#output-path')).to_have_text(str(prefs.path))
                page.evaluate('Promise.all([...document.images].map(i => i.decode().catch(() => {})))')
                page.screenshot(path=str(review/'desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(review/'mobile.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000})
                # Explicitly label all demonstration results, even in screenshots.
                rows = [dict(course='ABC123',status='working',expected=2,papers=[],errors=[],message='合成验收数据')]
                jobs.update(active=True,phase='downloading',kind='export',current_course='ABC123',
                            current_file='ABC123_2025_F.pdf',pages_done=3,pages_total=8,
                            results=rows,message='合成验收场景 · 不代表学校下载结果',job_output_dir=str(prefs.path))
                for phase, name in [('waiting','waiting'),('downloading','processing'),('validating','validating'),('review','partial'),('cancelled','cancelled'),('done','success')]:
                    if phase == 'review':
                        rows[0].update(status='partial', papers=[{'name':'ABC123_2025_F.pdf','pages':8}])
                    if phase == 'cancelled': rows[0].update(status='cancelled')
                    if phase == 'done': rows[0].update(status='complete',expected=1)
                    jobs.update(phase=phase,active=phase in ('waiting','downloading','validating'),results=rows)
                    expect(page.locator('body')).to_have_attribute('data-phase',phase)
                    page.evaluate('Promise.all([...document.images].map(i => i.decode().catch(() => {})))')
                    page.screenshot(path=str(review/(name+'.png')),full_page=True)
                page.emulate_media(reduced_motion='reduce')
                rows[0].update(status='working',expected=2,papers=[])
                jobs.update(phase='downloading',active=True,results=rows)
                expect(page.locator('body')).to_have_attribute('data-phase','downloading')
                page.screenshot(path=str(review/'reduced-motion.png'),full_page=True)
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    main()
