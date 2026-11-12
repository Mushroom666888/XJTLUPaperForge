"""Export verified PDFs into one folder per course, using temporary PNGs only."""

import math
import os
from pathlib import Path
import re
import tempfile

from capture_canvas import extract_canvas_pages
from merge_png_to_pdf import merge_png_to_pdf
from pdf_quality import inspect_png_pages, verify_pdf
from settings import OUTPUT_ROOT, WORK_ROOT
from output_preferences import course_directory
from task_events import check_cancelled, emit, TaskCancelled
from file_publication import publish_no_replace, check_publication_directory


def normalize_course_code(course_code):
    code = course_code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}\d{3}[A-Z]{0,2}", code):
        raise ValueError("课程代码格式无效，例如 CAN209 或 MTH102TC。")
    return code


def validate_scale(scale):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("缩放倍数必须是大于 0 的有限数值。")


def paper_pdf_path(course_code, paper_name):
    code = normalize_course_code(course_code)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", paper_name):
        raise ValueError("试卷文件名包含无效字符。")
    return course_directory(OUTPUT_ROOT, code) / f"{paper_name}.pdf"


def pdf_is_complete(path, expected_pages, min_dpi=0, *, source_identity=None):
    """Only reuse readable, unencrypted PDFs with the expected number of pages."""
    if expected_pages <= 0:
        return False
    try:
        verify_pdf(path, expected_pages, min_dpi=min_dpi, source_identity=source_identity)
        return True
    except TaskCancelled:
        raise
    except Exception:
        return False


def save_paper_pdf(viewer, course_code, paper_name, scale, expected_pages, *, source_identity=None):
    """Publish only a complete PDF; failures leave any old PDF unchanged."""
    validate_scale(scale)
    check_cancelled()
    output_file = paper_pdf_path(course_code, paper_name)
    dpi = 96 * scale
    existing = output_file.exists()
    reusable = bool(source_identity) and pdf_is_complete(output_file, expected_pages, min_dpi=dpi,
                                                         source_identity=source_identity)
    if reusable and source_identity.get('content_sha256'):
        print(f"  ⏭ 已有完整 PDF（{expected_pages} 页）: {output_file.name}")
        return str(output_file)
    if existing and not reusable:
        raise FileExistsError('已有文件的来源、页数或清晰度不满足本次要求；请更换保存位置或移走旧文件。')

    check_publication_directory(output_file.parent)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paper-", dir=WORK_ROOT) as scratch:
        page_sizes = []
        count = extract_canvas_pages(viewer, scratch, scale, page_sizes=page_sizes)
        if count != expected_pages:
            raise RuntimeError(f"页数不完整：{count}/{expected_pages}，未生成最终 PDF。")
        records = inspect_png_pages(scratch, expected_pages)
        if len(page_sizes) != expected_pages:
            raise ValueError('源页面纸张尺寸记录不完整，未发布文件。')
        check_cancelled()
        emit('phase', phase='validating')
        if existing:
            try:
                verify_pdf(output_file, expected_pages, min_dpi=dpi, source_records=records,
                           source_identity=source_identity, page_sizes=page_sizes)
            except TaskCancelled:
                raise
            except Exception as exc:
                raise FileExistsError('已有文件与当前试卷内容不一致，已保留原文件。') from exc
            return str(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        # Stage on the destination volume: C: capture storage may export to D: or USB.
        with tempfile.TemporaryDirectory(prefix='.paperforge-', dir=output_file.parent) as staging:
            pending = Path(staging) / 'complete.pdf'
            merge_png_to_pdf(scratch, str(pending), dpi=dpi, page_sizes=page_sizes,
                             source_identity=source_identity)
            verify_pdf(pending, expected_pages, min_dpi=dpi, source_records=records,
                       source_identity=source_identity, page_sizes=page_sizes)
            check_cancelled()
            paper_pdf_path(course_code, paper_name)  # Recheck junction containment before publication.
            publish_no_replace(pending, output_file)

    print(f"  PDF 已保存: {output_file}")
    return str(output_file)
