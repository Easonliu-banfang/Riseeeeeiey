"""Regenerates theme_extra/glyphs_zh.json — the bitmaps Rise's screen reader
matches against when the game is running in Chinese.

The English reader uses theme_extra/glyphs.json (font/ascii.png, 8x8 cells).
Chinese needs two extra sources:

  * unifont's .hex data for the ideographs. The game draws those with
    getOversample() == 2, so a 16x16 unifont glyph lands on the screen as 8x8 px
    and advances width/2 + 1 = 9. The atlas is sampled GL_NEAREST, so the 8
    output pixels do not simply average each 2x2 block — they pick one texel out
    of it. rise.js therefore stores four candidate sample sets and matches all
    of them; this script only has to emit the raw 16x16 bitmaps.

  * font/nonlatin_european.png for the ellipsis in "视频设置…", which the game
    takes from a bitmap provider (8x8, advance = ink width + 1).

Usage:
    tools/gen_glyphs_zh.py [--unifont PATH] [--assets PATH] [--out PATH]

`--unifont` defaults to the copy the script downloads into .unifont-cache/.
`--assets` defaults to dist/web/payload/eag-inline-assets.bin (only needed for
the ellipsis); it falls back to the built-in width if the file is missing.
"""
import argparse, io, json, os, re, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

UNIFONT_URL = ('https://unifoundry.com/pub/unifont/unifont-17.0.01/font-builds/'
               'unifont_all-17.0.01.hex.gz')
CACHE = os.path.join(ROOT, '.unifont-cache')
UNIFONT_HEX = 'unifont_all-17.0.01.hex'
UNIFONT_ZIP = 'unifont_all-17.0.01.hex.gz'
ELLIPSIS = '\u2026'

# Every character Rise's Chinese screen reader has to recognise:
#   options.title, options.videoTitle, options.video, menu.game,
#   menu.returnToMenu, menu.disconnect
DETECT_TEXT = '选项视频设置游戏菜单保存并退回到标题屏幕断开连接'


def unifont_path(explicit):
    if explicit:
        return explicit
    os.makedirs(CACHE, exist_ok=True)
    plain = os.path.join(CACHE, UNIFONT_HEX)
    if not os.path.exists(plain):
        gz = os.path.join(CACHE, UNIFONT_ZIP)
        if not os.path.exists(gz):
            print('downloading %s' % UNIFONT_URL)
            urllib.request.urlretrieve(UNIFONT_URL, gz)
        import gzip, shutil
        with gzip.open(gz, 'rb') as f, open(plain, 'wb') as o:
            shutil.copyfileobj(f, o)
    return plain


def load_unifont(path):
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            i = line.find(':')
            if i <= 0:
                continue
            try:
                cp = int(line[:i], 16)
            except ValueError:
                continue
            if cp < 0x10000:
                out[cp] = line[i + 1:]
    return out


def bitmap_glyph(png, cell, ink_cells=8):
    """One 8x8 cell of a font bitmap -> [8, rows] with column 0 in bit 0."""
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert('RGBA')
    px = im.load()
    cx, cy = cell
    rows, width = [], 0
    for y in range(8):
        bits = 0
        for x in range(8):
            if px[cx * 8 + x, cy * 8 + y][3] > 128:
                bits |= 1 << x
                width = max(width, x + 1)
        rows.append(bits)
    return [8, rows, width]


def ellipsis_glyph(assets):
    """U+2026 as the game renders it, or None if the asset pack is missing."""
    if not os.path.exists(assets):
        return None
    from epk import read_epk
    meta, files, _ = read_epk(open(assets, 'rb').read())
    d = {n: data for t, n, data in files if t == 'FILE'}
    j = json.loads(d['assets/minecraft/font/include/default.json'])
    for p in j['providers']:
        if p.get('file', '').endswith('nonlatin_european.png') and 'chars' in p:
            for y, row in enumerate(p['chars']):
                for x, ch in enumerate(row):
                    if ch == ELLIPSIS:
                        return bitmap_glyph(d['assets/minecraft/textures/font/nonlatin_european.png'], (x, y))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--unifont')
    ap.add_argument('--assets', default=os.path.join(ROOT, 'dist/web/payload/eag-inline-assets.bin'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'theme_extra/glyphs_zh.json'))
    a = ap.parse_args()

    uni = load_unifont(unifont_path(a.unifont))
    out = {}
    for ch in sorted(set(DETECT_TEXT)):
        h = uni.get(ord(ch))
        if not h:
            raise SystemExit('unifont has no glyph for %r (U+%04X)' % (ch, ord(ch)))
        w = len(h) // 2 // 16          # bytes per row
        if w not in (1, 2):
            raise SystemExit('unexpected glyph width %d for %r' % (w, ch))
        rows = [int(h[y * w * 2:(y + 1) * w * 2], 16) for y in range(16)]
        if w == 1:                     # 8-wide: only the top 8 rows are ink in practice
            rows = [r << 8 for r in rows]
        out[ch] = [16, rows, 8]        # 16x16 source, 8 px on screen

    e = ellipsis_glyph(a.assets)
    if e:
        out[ELLIPSIS] = e
        print('ellipsis: ink width %d -> advance %d' % (e[2], e[2] + 1))
    else:
        print('ellipsis: asset pack not found, skipped')

    json.dump(out, open(a.out, 'w'), ensure_ascii=False, separators=(',', ':'))
    print('wrote %s: %d glyphs, %d bytes' % (a.out, len(out), os.path.getsize(a.out)))


if __name__ == '__main__':
    main()
