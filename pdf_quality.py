"""Verify page pixels, page count and resolution for image-based exam PDFs."""

import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader
from task_events import check_cancelled

FORMAT_TAG = "exam-drm-bypass-lossless-v1"


def _verify_page_drawing(page, number):
    """Check the full-page image placement produced by our lossless exporter.

    Image hashes alone cannot detect an empty content stream or clipped image.
    This validator intentionally accepts the product's generated format only.
    """
    box = [float(value) for value in page.mediabox]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    if (not all(math.isfinite(value) for value in box) or width <= 0 or height <= 0 or
            box[:2] != [0, 0] or list(page.cropbox) != list(page.mediabox) or
            page.rotation % 360 or float(page.get('/UserUnit', 1)) != 1 or page.get('/Annots')):
        raise ValueError(f"PDF 第 {number} 页页面裁切、旋转或尺寸异常。")
    content = page.get_contents()
    operations = content.operations if content is not None else []
    if [operator for _, operator in operations] != [b'q', b'cm', b'Do', b'Q']:
        raise ValueError(f"PDF 第 {number} 页页面绘制指令不完整。")
    matrix, image_name = operations[1][0], operations[2][0]
    expected = [width, 0, 0, height, 0, 0]
    resources = page.get('/Resources', {}).get('/XObject', {})
    if (len(matrix) != 6 or any(not math.isclose(float(value), target, abs_tol=.001)
                               for value, target in zip(matrix, expected)) or
            len(image_name) != 1 or image_name[0] not in resources or
            resources[image_name[0]].get('/Subtype') != '/Image' or
            operations[0][0] or operations[3][0]):
        raise ValueError(f"PDF 第 {number} 页页面绘制未完整覆盖纸张。")


def page_fingerprint(image, reject_blank=False):
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    rgb = Image.alpha_composite(background, rgba).convert("RGB")
    if reject_blank and max(ImageStat.Stat(rgb).stddev) < 0.5:
        raise ValueError("疑似空白页或纯色页，请核对原件后重试。")
    return {"width": rgb.width, "height": rgb.height,
            "sha256": hashlib.sha256(rgb.tobytes()).hexdigest()}


def inspect_png_pages(folder, expected_pages):
    files = sorted(Path(folder).glob("pdf_page_*.png"))
    expected = [f"pdf_page_{i:03d}.png" for i in range(1, expected_pages + 1)]
    if [path.name for path in files] != expected:
        raise ValueError("分页图片数量或页码不完整。")
    records = []
    seen = set()
    for number, path in enumerate(files, 1):
        check_cancelled()
        with Image.open(path) as image:
            try:
                record = page_fingerprint(image, reject_blank=True)
            except ValueError as exc:
                raise ValueError(f"第 {number} 页: {exc}") from exc
        if record["sha256"] in seen:
            raise ValueError(f"第 {number} 页与前页完全相同，请核对原件，未输出整套 PDF。")
        seen.add(record["sha256"])
        records.append(record)
    return records


def verify_pdf(path, expected_pages, min_dpi=0, source_records=None, reject_blank=True):
    """Raise on corruption, missing pages, low resolution or changed image pixels."""
    with open(path, "rb") as stream:
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted or len(reader.pages) != expected_pages or expected_pages < 1:
            raise ValueError("PDF 页数不符或文件无法读取。")
        manifest = json.loads((reader.metadata or {}).get("/Subject", "{}"))
        if manifest.get("format") != FORMAT_TAG:
            raise ValueError("PDF 缺少无损导出校验记录，需要重新生成。")
        records = manifest.get("pages", [])
        if len(records) != expected_pages or (source_records is not None and records != source_records):
            raise ValueError("PDF 校验记录与原始分页图片不一致。")
        seen = set()
        for number, (page, expected) in enumerate(zip(reader.pages, records), 1):
            check_cancelled()
            _verify_page_drawing(page, number)
            if len(page.images) != 1:
                raise ValueError(f"PDF 第 {number} 页缺少完整页面图像。")
            image = page.images[0].image
            actual = page_fingerprint(image, reject_blank=reject_blank)
            if actual != expected:
                raise ValueError(f"PDF 第 {number} 页与原始图像像素不一致。")
            if reject_blank and actual["sha256"] in seen:
                raise ValueError(f"PDF 第 {number} 页出现完全重复的页面。")
            seen.add(actual["sha256"])
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            if width <= 0 or height <= 0:
                raise ValueError(f"PDF 第 {number} 页尺寸无效。")
            dpi = min(actual["width"] * 72 / width, actual["height"] * 72 / height)
            if dpi + 0.1 < max(min_dpi, float(manifest.get("dpi", 0))):
                raise ValueError(f"PDF 第 {number} 页分辨率不足: {dpi:.1f} DPI。")
    return expected_pages
