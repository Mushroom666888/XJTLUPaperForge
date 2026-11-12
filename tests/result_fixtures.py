"""Generated PDFs and protocol records for workbench tests, never school data."""
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw
from merge_png_to_pdf import merge_png_to_pdf
from result_audit import file_sha256, record_id
from task_events import PREFIX


def event(consume, kind, **fields):
    consume(PREFIX + json.dumps(dict(event=kind, **fields)))


def plan(consume, course, count):
    items = [{'id': record_id(f'https://fixture.test/{course}/{i}'),
              'label': f'{course} exam {i + 1}'} for i in range(count)]
    event(consume, 'inventory', total=count)
    event(consume, 'catalog', total=count, items=items)
    return items


def verified(consume, output, course, item, name=None, pages=1):
    name = name or f"{course}_{item['label'].split()[-1]}_F.pdf"
    folder = Path(output) / course
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with tempfile.TemporaryDirectory() as temporary:
        for number in range(1, pages + 1):
            image = Image.new('RGB', (160, 240), 'white')
            draw = ImageDraw.Draw(image)
            draw.text((10, 10), f'{course} {number} {item["id"][:8]}', fill='black')
            draw.line((10, 30, 130, 40 + number), fill='blue', width=3)
            image.save(Path(temporary) / f'pdf_page_{number:03d}.png')
        merge_png_to_pdf(temporary, path, dpi=300,
                         source_identity={'record_sha256': item['id'], 'course': course, 'version': 1})
    fields = dict(id=item['id'], name=name, pages=pages, sha256=file_sha256(path))
    event(consume, 'verified', **fields)
    return path, fields


def summary(consume, items, successes=None, failures=None):
    event(consume, 'summary', total=len(items),
          succeeded=[item['id'] for item in (items if successes is None else successes)],
          failed=[item['id'] for item in (failures or [])])
