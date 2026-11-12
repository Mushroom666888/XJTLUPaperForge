"""Regression contracts for the seven 2026-11-12 adversarial findings."""
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageStat
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
import browser_session
import capture_canvas
import file_publication
import pdf_output
from batch_capture import PaperLink, extract_one_paper
from merge_png_to_pdf import merge_png_to_pdf
from output_preferences import validate_directory, OutputPreferences
from pdf_quality import verify_pdf
from settings import PROJECT_ROOT
import test_pdf_export as export_tests
from test_pdf_export import make_pages, VIEWER_HTML


class IdentityTests(unittest.TestCase):
    def test_complete_catalog_still_rejects_wrong_or_unknown_cover(self):
        for code in ('EEE211', 'UNKNOWN'):
            with self.subTest(code=code), patch('capture_canvas.parse_exam_metadata', return_value=(code, '2024-25', 'F')):
                with self.assertRaisesRegex(ValueError, '课程编号'):
                    capture_canvas.resolve_paper_metadata('CAN209', 'CAN209 2024/25 Final', '', object(), 'CAN209')

    def test_renamed_legacy_pdf_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); images = root/'images'; images.mkdir(); make_pages(images)
            output = root/'output'; pdf = output/'CAN209/CAN209_2024-25_F.pdf'; pdf.parent.mkdir(parents=True)
            merge_png_to_pdf(images, pdf)
            before = pdf.read_bytes()
            with patch.object(pdf_output, 'OUTPUT_ROOT', output), patch.object(pdf_output, 'extract_canvas_pages') as capture:
                with self.assertRaises(FileExistsError):
                    pdf_output.save_paper_pdf(object(), 'CAN209', pdf.stem, 2, 2,
                                              source_identity={'course':'CAN209','record_sha256':'new'})
                capture.assert_not_called()
            self.assertEqual(pdf.read_bytes(), before)


class BrowserIdentityTests(export_tests.BrowserExportTests):
    # Keep the established browser setup/cleanup, but do not inherit its test cases.
    def test_wrong_course_source_is_rejected_despite_matching_catalog(self):
        def wrong(route):
            route.fulfill(content_type='text/html', body=VIEWER_HTML.replace('CAN209','EEE211'))
        self.context.route('https://export.test/viewer', wrong)
        try:
            result=extract_one_paper(self.context,self.user_tab,self.paper,2,'CAN209')
            self.assertFalse(result.success); self.assertIn('课程编号',result.error)
            self.assertEqual(list(self.root.rglob('*.pdf')),[])
        finally: self.context.unroute('https://export.test/viewer',wrong)

    def test_cross_run_record_and_source_revision_cannot_reuse_old_content(self):
        first=extract_one_paper(self.context,self.user_tab,self.paper,2,'CAN209',{})
        self.assertTrue(first.success,first.error)
        before=Path(first.output_file).read_bytes()
        other=PaperLink('https://export.test/another-detail','CAN209',0,1,'CAN209 2023/24 Final')
        second=extract_one_paper(self.context,self.user_tab,other,2,'CAN209',{})
        self.assertFalse(second.success)
        def changed(route):
            route.fulfill(content_type='text/html',body=VIEWER_HTML.replace('source v1','source v2').replace('page ','revised page '))
        self.context.route('https://export.test/viewer',changed)
        try:
            revised=extract_one_paper(self.context,self.user_tab,self.paper,2,'CAN209',{})
            self.assertFalse(revised.success)
            self.assertEqual(Path(first.output_file).read_bytes(),before)
        finally: self.context.unroute('https://export.test/viewer',changed)

    def test_without_source_bytes_reuse_recaptures_all_pages(self):
        def unavailable(route):
            route.fulfill(content_type='text/html',body=VIEWER_HTML.replace("getData: async () => new TextEncoder().encode('CAN209 synthetic source v1'),",''))
        self.context.route('https://export.test/viewer',unavailable)
        try:
            first=extract_one_paper(self.context,self.user_tab,self.paper,2,'CAN209',{})
            self.assertTrue(first.success,first.error)
            with patch.object(pdf_output,'extract_canvas_pages',wraps=capture_canvas.extract_canvas_pages) as capture:
                again=extract_one_paper(self.context,self.user_tab,self.paper,2,'CAN209',{})
                self.assertTrue(again.success,again.error);capture.assert_called_once()
        finally: self.context.unroute('https://export.test/viewer',unavailable)

    def test_dpr_does_not_change_source_page_points(self):
        page=self.context.new_page()
        try:
            for dpr in (1,1.25,2):
                with self.subTest(dpr=dpr):
                    page.goto('about:blank')  # Fresh JS realm; set_content cannot redeclare top-level const.
                    html=VIEWER_HTML.replace('Math.round(160 * scale)',f'Math.round(160 * scale * {dpr})').replace('Math.round(230 * scale)',f'Math.round(230 * scale * {dpr})')
                    page.set_content(html)
                    folder=self.root/f'dpr-{dpr}';folder.mkdir()
                    sizes=[]
                    capture_canvas.extract_canvas_pages(page,folder,2,page_sizes=sizes)
                    self.assertEqual(sizes,[[120,172.5],[120,172.5]])
                    pdf=folder/'exam.pdf';merge_png_to_pdf(folder,pdf,page_sizes=sizes)
                    self.assertEqual(verify_pdf(pdf,2,192,page_sizes=sizes),2)
                    self.assertEqual(float(PdfReader(pdf).pages[0].mediabox.width),120)
        finally: page.close()


# unittest discovers inherited methods; these are already exercised in their original class.
for _name in dir(export_tests.BrowserExportTests):
    if _name.startswith('test_'):
        setattr(BrowserIdentityTests, _name, None)


class VisibilityTests(unittest.TestCase):
    def test_hidden_optional_content_is_rejected_with_or_without_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);make_pages(root);pdf=root/'source.pdf';merge_png_to_pdf(root,pdf)
            for catalog in (True,False):
                writer=PdfWriter(clone_from=pdf)
                group=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/OCG'),NameObject('/Name'):TextStringObject('hidden')}))
                if catalog:
                    writer._root_object[NameObject('/OCProperties')]=DictionaryObject({NameObject('/OCGs'):ArrayObject([group]),NameObject('/D'):DictionaryObject({NameObject('/BaseState'):NameObject('/OFF')})})
                for image in writer.pages[0]['/Resources']['/XObject'].values():
                    image.get_object()[NameObject('/OC')]=group
                hidden=root/f'hidden-{catalog}.pdf';writer.write(hidden)
                with self.assertRaisesRegex(ValueError,'可选图层'):verify_pdf(hidden,2,192)
                self.assertFalse(pdf_output.pdf_is_complete(hidden,2,192))
                if catalog and (renderer:=shutil.which('pdftoppm')):
                    subprocess.run([renderer,'-f','1','-singlefile','-scale-to','400','-png',str(hidden),str(root/'render')],check=True,capture_output=True)
                    with Image.open(root/'render.png') as image:
                        self.assertEqual(ImageStat.Stat(image.convert('RGB')).mean,[255,255,255])


class PublicationAndPathsTests(unittest.TestCase):
    def test_native_publication_never_overwrites_and_does_not_need_hardlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch('file_publication.os.link',side_effect=OSError(errno.ENOTSUP,'no hardlinks')):
                file_publication.check_publication_directory(root)
                source,target=root/'new',root/'old'
                source.write_bytes(b'new');target.write_bytes(b'old')
                with self.assertRaises(FileExistsError):file_publication.publish_no_replace(source,target)
                self.assertEqual(target.read_bytes(),b'old');self.assertEqual(source.read_bytes(),b'new')
                target.unlink();file_publication.publish_no_replace(source,target)
                self.assertEqual(target.read_bytes(),b'new')

    def test_source_and_saved_source_paths_are_rejected_before_writing(self):
        for target in (PROJECT_ROOT,PROJECT_ROOT/'should-not-be-created'):
            with self.assertRaisesRegex(ValueError,'程序目录之外'):validate_directory(target,create=True)
        self.assertFalse((PROJECT_ROOT/'should-not-be-created').exists())
        with tempfile.TemporaryDirectory() as temporary:
            import json
            root=Path(temporary);preferences=root/'prefs.json'
            preferences.write_text(json.dumps({'output_dir':str(PROJECT_ROOT)}))
            prefs=OutputPreferences(preferences,root/'default')
            self.assertEqual(prefs.path,root/'default');self.assertTrue(prefs.warning)
            for variable in ('XJTLUPAPERFORGE_DATA','XJTLUPAPERFORGE_OUTPUT'):
                env=dict(os.environ,**{variable:str(PROJECT_ROOT)})
                result=subprocess.run([sys.executable,'-c','import settings'],cwd=PROJECT_ROOT,env=env,capture_output=True)
                self.assertNotEqual(result.returncode,0)

    def test_startup_timeout_cleans_owned_process_and_keeps_unrelated_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            args=[sys.executable,'-c','import time; time.sleep(60)']
            flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            foreign=subprocess.Popen(args,creationflags=flags,start_new_session=os.name!='nt')
            owned=subprocess.Popen(args,creationflags=flags,start_new_session=os.name!='nt')
            try:
                with patch('browser_session.subprocess.Popen',return_value=owned), patch('browser_session._wait_for_debug_port',side_effect=RuntimeError('CDP timeout')):
                    with self.assertRaisesRegex(RuntimeError,'CDP timeout'):
                        browser_session.launch_detached_chrome(temporary,headless=True)
                self.assertIsNotNone(owned.poll());self.assertIsNone(foreign.poll())
            finally:
                for child in (owned,foreign):
                    if child.poll() is None:child.terminate()
                    child.wait(timeout=5)

    def test_failed_session_write_cleans_up_after_launcher_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile=str(Path(temporary).resolve());port=58991
            started=time.time()
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)',f'--remote-debugging-port={port}',f'--user-data-dir={profile}'],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
            launcher=Mock();launcher.poll.return_value=0
            try:
                browser_session._cleanup_failed_launch(launcher,port,profile,started)
                child.wait(timeout=5)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)


if __name__=='__main__':unittest.main()
