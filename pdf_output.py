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
    return OUTPUT_ROOT / code / f"{paper_name}.pdf"


def pdf_is_complete(path, expected_pages, min_dpi=0):
    """Only reuse readable, unencrypted PDFs with the expected number of pages."""
    if expected_pages <= 0:
        return False
    try:
        verify_pdf(path, expected_pages, min_dpi=min_dpi)
        return True
    except Exception:
        return False


def save_paper_pdf(viewer, course_code, paper_name, scale, expected_pages):
    """Publish only a complete PDF; failures leave any old PDF unchanged."""
    validate_scale(scale)
    output_file = paper_pdf_path(course_code, paper_name)
    dpi = 96 * scale
    if pdf_is_complete(output_file, expected_pages, min_dpi=dpi):
        print(f"  ⏭ 已有完整 PDF（{expected_pages} 页）: {output_file.name}")
        return str(output_file)

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paper-", dir=WORK_ROOT) as scratch:
        count = extract_canvas_pages(viewer, scratch, scale)
        if count != expected_pages:
            raise RuntimeError(f"页数不完整：{count}/{expected_pages}，未生成最终 PDF。")
        records = inspect_png_pages(scratch, expected_pages)
        pending = Path(scratch) / "complete.pdf"
        merge_png_to_pdf(scratch, str(pending), dpi=dpi)
        verify_pdf(pending, expected_pages, min_dpi=dpi, source_records=records)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        os.replace(pending, output_file)

    print(f"  PDF 已保存: {output_file}")
    return str(output_file)
