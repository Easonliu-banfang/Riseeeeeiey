"""Rebuilds the pre-built dist/ and docs/ artefacts from src/.

Why this exists: build.py needs `ref/wispcraft-26.2.html` (the 77 MB Eaglercraft
base build), which is not in this repository. Rather than shipping a broken
rebuild path, this script performs exactly the same edits build.py would make,
but on the artefacts that are already committed:

  * the inlined `src/i18n.js + src/rise.js` block is regenerated and swapped in
    (the Blueprint source, which lives outside this repo, is lifted back out of
    the existing build so nothing is lost),
  * the assets EPK gets the CJK blocks put back into unifont.zip plus the two
    `credits_and_attribution.button.credits` overrides,
  * the web build's payload, cache-busting version and version.txt are refreshed
    and dist/web/ is copied over docs/.

Usage:
    tools/i18n_build.py [--only dist|web|docs] [--check]

`--check` only reports what would change.
"""
import argparse, base64, hashlib, json, os, re, shutil, sys, zipfile, io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from epk import read_epk, write_epk          # noqa: E402
import build as build_mod                     # noqa: E402
from gen_glyphs_zh import unifont_path, load_unifont  # noqa: E402

EX = os.path.join(ROOT, 'theme_extra')
HTML = os.path.join(ROOT, 'dist', 'RiseClient.html')
WEB = os.path.join(ROOT, 'dist', 'web')
DOCS = os.path.join(ROOT, 'docs')
LINE = 262144
UNIFONT_NAME = 'assets/minecraft/font/unifont.zip'


# ---------------------------------------------------------------- assets
def cjk_lines(uni):
    """unifont .hex lines for the CJK blocks, keyed by codepoint."""
    out = {}
    for cp, h in uni.items():
        for a, b in build_mod.CJK_RANGES:
            if a <= cp <= b:
                out[cp] = ('%04X' % cp) + ':' + h
                break
    return out


def patch_unifont(zbytes, uni, stats):
    src = zipfile.ZipFile(io.BytesIO(zbytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith('.hex'):
                have = {}
                for line in data.decode('ascii').splitlines():
                    i = line.find(':')
                    if i > 0:
                        have[int(line[:i], 16)] = line
                added = 0
                for cp, line in cjk_lines(uni).items():
                    if cp not in have:
                        have[cp] = line
                        added += 1
                data = ('\n'.join(have[cp] for cp in sorted(have)) + '\n').encode('ascii')
                stats['unifont_glyphs'] = len(have)
                stats['unifont_added'] = added
            # keep the original entry timestamp: writestr() with a bare name
            # stamps the current time, which would make every rebuild differ
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zi.create_system = info.create_system
            dst.writestr(zi, data)
    return out.getvalue()


def patch_assets(epk_bytes, uni, stats):
    meta, files, _ = read_epk(epk_bytes)
    out = []
    for t, n, d in files:
        if t == 'FILE' and n == UNIFONT_NAME:
            before = len(d)
            d = patch_unifont(d, uni, stats)
            stats['unifont'] = '%.2f MB -> %.2f MB' % (before / 1e6, len(d) / 1e6)
        if t == 'FILE' and n in ('assets/minecraft/lang/en_us.json', 'assets/minecraft/lang/zh_cn.json'):
            lang = json.loads(d)
            lang.update(build_mod.LANG_ZH if n.endswith('zh_cn.json') else build_mod.LANG)
            d = json.dumps(lang, ensure_ascii=False, indent=1).encode('utf-8')
        out.append((t, n, d))
    meta['count'] = len(out)
    return write_epk(meta, out)


# ---------------------------------------------------------------- rise.js
def b64_lines(data):
    s = base64.b64encode(data).decode('ascii')
    return '\n' + '\n'.join(s[i:i + LINE] for i in range(0, len(s), LINE)) + '\n'


def find_rise_block(html):
    """(start, end) of the inlined rise.js payload inside the built page."""
    anchor = '<script type="module">'
    assert html.count(anchor) == 1, 'module boot anchor not found'
    end = html.index(anchor)
    head = html.rindex('<script type="text/javascript">', 0, end)
    start = head + len('<script type="text/javascript">\n')
    tail = '\n</script>\n\t'
    assert html[end - len(tail):end] == tail, 'unexpected script tail before the boot module'
    return start, end - len(tail)


def extract_blueprint(old_rise):
    """The BlueprintMod source is inlined as a JS string literal; hand it back
    *including* its quotes, which is what build.py's json.dumps() produces."""
    i = old_rise.index('var BLUEPRINT_SRC = ')
    m = re.compile(r'"((?:[^"\\]|\\.)*)"').match(old_rise, i + len('var BLUEPRINT_SRC = '))
    assert m, 'BLUEPRINT_SRC not found in the existing build'
    return m.group(0)


def rise_payload(bp_literal):
    assert bp_literal.startswith('"') and bp_literal.endswith('"'), 'blueprint literal lost its quotes'
    src = open(os.path.join(ROOT, 'src', 'i18n.js'), encoding='utf-8').read() + '\n' + \
        open(os.path.join(ROOT, 'src', 'rise.js'), encoding='utf-8').read()
    src = (src.replace('%GLYPHS_ZH%', open(os.path.join(EX, 'glyphs_zh.json')).read())
              .replace('%GLYPHS%', open(os.path.join(EX, 'glyphs.json')).read())
              .replace('%FONT%', base64.b64encode(open(os.path.join(EX, 'rise-font.ttf'), 'rb').read()).decode())
              .replace('%PACKS%', open(os.path.join(EX, 'packs.json')).read())
              .replace('%PREVIEWS%', open(os.path.join(EX, 'previews.json')).read())
              .replace('%SKINS%', open(os.path.join(EX, 'skins.json')).read())
              .replace('%BLUEPRINT%', bp_literal))
    assert '</script' not in src.lower(), 'rise.js payload would close the script tag'
    return src


# ---------------------------------------------------------------- offline html
def patch_offline(uni, stats, check):
    html = open(HTML, encoding='utf-8').read()
    start, end = find_rise_block(html)
    new_rise = rise_payload(extract_blueprint(html[start:end]))

    m = re.search(r'(<script type="application/octet-stream" id="eag-inline-assets" data-size=")(\d+)(">)(.*?)(</script>)', html, re.S)
    assert m, 'assets payload not found'
    old_size = int(m.group(2))
    epk = base64.b64decode(re.sub(r'\s', '', m.group(4)))
    assert len(epk) == old_size, 'assets payload size mismatch'
    new_epk = patch_assets(epk, uni, stats)

    if check:
        print('[offline] rise.js %d -> %d bytes, assets %d -> %d bytes'
              % (end - start, len(new_rise), old_size, len(new_epk)))
        return

    html = html[:m.start()] + m.group(1) + str(len(new_epk)) + m.group(3) + b64_lines(new_epk) + m.group(5) + html[m.end():]
    marker = 'var size = %d;' % old_size
    assert html.count(marker) == 1, 'asset size marker not found'
    html = html.replace(marker, 'var size = %d;' % len(new_epk))
    # the block moved when the payload above was rewritten: locate it again
    start, end = find_rise_block(html)
    html = html[:start] + new_rise + html[end:]
    open(HTML, 'w', encoding='utf-8').write(html)
    print('[offline] wrote %s (%.1f MB)' % (HTML, os.path.getsize(HTML) / 1e6))


# ---------------------------------------------------------------- web + docs
def patch_web(uni, stats, check, out_dir, version_in):
    index = os.path.join(out_dir, 'index.html')
    html = open(index, encoding='utf-8').read()
    start, end = find_rise_block(html)
    new_rise = rise_payload(extract_blueprint(html[start:end]))

    bin_path = os.path.join(out_dir, 'payload', 'eag-inline-assets.bin')
    epk = open(bin_path, 'rb').read()
    new_epk = patch_assets(epk, uni, stats)

    # one version string drives the payload URLs, the Cache API name and the
    # wasm cache keys, so it has to change whenever a payload changes
    version = hashlib.sha1(new_epk + new_rise.encode('utf-8')).hexdigest()[:12]
    old_version = re.search(r"var V = '([^']*)';", html)
    assert old_version, 'web loader version marker not found'
    if version_in:
        version = version_in

    if check:
        print('[web]   rise.js %d -> %d bytes, assets %d -> %d bytes, version %s -> %s'
              % (end - start, len(new_rise), len(epk), len(new_epk), old_version.group(1), version))
        return version

    html = html[:start] + new_rise + html[end:]
    html = html.replace("var V = '%s';" % old_version.group(1), "var V = '%s';" % version, 1)
    html = re.sub(r'var total = \d+, done = 0;', 'var total = %d, done = 0;' % len(new_epk), html, count=1)
    html = re.sub(r'var SIZES = \{.*?\};',
                  'var SIZES = {"eag-inline-assets": %d};' % len(new_epk), html, count=1, flags=re.S)
    open(bin_path, 'wb').write(new_epk)
    open(index, 'w', encoding='utf-8').write(html)
    open(os.path.join(out_dir, 'version.txt'), 'w').write(version)
    shutil.copy(os.path.join(ROOT, 'src', 'sw.js'), os.path.join(out_dir, 'sw.js'))
    print('[web]   wrote %s (%.1f MB) + payload (%.1f MB), version %s'
          % (index, os.path.getsize(index) / 1e6, len(new_epk) / 1e6, version))
    return version


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=['dist', 'web', 'docs'], action='append')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    want = set(a.only or ['dist', 'web', 'docs'])

    uni = load_unifont(unifont_path(None))
    stats = {}

    if 'dist' in want:
        patch_offline(uni, stats, a.check)

    version = None
    if 'web' in want:
        version = patch_web(uni, stats, a.check, WEB, None)
    if 'docs' in want:
        # docs/ is the published copy of dist/web; keep the same version
        v = None
        if not a.check:
            v = open(os.path.join(WEB, 'version.txt')).read().strip() if os.path.exists(os.path.join(WEB, 'version.txt')) else None
        patch_web(uni, stats, a.check, DOCS, v)

    for k in ('unifont', 'unifont_glyphs', 'unifont_added'):
        if k in stats:
            print('%-16s %s' % (k, stats[k]))


if __name__ == '__main__':
    main()
