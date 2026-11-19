"""Check every internal link and asset reference in the generated site resolves to a file.
Usage: python3 linkcheck.py SITE_DIR"""
import os, re, sys
from collections import Counter
from urllib.parse import unquote, urlparse

site = sys.argv[1]
HREF = re.compile(r'(?:href|src)="(/[^"#?]*)')
legacy_ok = re.compile(r'^/(node|taxonomy/term)/\d+$')   # resolved by 404.html
missing, checked, pages = Counter(), 0, 0
exists_cache = {}


def exists(p):
    if p not in exists_cache:
        fs = os.path.join(site, unquote(p).lstrip('/'))
        exists_cache[p] = os.path.isfile(fs) or os.path.isfile(os.path.join(fs, 'index.html'))
    return exists_cache[p]


for root, dirs, files in os.walk(site):
    for fn in files:
        if not fn.endswith('.html'):
            continue
        pages += 1
        with open(os.path.join(root, fn), encoding='utf-8') as f:
            for u in HREF.findall(f.read()):
                if u.startswith('//'):
                    continue
                checked += 1
                if u == '/' or exists(u) or legacy_ok.match(unquote(u).rstrip('/')):
                    continue
                if u.startswith('/sites/default/files/audio/'):
                    continue          # audio is hosted separately
                missing[unquote(u)] += 1
print(f'{pages} pages, {checked} links checked, {len(missing)} distinct broken targets, {sum(missing.values())} broken links')
for u, n in missing.most_common(40):
    print(f'{n:6d}  {u}')
