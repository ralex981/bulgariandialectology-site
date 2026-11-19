"""Compare generated pages against the live Drupal site.

For a random sample of pages of each type, fetch the live page and the local file and compare
  * the set of internal link targets in the main content
  * the multiset of words in the main content
Usage: python3 compare.py RAW.sqlite SITE_DIR [--per-type N] [--types a,b] [--seed S]"""
import argparse, os, random, re, sys, time, urllib.request
from collections import Counter
from urllib.parse import unquote, urlparse

import bs4

sys.path.insert(0, os.path.dirname(__file__))
from model import Corpus

LIVE = 'https://bulgariandialectology.org'
CACHE = os.path.join(os.path.dirname(__file__), '..', 'build', 'live-cache')


def fetch(alias):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, re.sub(r'[^\w.-]', '_', alias)[:180] + '.html')
    if os.path.exists(fn):
        return open(fn, encoding='utf-8').read()
    url = LIVE + '/' + urllib.request.quote(alias)
    with urllib.request.urlopen(url, timeout=60) as r:
        h = r.read().decode('utf-8')
    open(fn, 'w', encoding='utf-8').write(h)
    time.sleep(0.5)
    return h


def main_parts(h, live):
    s = bs4.BeautifulSoup(h, 'lxml')
    for t in s(['script', 'style', 'audio']):
        t.decompose()
    if live:
        regions = s.select('.region-content, .region-sidebar-first, .region-sidebar-second')
        for r in regions:   # drop jPlayer chrome and quicktab labels, which have no static equivalent
            for x in r.select('.jp-interface, .jp-controls, .item-list ul.quicktabs-tabs'):
                x.decompose()
        h1 = s.select_one('#main h1')
        roots = ([h1] if h1 else []) + regions
    else:
        roots = [x for x in [s.select_one('main'), s.select_one('aside.sidebar')] if x]
        for r in roots:
            for x in r.select('[role=tablist], .player'):
                x.decompose()
    links, words = set(), Counter()
    for r in roots:
        for a in r.select('a[href]'):
            u = urlparse(a['href'])
            if u.netloc and 'bulgariandialectology' not in u.netloc:
                continue
            p = unquote(u.path).rstrip('/')
            if p and not p.startswith('/sites/default/files'):
                links.add(p)
        words.update(w.lower() for w in re.findall(r'\w+', r.get_text(' ')))
    return links, words


def compare(alias, site):
    live = main_parts(fetch(alias), True)
    local_file = os.path.join(site, alias, 'index.html')
    loc = main_parts(open(local_file, encoding='utf-8').read(), False)
    missing_links = live[0] - loc[0]
    extra_links = loc[0] - live[0]
    missing_words = live[1] - loc[1]
    extra_words = loc[1] - live[1]
    return missing_links, extra_links, missing_words, extra_words


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('raw'); ap.add_argument('site')
    ap.add_argument('--per-type', type=int, default=5); ap.add_argument('--types'); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--verbose', '-v', action='store_true')
    a = ap.parse_args()
    c = Corpus(a.raw)
    rnd = random.Random(a.seed)
    types = a.types.split(',') if a.types else ['text', 'location', 'line', 'token', 'lexeme', 'phrase',
                                                'informant', 'linguistic_trait', 'page']
    for t in types:
        pool = [n for n in c.by_type[t] if not n.alias.startswith('node/')]
        for n in rnd.sample(pool, min(a.per_type, len(pool))):
            try:
                ml, el, mw, ew = compare(n.alias, a.site)
            except Exception as e:
                print(f'[{t}] {n.alias}: ERROR {e}')
                continue
            ok = not ml and not mw
            print(f'[{t}] {"OK " if ok else "DIFF"} {n.alias}  missing links {len(ml)}, extra links {len(el)}, '
                  f'missing words {sum(mw.values())}, extra words {sum(ew.values())}')
            if a.verbose and not ok:
                if ml: print('     missing links:', sorted(ml)[:8])
                if mw: print('     missing words:', mw.most_common(15))
                if ew: print('     extra words:  ', ew.most_common(10))
