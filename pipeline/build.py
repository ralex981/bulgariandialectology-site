"""Stage 2: Corpus -> static site.

Usage:  python3 build.py RAW.sqlite FILES_DIR HEADERIMG_DIR OUT_DIR [--only TYPE,...] [--limit N]

FILES_DIR is the unpacked Drupal files directory (files_live/); audio is not copied
(see AUDIO_BASE in config) because it is large and is better hosted separately."""
import argparse, hashlib, json, os, random, shutil, sys, time
from collections import defaultdict
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader

from model import Corpus, _php
from render import esc, rich, fix_links
import search
from collate import key as ckey, js as collate_js

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_URL = os.environ.get('SITE_URL', 'https://bulgariandialectology.org')
AUDIO_BASE = os.environ.get('AUDIO_BASE', '/sites/default/files/audio/')
# STAGING=1: keep search engines out (robots.txt + noindex) while the site is reviewed
STAGING = os.environ.get('STAGING') == '1'
# Custom domain for GitHub Pages (written to site/CNAME), e.g. staging.bulgariandialectology.org
PAGES_DOMAIN = os.environ.get('PAGES_DOMAIN', '')

# Order of grammatical fields in the gloss line under each token (from view text_based_rochelle)
GLOSS_FIELDS = ['meaning', 'case', 'number', 'gram_gender', 'definiteness', 'person', 'tense', 'aspect',
                'particle', 'deictic', 'clitic', 'other', 'pragmatic']


def url_path(alias):
    """URL for an alias, percent-encoded the way browsers send it."""
    return '/' + quote(alias, safe="/-._~!$&'()*+,;=:@[]")


def secs(tc):
    """'1:23' -> 83 ; '1:02:03' -> 3723 ; None on junk."""
    if not tc:
        return None
    try:
        parts = [float(p) for p in str(tc).strip().strip('[]').split(':')]
    except ValueError:
        return None
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


class Site:
    def __init__(self, raw, files_dir, header_dir, out, args):
        t0 = time.time()
        self.c = Corpus(raw, cleanup_report=os.path.join(os.path.dirname(os.path.abspath(raw)), 'cleanup-report.csv'))
        print(f'corpus loaded in {time.time() - t0:.1f}s')
        self.files_dir, self.header_dir, self.out, self.args = files_dir, header_dir, out, args
        self.env = Environment(loader=FileSystemLoader(os.path.join(HERE, 'templates')), autoescape=False)
        self.base = self.env.get_template('base.html')
        # cache-busting id = hash of the CSS/JS, so pages only change when their content does
        h = hashlib.md5()
        for fn in sorted(os.listdir(os.path.join(HERE, 'static'))):
            h.update(open(os.path.join(HERE, 'static', fn), 'rb').read())
        self.build_id = h.hexdigest()[:8]
        self.header_imgs = sorted(os.listdir(header_dir)) if header_dir and os.path.isdir(header_dir) else []
        self.written = 0
        self.site_name = self._var('site_name') or 'Bulgarian Dialectology as Living Tradition'
        self.blocks = {r['bid']: r['body'] for r in self.c.db.execute('select bid, body from block_custom')}
        self.footer = rich(self.blocks.get(9, ''), 'full_html')
        self.menu = self._menu()

    # ------------------------------------------------------------------ infra
    def _var(self, name):
        r = self.c.db.execute('select value from variable where name=?', (name,)).fetchone()
        return _php(r[0]) if r else None

    def _menu(self):
        rows = list(self.c.db.execute(
            "select mlid, plid, link_path, link_title, options, hidden, weight from menu_links "
            "where menu_name='main-menu' and hidden=0 order by weight, link_title"))
        known_paths = {n.alias for n in self.c.nodes.values()} | {
            'status-texts', 'wordform-search', 'lexemes', 'mapdev', 'thematic-list', 'phrase-search',
            'all_tokens_user', 'locations', 'lexeme-search'}
        items = {}
        for r in rows:
            p = r['link_path']
            if p == '<front>':
                href = '/'
            elif p.startswith('http'):
                href = fix_links(p)
            elif p.startswith('node/'):
                n = self.c.node(int(p.split('/')[1]))
                if not n:
                    continue
                href = url_path(n.alias)
            else:
                if p not in known_paths:
                    continue          # menu item points at a page that no longer exists (Drupal hides these too)
                href = '/' + p
            opts = _php(r['options']) or {}
            items[r['mlid']] = dict(title=r['link_title'], href=href, plid=r['plid'], children=[],
                                    title_attr=esc((opts.get('attributes') or {}).get('title', '')))
        top = []
        for mlid, it in items.items():
            if it['plid'] and it['plid'] in items:
                items[it['plid']]['children'].append(it)
            elif not it['plid']:
                top.append(it)
        return top

    def write(self, alias, title, content, *, sidebar='', breadcrumb=None, needs_map=False, page_class='page',
              show_title=True, lang='en', head='', scripts=''):
        alias = alias.strip('/')
        rel = os.path.join(alias, 'index.html') if alias else 'index.html'
        path = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmpl = self.base
        if head or scripts:
            tmpl = self.env.from_string(
                "{% extends 'base.html' %}{% block head %}" + head + "{% endblock %}"
                "{% block scripts %}" + scripts + "{% endblock %}")
        html = tmpl.render(
            title=title, content=content, sidebar=sidebar, breadcrumb=breadcrumb, needs_map=needs_map,
            page_class=page_class, show_title=show_title, lang=lang, site_name=self.site_name,
            menu=self.menu, footer=self.footer, build_id=self.build_id,
            canonical=SITE_URL + (url_path(alias) if alias else '/'), staging=STAGING,
            header_img=random.Random(alias).choice(self.header_imgs) if self.header_imgs else '')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        self.written += 1

    # ------------------------------------------------------------------ field rendering
    def link(self, obj, label=None):
        if obj is None:
            return ''
        return f'<a href="{url_path(obj.alias)}">{esc(label if label is not None else obj.title if hasattr(obj, "title") else obj.name)}</a>'

    def field_values_html(self, node, name):
        """Rendered values of one field, as a list of HTML snippets."""
        c, typ = self.c, self.c.field_type.get(name, '')
        out = []
        for v in node.all(name):
            if typ.startswith('list_'):
                out.append(c.label(name, v))           # labels are trusted admin-entered HTML
            elif typ == 'node_reference':
                ref = c.node(v)
                if ref:
                    out.append(self.link(ref))
            elif typ == 'taxonomy_term_reference':
                t = c.terms.get(v)
                if t:
                    out.append(self.link(t))
            elif typ in ('text_long', 'text_with_summary'):
                out.append(rich(v, node.fmt.get(name)))
            elif typ == 'text':
                out.append(esc(v))
            else:
                out.append(esc(v))
        return out

    def field_block(self, node, name, label=None, mode='inline'):
        vals = self.field_values_html(node, name)
        if not vals:
            return ''
        label = label if label is not None else self.c.labels[node.type].get(name, name)
        cls = f'field field-{name.replace("_", "-")} label-{mode}'
        lab = f'<div class="field-label">{esc(label)}:</div>' if mode != 'hidden' else ''
        items = ''.join(f'<div class="field-item">{v}</div>' for v in vals)
        return f'<div class="{cls}">{lab}<div class="field-items">{items}</div></div>'

    def display_fields(self, node):
        """Fields in the order and label style Drupal's 'default' display uses for this bundle."""
        rows = []
        for r in self.c.db.execute("select field_name, data from field_config_instance "
                                   "where entity_type='node' and bundle=? and deleted=0", (node.type,)):
            d = _php(r['data'])
            disp = d.get('display', {}).get('default', {})
            if disp.get('type') == 'hidden' or self.c.field_type.get(r['field_name'].removeprefix('field_')) == 'geofield':
                continue
            rows.append((float(disp.get('weight', 0)), r['field_name'].removeprefix('field_'),
                         disp.get('label', 'above'), d.get('label')))
        rows.sort()
        return rows

    # caches
    _disp_cache = {}

    def fields_for(self, bundle, node):
        if bundle not in self._disp_cache:
            self._disp_cache[bundle] = self.display_fields(node)
        return self._disp_cache[bundle]

    def render_default(self, node, skip=(), order=None):
        rows = self.fields_for(node.type, node)
        if order:  # Display Suite layout order
            pos = {f: i for i, f in enumerate(order)}
            rows = sorted([r for r in rows if r[1] in pos], key=lambda r: pos[r[1]])
        return ''.join(self.field_block(node, name, label, mode)
                       for _, name, mode, label in rows if name not in skip)

    # ------------------------------------------------------------------ pieces
    def gloss(self, tok):
        bits = []
        for f in GLOSS_FIELDS:
            vals = tok.all(f)
            if vals:
                bits.append(', '.join(esc(self.c.label(f, v)) if f != 'meaning' else esc(v) for v in vals))
        return ' '.join(bits)

    def line_heading(self, line, text):
        spk = self.c.speaker(line)
        tc = line.get('timecode')
        n = line.get('line_number', '')
        tc_html = f' <button class="tc" data-t="{secs(tc)}" title="Play from {esc(tc)}">[{esc(tc)}]</button>' if tc and secs(tc) is not None else (f' [{esc(tc)}]' if tc else '')
        return f'<span class="ln">{esc(n)}</span> <span class="spk">({esc(spk)})</span>{tc_html}'

    def map_html(self, points, height=220, zoom=None, cls='map'):
        """points: [(lat, lon, label_html)]"""
        if not points:
            return ''
        data = esc(json.dumps([[p[0], p[1], p[2]] for p in points], ensure_ascii=False))
        z = f' data-zoom="{zoom}"' if zoom else ''
        return f'<div class="{cls} leaflet-map" style="height:{height}px" data-points="{data}"{z}></div>'

    def loc_point(self, loc, label=None):
        co = loc.get('coordinates') if loc else None
        if not co:
            return None
        return (co[0], co[1], label if label is not None else self.link(loc))

    # ------------------------------------------------------------------ page types
    def page_text(self, t):
        c = self.c
        loc = c.location_of_text(t)
        lines = c.lines_of_text.get(t.nid, [])
        # --- sidebar (blocks in region sidebar_first, in Drupal's weight order)
        sb = []
        img = t.get('village_image')
        if img and c.file_url(img):
            sb.append(f'<div class="block"><img src="{esc(c.file_url(img))}" alt="{esc(loc.title if loc else "")}" loading="lazy"></div>')
        pt = self.loc_point(loc)
        if pt:
            sb.append(f'<div class="block"><h3>Map</h3>{self.map_html([pt], 200, zoom=8)}</div>')
        for f in ('date_of_recording', 'text_size', 'word_count', 'physical_context_recording', 'recording_team', 'synopsis'):
            fb = self.field_block(t, f)
            if fb:
                sb.append(f'<div class="block">{fb}</div>')
        # participants: informants referenced by this text's lines, investigators first
        infs, seen = [], set()
        for l in lines:
            i = c.node(l.get('informant_reference'))
            if i and i.nid not in seen:
                seen.add(i.nid); infs.append(i)
        infs.sort(key=lambda i: (0 if i.get('investigator') else 1, i.get('informant_id') or ''))
        if infs:
            parts = []
            for i in infs:
                det = ''.join(filter(None, [rich(i.get('body'), i.fmt.get('body')) if i.get('body') else '',
                                            f'<div>{esc(i.get("gender"))}</div>' if i.get('gender') else '',
                                            f'<div>Age: {esc(i.get("age"))}</div>' if i.get('age') else '']))
                parts.append(f'<h4><a href="{url_path(i.alias)}">{esc(i.get("informant_id") or i.title)}</a></h4>{det}')
            sb.append('<div class="block participants"><h3>Participants</h3>' + ''.join(parts) + '</div>')

        # --- main column
        audio = c.file_url(t.get('audio'))
        out = []
        if audio:
            fname = os.path.basename(audio)
            src = AUDIO_BASE + quote(fname)
            out.append(f'<div class="player"><audio id="audio" controls preload="metadata" src="{esc(src)}"></audio>'
                       f'<div class="player-meta"><a href="{esc(src)}" download>{esc(fname)}</a>'
                       f'<label><input type="checkbox" id="follow" checked> Follow along</label></div></div>')
        out.append(self.field_block(t, 'textual_notes', 'Commentary on the text', 'above'))
        out.append(self.field_block(t, 'text_commentary'))

        glossed, linev, cyr = [], [], []
        for l in lines:
            ts = secs(l.get('timecode'))
            data_t = f' data-t="{ts}"' if ts is not None else ''
            head = self.line_heading(l, t)
            # glossed view: heading = number (speaker) [time] translation, then token grid
            toks = []
            for tid in l.all('token_reference'):
                tok = c.node(tid)
                if not tok:
                    continue
                lex = c.node(tok.get('lexeme'))
                toks.append('<div class="tok">'
                            f'<a class="w" href="{url_path(tok.alias)}">{esc(tok.title)}</a>'
                            f'<span class="g">{self.gloss(tok) or "&nbsp;"}</span>'
                            f'<span class="lx">{self.link(lex) if lex else "&nbsp;"}</span></div>')
            glossed.append(f'<section class="line"{data_t} id="l{esc(l.get("line_number"))}">'
                           f'<h3>{head} <span class="tr">{esc(l.get("translation"))}</span></h3>'
                           f'<div class="toks">{"".join(toks)}</div></section>')
            linev.append(f'<section class="line"{data_t}><h5>{head} <a href="{url_path(l.alias)}">{esc(l.get("full_line"))}</a></h5>'
                         f'<p class="tr">{esc(l.get("translation"))}</p></section>')
            cyr.append(f'<section class="line"{data_t}><h5>{head} <span lang="bg">{esc(l.get("cyrillic_full_line"))}</span></h5></section>')
        out.append(
            '<div class="tabs" data-tabs>'
            '<div role="tablist">'
            '<button role="tab" aria-selected="true" data-tab="glossed">Glossed Text</button>'
            '<button role="tab" aria-selected="false" data-tab="line">Line Display</button>'
            '<button role="tab" aria-selected="false" data-tab="cyrillic">Cyrillic Line Display</button></div>'
            f'<div class="tabpanel text-glossed" data-panel="glossed">{"".join(glossed)}</div>'
            f'<div class="tabpanel text-lines" data-panel="line" hidden>{"".join(linev)}</div>'
            f'<div class="tabpanel text-lines" data-panel="cyrillic" hidden>{"".join(cyr)}</div></div>')
        bc = [('/', 'Home'), ('/locations', 'Locations')]
        if loc:
            bc.append((url_path(loc.alias), loc.title))
        bc.append((None, t.title))
        self.write(t.alias, t.title, ''.join(out), sidebar=''.join(sb), breadcrumb=bc, needs_map=bool(pt),
                   page_class='text')

    def page_location(self, loc):
        c = self.c
        texts = c.texts_of_location.get(loc.nid, [])
        out = []
        if texts:
            out.append('<div class="block texts"><h3>Texts</h3><ul class="plain">' +
                       ''.join(f'<li>{self.link(t)}</li>' for t in sorted(texts, key=lambda t: ckey(t.title))) + '</ul></div>')
        out.append(self.render_default(loc))
        sb = []
        pt = self.loc_point(loc, esc(loc.title))
        if pt:
            sb.append(f'<div class="block"><h3>Map</h3>{self.map_html([pt], 220, zoom=8)}</div>')
        for fid in loc.all('location_image'):
            u = c.file_url(fid)
            if u:
                sb.append(f'<div class="block"><img src="{esc(u)}" alt="{esc(loc.title)}" loading="lazy"></div>')
        self.write(loc.alias, loc.title, ''.join(out), sidebar=''.join(sb), needs_map=bool(pt),
                   breadcrumb=[('/', 'Home'), ('/locations', 'Locations'), (None, loc.title)], page_class='location')

    def page_line(self, l):
        c = self.c
        order = ['full_line', 'cyrillic_full_line', 'translation', 'text_reference', 'timecode', 'token_reference',
                 'narrative_structure', 'note', 'thematic_content', 'discourse_elements', 'body']
        out = [self.render_default(l, order=order)]
        ph = sorted(c.phrases_of_line.get(l.nid, []), key=lambda p: -p.created)
        if ph:
            out.append('<div class="field label-inline"><div class="field-label">Phrases:</div><div class="field-items">' +
                       ''.join(f'<div class="field-item">{self.link(p)}</div>' for p in ph) + '</div></div>')
        t = c.text_of_line(l)
        if t and c.file_url(t.get('audio')) and secs(l.get('timecode')) is not None:
            src = AUDIO_BASE + quote(os.path.basename(c.file_url(t.get('audio'))))
            nxt = None
            ls = c.lines_of_text.get(t.nid, [])
            later = [secs(x.get('timecode')) for x in ls if (x.get('line_number') or 0) > (l.get('line_number') or 0)
                     and secs(x.get('timecode')) is not None]
            if later:
                nxt = min(later)
            frag = f'#t={secs(l.get("timecode"))}' + (f',{nxt}' if nxt else '')
            out.insert(0, f'<div class="player small"><audio controls preload="none" src="{esc(src + frag)}"></audio></div>')
        self.write(l.alias, l.title, ''.join(out), breadcrumb=[('/', 'Home'), (None, l.title)], page_class='line')

    def lines_list(self, lines):
        c = self.c

        def key(l):
            t = c.text_of_line(l)
            return (ckey(t.title) if t else ((), ''), l.get('line_number') or 0)
        return ''.join(f'<li>{self.link(l)} - <span class="fl">{esc(l.get("full_line"))}</span></li>'
                       for l in sorted(lines, key=key))

    def page_token(self, tok):
        c = self.c
        out = [self.render_default(tok)]
        lines = c.lines_of_token.get(tok.nid, [])
        if lines:
            out.append(f'<div class="block"><h3>Lines where {esc(tok.title)} appears</h3><ul class="plain lines">'
                       + self.lines_list(lines) + '</ul></div>')
        self.write(tok.alias, tok.title, ''.join(out), breadcrumb=[('/', 'Home'), (None, tok.title)], page_class='token')

    def page_lexeme(self, lx):
        c = self.c
        out = [self.render_default(lx)]
        toks = sorted(c.tokens_of_lexeme.get(lx.nid, []), key=lambda t: ckey(t.title))
        if toks:
            rows = []
            for t in toks:
                n = len(c.lines_of_token.get(t.nid, []))
                rows.append(f'<tr><td>{self.link(t)}</td><td>{esc(self.gloss(t))}</td><td class="num">{n}</td></tr>')
            out.append('<div class="block"><h3>Tokens</h3><table class="data"><thead><tr><th>Token</th><th>Gloss</th>'
                       '<th>Occurrences</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
        self.write(lx.alias, lx.title, ''.join(out), breadcrumb=[('/', 'Home'), (None, lx.title)], page_class='lexeme')

    def page_generic(self, n):
        out = [self.render_default(n)]
        if n.type == 'linguistic_trait':
            toks = sorted(self.c.tokens_of_trait.get(n.nid, []), key=lambda t: ckey(t.title))
            if toks:
                out.append('<div class="block"><h3>Tokens</h3><ul class="plain cols">' +
                           ''.join(f'<li>{self.link(t)}</li>' for t in toks) + '</ul></div>')
        lang = 'bg' if any('Ѐ' <= ch <= 'ӿ' for ch in n.title[:5]) else 'en'
        self.write(n.alias, n.title, ''.join(out), breadcrumb=[('/', 'Home'), (None, n.title)],
                   page_class=n.type, lang=lang)

    def page_term(self, term):
        c = self.c
        out = []
        if term.description:
            out.append(rich(term.description, 'filtered_html'))
        if term.children:
            out.append('<ul class="plain">' + ''.join(f'<li>{self.link(c.terms[ch])}</li>' for ch in term.children) + '</ul>')
        by_text = {}
        for l in c.lines_of_term.get(term.tid, []):
            t = c.text_of_line(l)
            if t:
                by_text.setdefault(t.nid, (t, []))[1].append(l)
        for t, ls in sorted(by_text.values(), key=lambda x: ckey(x[0].title)):
            out.append(f'<h3>{self.link(t)}</h3><div class="text-lines">')
            for l in sorted(ls, key=lambda l: l.get('line_number') or 0):
                out.append(f'<section class="line"><h5><a href="{url_path(l.alias)}">{esc(l.get("line_number"))} '
                           f'({esc(c.speaker(l))})</a> {esc(l.get("full_line"))}</h5>'
                           f'<p class="tr">{esc(l.get("translation"))}</p></section>')
            out.append('</div>')
        vocab = c.vocabs[term.vid]['name']
        self.write(term.alias, term.name, ''.join(out), breadcrumb=[('/', 'Home'), (None, vocab), (None, term.name)],
                   page_class='term')

    # ------------------------------------------------------------------ listing pages
    def page_front(self):
        c = self.c
        locs = sorted(c.by_type['location'], key=lambda n: ckey(n.title))
        # the old view excluded 'New Location' (MySQL compares case-insensitively)
        locs = [l for l in locs if l.title.lower() != 'new location']
        pts = [p for p in (self.loc_point(l) for l in locs) if p]
        # alphabetical village list, flowing down columns as on the old site
        grid = '<ul class="village-grid">' + ''.join(f'<li>{self.link(l)}</li>' for l in locs) + '</ul>'
        front = c.node(int(str(self._var('site_frontpage') or 'node/0').split('/')[1]))
        body = rich(front.get('body'), front.fmt.get('body')) if front and front.get('body') else ''
        content = (rich(self.blocks.get(11, ''), 'full_html') + grid + rich(self.blocks.get(10, ''), 'full_html')
                   + self.map_html(pts, 520, cls='map big') + body)
        self.write('', None, content, needs_map=True, page_class='front', show_title=False)
        if front:   # the front-page node also lives at its own alias (/introduction)
            self.write(front.alias, front.title, body, breadcrumb=[('/', 'Home'), (None, front.title)])

    def page_locations(self):
        locs = sorted([l for l in self.c.by_type['location'] if l.title.lower() != 'new location'], key=lambda n: ckey(n.title))
        pts = [p for p in (self.loc_point(l) for l in locs) if p]
        content = self.map_html(pts, 480, cls='map big') + '<ul class="plain cols">' + ''.join(
            f'<li>{self.link(l)}</li>' for l in locs) + '</ul>'
        self.write('locations', 'Locations', content, needs_map=True, breadcrumb=[('/', 'Home'), (None, 'Locations')])

    def view_area(self, view, display, key='header'):
        """Header/empty text configured on a Drupal view display (falls back to the default display)."""
        for dn in (display, 'default'):
            r = self.c.db.execute("select d.display_options from views_view v join views_display d on d.vid=v.vid "
                                  "where v.name=? and d.id=?", (view, dn)).fetchone()
            if not r:
                continue
            x = _php(r[0]) or {}
            if key in x:
                parts = [v.get('content', '') for v in (x[key] or {}).values() if isinstance(v, dict)]
                return ''.join(rich(p, 'full_html') for p in parts if p)
        return ''

    def page_contents(self):
        """/status-texts: table of all texts (view status_texts, display page_1)."""
        c = self.c
        rows = []
        for t in sorted(c.by_type['text'], key=lambda t: ckey(t.title)):
            loc = c.location_of_text(t)
            dg = ', '.join(c.terms[x].name for x in (loc.all('dialect_group') if loc else []) if x in c.terms)
            rows.append('<tr>' + ''.join(f'<td{cl}>{x}</td>' for cl, x in [
                ('', self.link(t)), ('', esc(dg)), (' class="num"', esc(t.get('word_count', ''))),
                (' class="num"', esc(t.get('text_size', ''))), (' class="num"', esc(t.get('lines', ''))),
                ('', rich(t.get('synopsis'), t.fmt.get('synopsis')))]) + '</tr>')
        head = ['Text', 'Dialect Group', 'Tokens', 'Length', 'Lines', 'Synopsis of Thematic Content']
        content = (self.view_area('status_texts', 'page_1') +
                   '<div class="table-scroll"><table class="data sortable"><thead><tr>' +
                   ''.join(f'<th>{h}</th>' for h in head) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
        self.write('status-texts', 'Table of Contents', content, breadcrumb=[('/', 'Home'), (None, 'Contents')])

    # ------------------------------------------------------------------ old URLs
    def legacy_urls(self):
        """Keep old links working:
          * secondary aliases (a node with two aliases) get a small redirect page
          * /node/123 and /taxonomy/term/45 are resolved by the 404 page through a lookup table"""
        c = self.c
        from cleanup import fold
        primary = {fold(n.alias) for n in c.nodes.values() if n.status} | {fold(t.alias) for t in c.terms.values()}
        n_stub = 0
        for r in c.db.execute('select source, alias from url_alias'):
            src, alias = r['source'], r['alias']
            if fold(alias) in primary or not src.startswith(('node/', 'taxonomy/term/')) or src.count('/') != 1 + src.startswith('taxonomy'):
                continue
            if src.startswith('node/') and not c.node(int(src.split('/')[1])):
                continue
            target = c.alias_of.get(src)
            if not target or target == alias:
                continue
            self._redirect_stub(alias, url_path(target)); n_stub += 1
        table = {}
        for n in c.nodes.values():
            if n.status and not n.alias.startswith('node/'):
                table['node/' + str(n.nid)] = n.alias
        for t in c.terms.values():
            if not t.alias.startswith('taxonomy/'):
                table['taxonomy/term/' + str(t.tid)] = t.alias
        os.makedirs(os.path.join(self.out, 'assets', 'data'), exist_ok=True)
        with open(os.path.join(self.out, 'assets', 'data', 'legacy.json'), 'w', encoding='utf-8') as f:
            json.dump(table, f, ensure_ascii=False, separators=(',', ':'))
        notfound = ('<p>Sorry, that page could not be found.</p><p id="moved" hidden>This page has moved: '
                    '<a href="#">continue</a>.</p>'
                    '<script>(function(){var m=/^\\/((?:node|taxonomy\\/term)\\/\\d+)/.exec(location.pathname);'
                    'if(!m)return;fetch("/assets/data/legacy.json").then(function(r){return r.json()}).then(function(t){'
                    'var a=t[m[1]];if(a){location.replace("/"+a.split("/").map(encodeURIComponent).join("/")+location.search+location.hash);}})})();</script>')
        self.write('__404', 'Page not found', notfound)
        shutil.move(os.path.join(self.out, '__404', 'index.html'), os.path.join(self.out, '404.html'))
        os.rmdir(os.path.join(self.out, '__404'))
        self.written += n_stub

    def _redirect_stub(self, alias, target):
        path = os.path.join(self.out, alias.strip('/'), 'index.html')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'<!doctype html><meta charset="utf-8"><title>Moved</title><link rel="canonical" href="{esc(target)}">'
                    f'<meta http-equiv="refresh" content="0; url={esc(target)}"><a href="{esc(target)}">This page has moved.</a>')

    # ------------------------------------------------------------------ archival dataset
    def dataset(self):
        """Plain CSV copy of the whole corpus (also suitable for an archival deposit)."""
        import csv, io, zipfile
        c = self.c
        out_dir = os.path.join(self.out, 'data')
        os.makedirs(out_dir, exist_ok=True)
        lab = lambda f, vals: '; '.join(str(c.label(f, v)) for v in vals)
        ref = lambda nid: (c.node(nid).title if c.node(nid) else '')
        terms = lambda tids: '; '.join(c.terms[t].name for t in tids if t in c.terms)
        tables = {
            'locations': (['nid', 'title', 'url', 'latitude', 'longitude', 'region', 'date_visited', 'dialect_group'],
                          [[n.nid, n.title, url_path(n.alias), *(n.get('coordinates') or ('', '')), n.get('region', ''),
                            n.get('date_visited', ''), terms(n.all('dialect_group'))] for n in c.by_type['location']]),
            'texts': (['nid', 'title', 'url', 'location', 'text_number', 'date_of_recording', 'length', 'word_count',
                       'lines', 'audio_file', 'recording_team', 'synopsis'],
                      [[n.nid, n.title, url_path(n.alias), ref(n.get('location_reference')), n.get('text_number', ''),
                        n.get('date_of_recording', ''), n.get('text_size', ''), n.get('word_count', ''), n.get('lines', ''),
                        os.path.basename(c.file_url(n.get('audio')) or ''), n.get('recording_team', ''), n.get('synopsis', '')]
                       for n in c.by_type['text']]),
            'informants': (['nid', 'title', 'informant_id', 'location', 'investigator', 'gender', 'age'],
                           [[n.nid, n.title, n.get('informant_id', ''), ref(n.get('location_reference')),
                             n.get('investigator', ''), n.get('gender', ''), n.get('age', '')] for n in c.by_type['informant']]),
            'lines': (['nid', 'title', 'url', 'text', 'line_number', 'speaker', 'timecode', 'full_line', 'cyrillic_full_line',
                       'translation', 'token_nids', 'thematic_content', 'discourse_elements', 'narrative_structure', 'note'],
                      [[n.nid, n.title, url_path(n.alias), ref(n.get('text_reference')), n.get('line_number', ''),
                        c.speaker(n), n.get('timecode', ''), n.get('full_line', ''), n.get('cyrillic_full_line', ''),
                        n.get('translation', ''), ' '.join(map(str, n.all('token_reference'))), terms(n.all('thematic_content')),
                        terms(n.all('discourse_elements')), terms(n.all('narrative_structure')), n.get('note', '')]
                       for n in c.by_type['line']]),
            'tokens': (['nid', 'token', 'url', 'meaning', 'lexeme_nid', 'lexeme'] + search.GRAM + ['linguistic_trait_nids', 'note'],
                       [[n.nid, n.title, url_path(n.alias), n.get('meaning', ''), n.get('lexeme', ''), ref(n.get('lexeme'))] +
                        [lab(f, n.all(f)) for f in search.GRAM] + [' '.join(map(str, n.all('ling_trait_ref'))), n.get('note', '')]
                        for n in c.by_type['token']]),
            'lexemes': (['nid', 'lexeme', 'url', 'lexical_traits', 'note'],
                        [[n.nid, n.title, url_path(n.alias), terms(n.all('lexical_traits')), n.get('note', '')]
                         for n in c.by_type['lexeme']]),
            'linguistic_traits': (['nid', 'title', 'traits'],
                                  [[n.nid, n.title, terms(n.all('ling_trait'))] for n in c.by_type['linguistic_trait']]),
            'phrases': (['nid', 'phrase', 'url', 'line_nid', 'line', 'cyrillic_phrase', 'token_nids'] + search.PHRASE,
                        [[n.nid, n.title, url_path(n.alias), n.get('line', ''), ref(n.get('line')), n.get('cyrillic_phrase', ''),
                          ' '.join(map(str, n.all('token_reference')))] + [lab(f, n.all(f)) for f in search.PHRASE]
                         for n in c.by_type['phrase']]),
            'terms': (['tid', 'vocabulary', 'name', 'parent_tid'],
                      [[t.tid, c.vocabs[t.vid]['name'], t.name, t.parents[0] if t.parents else ''] for t in c.terms.values()]),
        }
        zpath = os.path.join(out_dir, 'bdlt-corpus-csv.zip')
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, (head, rows) in tables.items():
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(head); w.writerows(rows)
                z.writestr(f'{name}.csv', '\ufeff' + buf.getvalue())
        items = ''.join(f'<li><b>{n}.csv</b> — {len(r):,} rows</li>' for n, (h, r) in tables.items())
        self.write('data', 'Download the data',
                   '<p>The complete corpus as plain CSV files (UTF-8), one file per kind of record. '
                   'Records cross-reference each other by their <code>nid</code> (node ID).</p>'
                   f'<p><a class="btn" href="/data/bdlt-corpus-csv.zip">Download bdlt-corpus-csv.zip</a> '
                   f'({os.path.getsize(zpath) / 1e6:.1f} MB)</p><ul>{items}</ul>',
                   breadcrumb=[('/', 'Home'), (None, 'Data')])

    # ------------------------------------------------------------------ assets + driver
    def copy_assets(self):
        dst = os.path.join(self.out, 'assets')
        os.makedirs(dst, exist_ok=True)
        with open(os.path.join(self.out, 'robots.txt'), 'w') as f:
            f.write('User-agent: *\nDisallow: /\n' if STAGING else
                    'User-agent: *\nDisallow: /assets/data/\n')
        open(os.path.join(self.out, '.nojekyll'), 'w').close()
        with open(os.path.join(dst, 'collation.js'), 'w', encoding='utf-8') as f:
            f.write(collate_js())   # tell GitHub Pages not to run Jekyll
        if PAGES_DOMAIN:
            with open(os.path.join(self.out, 'CNAME'), 'w') as f:
                f.write(PAGES_DOMAIN + '\n')
        for f in os.listdir(os.path.join(HERE, 'static')):
            shutil.copy2(os.path.join(HERE, 'static', f), dst)
        if self.header_imgs:
            shutil.copytree(self.header_dir, os.path.join(dst, 'headerimg'), dirs_exist_ok=True)
        if self.files_dir and os.path.isdir(self.files_dir):
            # public files keep their old URLs (/sites/default/files/...) so existing links keep working
            shutil.copytree(self.files_dir, os.path.join(self.out, 'sites/default/files'), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('audio', '.htaccess', 'css', 'js', 'styles', 'ctools',
                                                          'languages', '*.log', 'imports',
                                                          *self.c.skip_files))

    def run(self):
        only = set(self.args.only.split(',')) if self.args.only else None
        lim = self.args.limit
        self.copy_assets()
        jobs = [
            ('front', lambda: (self.page_front(), self.page_locations(), self.page_contents())),
            ('text', lambda: [self.page_text(n) for n in self.c.by_type['text'][:lim]]),
            ('location', lambda: [self.page_location(n) for n in self.c.by_type['location'][:lim]]),
            ('line', lambda: [self.page_line(n) for n in self.c.by_type['line'][:lim]]),
            ('token', lambda: [self.page_token(n) for n in self.c.by_type['token'][:lim]]),
            ('lexeme', lambda: [self.page_lexeme(n) for n in self.c.by_type['lexeme'][:lim]]),
            ('other', lambda: [self.page_generic(n) for t in ('phrase', 'informant', 'linguistic_trait', 'page', 'news')
                               for n in self.c.by_type[t][:lim]]),
            ('term', lambda: [self.page_term(t) for t in list(self.c.terms.values())[:lim]]),
            ('search', lambda: search.pages(self, search.export(self))),
            ('legacy', lambda: self.legacy_urls()),
            ('dataset', lambda: self.dataset()),
        ]
        for name, fn in jobs:
            if only and name not in only:
                continue
            t0, w0 = time.time(), self.written
            fn()
            print(f'{name:10s} {self.written - w0:6d} pages  {time.time() - t0:5.1f}s')
        print('total pages', self.written)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('raw'); ap.add_argument('files'); ap.add_argument('headers'); ap.add_argument('out')
    ap.add_argument('--only'); ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    Site(a.raw, a.files, a.headers, a.out, a).run()
