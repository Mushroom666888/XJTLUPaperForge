"""Rebuild the seven selected stickers from the user-supplied 1070 x 697 expression sheet.

Usage: python tools/prepare_expressions.py path/to/source.jpg
The private source photo is deliberately not bundled in this repository.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter, PngImagePlugin

CELLS = [
    ('validating', (0, 36, 270, 342)), ('issue', (280, 56, 538, 350)),
    ('success', (544, 55, 808, 334)),
    ('starting', (0, 416, 264, 682)), ('searching', (273, 418, 532, 670)),
    ('idle', (538, 466, 810, 697)), ('downloading', (814, 415, 1070, 672)),
]


def matte(gray):
    ink = gray.point(lambda v: 255 if v < 210 else 0)
    ink = ink.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    for xy in ((0, ink.height - 1), (ink.width - 1, ink.height - 1), (0, 0), (ink.width - 1, 0)):
        if ink.getpixel(xy) == 0:
            ImageDraw.floodfill(ink, xy, 128, thresh=0)
    mask = ink.point(lambda v: 0 if v == 128 else 255)
    w, h = gray.size
    seen, clean = set(), Image.new('L', (w, h))
    source, target = mask.load(), clean.load()
    for y in range(h):
        for x in range(w):
            if not source[x, y] or (x, y) in seen:
                continue
            stack, region = [(x, y)], []
            seen.add((x, y))
            while stack:
                a, b = stack.pop()
                region.append((a, b))
                for nx, ny in ((a-1, b), (a+1, b), (a, b-1), (a, b+1)):
                    if 0 <= nx < w and 0 <= ny < h and source[nx, ny] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(region) > 30:
                for a, b in region:
                    target[a, b] = 255
    return clean


def sticker(source, name, box):
    gray = source.crop(box).filter(ImageFilter.MedianFilter(3))
    w, h = gray.size
    mask = matte(gray)
    mask = mask.filter(ImageFilter.GaussianBlur(.6))
    image = Image.new('RGBA', gray.size)
    for y in range(h):
        for x in range(w):
            v = gray.getpixel((x, y)) / 255
            if v < .59:
                t = (v / .59) ** 2
                color = (31 + 39*t, 35 + 23*t, 32 + 12*t)
            elif v < .82:
                t = (v - .59) / .23
                color = (100 + 90*t, 70 + 74*t, 46 + 61*t)
            else:
                t = (v - .82) / .18
                color = (210 + 43*t, 170 + 61*t, 135 + 70*t)
            light = max(0, 1 - ((x/w-.32)**2/.17 + (y/h-.23)**2/.22)) * 10
            color = tuple(min(255, int(c + light)) for c in color)
            if name == 'idle' and y > h*.88 and .35 < x/w < .84:
                color = tuple(int(c * v) for c in (102, 145, 122))
            image.putpixel((x, y), color + (mask.getpixel((x, y)),))
    blush = Image.new('RGBA', gray.size)
    draw = ImageDraw.Draw(blush)
    if name != 'idle':
        yy = .78 if name in ('starting','searching','downloading') else .72
        for xx in (.22, .67):
            draw.ellipse((w*xx-12, h*yy-4, w*xx+12, h*yy+5), fill=(226,112,99,95))
        blush = blush.filter(ImageFilter.GaussianBlur(5))
        blush.putalpha(ImageChops.multiply(blush.getchannel('A'), mask))
        image = Image.alpha_composite(image, blush)
    image = image.crop(mask.getbbox())
    image.thumbnail((268, 268), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (320, 320))
    pos = ((320-image.width)//2, (304-image.height)//2)
    alpha = Image.new('L', canvas.size)
    alpha.paste(image.getchannel('A'), pos)
    rim = alpha.filter(ImageFilter.MaxFilter(9))
    offset = Image.new('L', canvas.size)
    offset.paste(rim, (0, 7))
    shadow = Image.new('RGBA', canvas.size, (53,40,28,0))
    shadow.putalpha(offset.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v*.22)))
    canvas = Image.alpha_composite(canvas, shadow)
    paper = Image.new('RGBA', canvas.size, (255,251,240,255))
    paper.putalpha(rim)
    canvas = Image.alpha_composite(canvas, paper)
    canvas.alpha_composite(image, pos)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'frontend/assets')
    args = parser.parse_args()
    source = Image.open(args.source).convert('L')
    if source.size != (1070, 697):
        parser.error('Expected the original 1070 x 697 expression sheet.')
    args.output.mkdir(parents=True, exist_ok=True)
    info = PngImagePlugin.PngInfo()
    info.add_text('Source', 'User-supplied eight-expression reference sheet, cropped and colorized locally; see ASSETS.md.')
    for name, box in CELLS:
        sticker(source, name, box).save(args.output / (name + '.png'), pnginfo=info, optimize=True)


if __name__ == '__main__':
    main()
