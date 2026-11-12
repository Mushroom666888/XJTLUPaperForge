"""Unattended package acceptance: actual UI, child workers, OCR and shutdown."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch


def main():
    # Set a fresh external runtime before importing modules that resolve settings.
    with tempfile.TemporaryDirectory(prefix='paperforge-package-check-') as temporary:
        root=Path(temporary).resolve()
        os.environ['XJTLUPAPERFORGE_DATA']=str(root/'runtime')
        os.environ['XJTLUPAPERFORGE_OUTPUT']=str(root/'default')
        from app import Jobs,Server
        from browser_config import BrowserPreferences,detect_browsers
        from output_preferences import OutputPreferences
        from pdf_quality import verify_pdf
        from playwright.sync_api import sync_playwright,expect
        from PIL import Image,ImageDraw,ImageFont
        from capture_canvas import _ocr_image_text
        from runtime_paths import FROZEN,RESOURCE_ROOT
        available=detect_browsers()
        if 'chrome' not in available:raise RuntimeError('Package acceptance requires actual Chrome.')
        # Pillow's scalable bundled default font avoids a developer/system font path.
        image=Image.new('RGB',(1200,200),'white')
        ImageDraw.Draw(image).text((30,40),'CAN209 2024/25 FINAL EXAM',font=ImageFont.load_default(size=48),fill='black')
        data=io.BytesIO();image.save(data,format='PNG')
        with patch('requests.get',side_effect=AssertionError('OCR must use bundled models')):
            text=_ocr_image_text(data.getvalue())
        if 'CAN209' not in text or 'FINAL' not in text:raise AssertionError(f'OCR failed: {text}')
        checked=[]
        for key in ('chrome','edge'):
            if key not in available:continue
            selected=root/key/'chosen papers 中文';selected.mkdir(parents=True)
            prefs=OutputPreferences(root/key/'prefs.json',selected)
            browsers=BrowserPreferences(root/key,lambda:{key:available[key]})
            if key!='chrome':browsers.select(key)
            jobs=Jobs(preferences=prefs,browsers=browsers)
            def runner(script,args,consume):
                if script=='login.py':return 0  # No school connection in package acceptance.
                return jobs.run_script('synthetic_worker.py',args,consume)
            jobs.runner=runner
            server=Server(jobs=jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=available[key],headless=True)
                    page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    page.locator('#courses').fill('CAN209');page.locator('input[value="3.125"]').check()
                    page.locator('#submit').click()
                    try:
                        expect(page.locator('#phase')).to_have_text('归档完成',timeout=90000)
                    except AssertionError as exc:
                        from settings import DATA_ROOT
                        logs='\n'.join(path.read_text(encoding='utf-8') for path in (DATA_ROOT/'logs').glob('*.log'))
                        raise AssertionError(f'{key}: {exc}\nState: {jobs.snapshot()}\nSynthetic worker logs:\n{logs}') from exc
                    pdf=selected/'CAN209/CAN209_2023-24_F.pdf'
                    assert verify_pdf(pdf,2,300)==2
                    assert not errors,errors
                    page.locator('#quit').click()
                    expect(page.locator('#phase')).to_have_text('已退出')
                    browser.close()
                checked.append(key)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
        if FROZEN:
            import sys
            foreign=[str(module.__file__) for module in sys.modules.values()
                if getattr(module,'__file__',None) and Path(module.__file__).is_absolute()
                and not Path(module.__file__).resolve().is_relative_to(RESOURCE_ROOT)]
            assert not foreign,foreign
        print('PACKAGE_CHECK '+json.dumps({'frozen':FROZEN,'browsers':checked,'ocr':text,'export':'300 DPI / 2 pages','shutdown':True},ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
