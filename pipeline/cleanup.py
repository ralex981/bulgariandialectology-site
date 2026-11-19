"""Data clean-up applied while building (the Drupal database itself is never changed).

Every change is listed in build/cleanup-report.csv so it can be reviewed.

  1. Empty lines: line records that belong to no text (mostly blank shells titled ": ").
     They cannot be reached from any text page, so they are left out of the site.
  2. Test content: the "New location" placeholder, a phrase titled "test", and two test PDF uploads.
  3. Broken URL aliases: about 1,100 lines (and 3 news items) got URLs like
     locations/[field_location_reference-title-raw]/[field_text_number-raw]-4 because of an old
     Pathauto misconfiguration. They get clean URLs in the site's normal pattern; the old URLs keep
     working as redirects.
  4. Aliases that differ only by letter case (which clash on Mac/Windows disks) get a suffix.
  5. Tokens that no line uses are left out (Ronelle's decision; KEEP_ORPHAN_TOKENS=1 keeps them).
  6. Pages removed on request (Screenshots, Updates) and three PDF links repaired.
"""
import csv, os, re, unicodedata

TEST_NODE_TITLES = {('location', 'New location'), ('phrase', 'test')}
# pages Ronelle asked to remove (Site Information > Screenshots, Site Information > Updates)
REMOVED_PAGES = {32659: 'Screenshots', 66429: 'Future plans'}
# links to files that exist under a different name or path
LINK_FIXES = {
    '/sites/default/files/Strandzha.Cyr.pdf': '/sites/default/files/Strandzha.Cyr_.pdf',
    '/sites/default/files/vidinlom.pdf': '/sites/default/files/VidinLomCyr.pdf',
    '/file/Alexander.2021.Shumen.pdf': '/sites/default/files/Alexander.2021.Shumen.pdf',
}
TEST_FILES = {'test.pdf', 'cammerontestupload.pdf'}


def fold(alias):
    """Key under which two URLs land on the same file on a Mac or Windows disk
    (letter case and Unicode composition are both ignored there)."""
    return unicodedata.normalize('NFD', alias).casefold()


def slug(s):
    """Approximation of Pathauto's cleaning: lower case, punctuation removed, spaces to hyphens."""
    s = s.lower()
    s = re.sub(r"[^\w\s-]", '', s)
    s = re.sub(r'[\s_]+', '-', s).strip('-')
    return re.sub(r'-{2,}', '-', s)


def apply(c, report_path=None, drop_orphan_tokens=None):
    if drop_orphan_tokens is None:      # Ronelle: leave out tokens no line uses (KEEP_ORPHAN_TOKENS=1 keeps them)
        drop_orphan_tokens = os.environ.get('KEEP_ORPHAN_TOKENS') != '1'
    rows = []

    def drop(n, why):
        if n.status:
            n.status = 0
            rows.append(['removed', n.type, n.nid, n.title, n.alias, why])

    # 1. lines that belong to no text
    for n in list(c.nodes.values()):
        if n.type == 'line' and n.status and not n.get('text_reference'):
            has = 'has text content, review' if (n.get('full_line') or n.get('translation')) else 'empty'
            drop(n, f'line not attached to any text ({has})')

    # 2. test content
    for n in c.nodes.values():
        if (n.type, n.title) in TEST_NODE_TITLES:
            drop(n, 'test/placeholder record')
    for nid, title in REMOVED_PAGES.items():
        n = c.nodes.get(nid)
        if n is not None and n.title == title:
            drop(n, 'page removed at Ronelle\'s request')
    for n in c.nodes.values():               # repair links to misnamed files
        for f, vals in n.f.items():
            for i, v in enumerate(vals):
                if isinstance(v, str) and ('.pdf' in v):
                    w = v
                    for old, new in LINK_FIXES.items():
                        w = w.replace('bulgariandialectology.org' + old, 'bulgariandialectology.org' + new)
                    if w != v:
                        vals[i] = w
                        rows.append(['fixed link', n.type, n.nid, n.title, n.alias, 'PDF link pointed at a missing file'])
    c.skip_files = set(TEST_FILES)
    for f in TEST_FILES:
        rows.append(['removed', 'file', '', f, 'sites/default/files/' + f, 'test upload'])

    # 5. (optional) tokens no line uses
    if drop_orphan_tokens:
        used = set()
        for n in c.nodes.values():
            if n.type == 'line' and n.status:
                used.update(n.all('token_reference'))
        for n in c.nodes.values():
            if n.type == 'token' and n.nid not in used:
                drop(n, 'token not used in any line')

    # 3. broken aliases -> clean ones (old ones become redirects via url_alias)
    taken = {fold(a) for a in c.alias_of.values()}

    def unique(base):
        a, i = base, 0
        while fold(a) in taken:
            a = f'{base}-{i}'; i += 1
        taken.add(fold(a))
        return a

    for n in sorted(c.nodes.values(), key=lambda n: n.nid):
        if not n.status or '[' not in n.alias:
            continue
        old = n.alias
        prefix = 'news' if n.type == 'news' else 'locations'
        n.alias = unique(f'{prefix}/{slug(n.title) or n.type}')
        c.alias_of[f'node/{n.nid}'] = n.alias
        rows.append(['new URL', n.type, n.nid, n.title, n.alias, f'was {old}'])

    # 4. URLs that differ only in letter case or accent encoding (one file on Mac/Windows disks)
    seen = {}
    objs = [('node', n) for n in sorted(c.nodes.values(), key=lambda n: n.nid) if n.status] + \
           [('term', t) for t in sorted(c.terms.values(), key=lambda t: t.tid)]
    for kind, o in objs:
        k = fold(o.alias)
        if k in seen and seen[k] != o.alias:
            old = o.alias
            o.alias = unique(o.alias)
            src = f'node/{o.nid}' if kind == 'node' else f'taxonomy/term/{o.tid}'
            c.alias_of[src] = o.alias
            rows.append(['new URL', o.type if kind == 'node' else 'term', o.nid if kind == 'node' else o.tid,
                         o.title if kind == 'node' else o.name, o.alias, f'was {old} (clashed with {seen[k]})'])
        else:
            seen[k] = o.alias

    if report_path:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['action', 'type', 'nid', 'title', 'url', 'reason'])
            w.writerows(rows)
    return rows
