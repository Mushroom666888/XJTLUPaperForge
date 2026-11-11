"""Verify page pixels, page count and resolution for image-based exam PDFs."""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader

FORMAT_TAG = "exam-drm-bypass-lossless-v1"


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
