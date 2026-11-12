"""Losslessly embed PNG pages into a PDF, then verify every decoded page."""

import glob
import json
import math
import os
from pathlib import Path
import sys
import tempfile

import img2pdf
from PIL import Image

from pdf_quality import FORMAT_TAG, page_fingerprint, verify_pdf
from task_events import check_cancelled


def merge_png_to_pdf(input_dir=None, output_file=None, dpi=192.0):
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("DPI 必须是正数。")
    if input_dir is None:
        folders = sorted(
            [d for d in glob.glob("exam_pages/*") if os.path.isdir(d)],
            key=os.path.getmtime, reverse=True,
        )
        input_dir = folders[0] if folders else "exam_pages"
    files = sorted(
        Path(input_dir).glob("pdf_page_*.png"),
        key=lambda path: int(path.stem.split("_")[-1]),
    )
    if not files:
        print(f"未在 {input_dir} 下找到分页图片")
        return None
    if output_file is None:
        folder = Path(input_dir)
        output_file = str(folder / f"{folder.name}.pdf")
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for path in files:
        check_cancelled()
        with Image.open(path) as image:
            records.append(page_fingerprint(image))
    manifest = {"format": FORMAT_TAG, "dpi": dpi, "pages": records}
    descriptor, pending = tempfile.mkstemp(suffix=".pdf", dir=output_file.parent)
    os.close(descriptor)
    try:
        with open(pending, "wb") as stream:
            img2pdf.convert(
                *[str(path) for path in files], outputstream=stream,
                engine=img2pdf.Engine.pikepdf,
                layout_fun=img2pdf.get_fixed_dpi_layout_fun((dpi, dpi)),
                producer=FORMAT_TAG,
                subject=json.dumps(manifest, separators=(",", ":")),
            )
        verify_pdf(pending, len(files), min_dpi=dpi,
                   source_records=records, reject_blank=False)
        os.replace(pending, output_file)
    finally:
        if os.path.exists(pending):
            os.remove(pending)
    print(f"无损合并并校验完成: {output_file}（{len(files)} 页，{dpi:g} DPI）")
    return str(output_file)


def merge_missing_pdf(input_dir):
    folder = Path(input_dir)
    output_file = folder / f"{folder.name}.pdf"
    if output_file.is_file():
        return str(output_file)
    return merge_png_to_pdf(input_dir, str(output_file))


if __name__ == "__main__":
    merge_png_to_pdf(
        input_dir=sys.argv[1] if len(sys.argv) > 1 else None,
        output_file=sys.argv[2] if len(sys.argv) > 2 else None,
    )
