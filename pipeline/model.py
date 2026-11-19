"""Load the raw Drupal tables (from extract.py) into plain Python objects.

Everything downstream (page generator, search indexes, archival export) works from
the Corpus object built here, so Drupal's storage quirks are handled in one place."""
import re, sqlite3
from collections import defaultdict
import phpserialize


class Node:
    __slots__ = ('nid', 'type', 'title', 'status', 'created', 'changed', 'f', 'fmt', 'alias')

    def __init__(self, nid, type_, title, status, created, changed):
        self.nid, self.type, self.title, self.status = nid, type_, title, status
        self.created, self.changed = created, changed
        self.fmt = {}      # field name -> text format of first value (for text fields)
        self.f = {}        # field name (without 'field_' prefix) -> list of values in delta order
        self.alias = None  # URL path without leading slash

    def get(self, name, default=None):
        v = self.f.get(name)
        return v[0] if v else default

    def all(self, name):
        return self.f.get(name, [])

    def __repr__(self):
        return f'<{self.type} {self.nid} {self.title!r}>'


class Term:
    __slots__ = ('tid', 'vid', 'name', 'description', 'weight', 'parents', 'children', 'alias')

    def __init__(self, tid, vid, name, description, weight):
        self.tid, self.vid, self.name, self.description, self.weight = tid, vid, name, description, weight
        self.parents, self.children, self.alias = [], [], None


def _php(data):
    if data is None:
        return None
    if isinstance(data, str):
        data = data.encode('utf-8', 'surrogateescape')
    return phpserialize.loads(data, decode_strings=True)


class Corpus:
    def __init__(self, raw_path, cleanup_report=None, clean=True):
        db = sqlite3.connect(raw_path)
        db.row_factory = sqlite3.Row
        self.db = db
        self._load_fields_config()
        self._load_nodes()
        self._load_terms()
        self._load_files()
        self._load_aliases()
        self.skip_files = set()
        self.cleanup = []
        if clean:
            import cleanup
            self.cleanup = cleanup.apply(self, cleanup_report)
        self._index()

    # ---------------------------------------------------------------- loading
    def _load_fields_config(self):
        self.allowed = {}      # field -> {key: label}
        self.field_type = {}
        for r in self.db.execute('select field_name, type, data from field_config where deleted=0'):
            name = r['field_name'].removeprefix('field_')
            self.field_type[name] = r['type']
            if r['type'].startswith('list_'):
                av = _php(r['data'])['settings'].get('allowed_values', {})
                self.allowed[name] = {str(k): str(v) for k, v in av.items()}
        self.labels = defaultdict(dict)   # bundle -> field -> label
        for r in self.db.execute("select field_name, bundle, data from field_config_instance "
                                 "where deleted=0 and entity_type='node'"):
            self.labels[r['bundle']][r['field_name'].removeprefix('field_')] = _php(r['data']).get('label')

    def _load_nodes(self):
        self.nodes = {}
        for r in self.db.execute('select nid, type, title, status, created, changed from node'):
            self.nodes[r['nid']] = Node(r['nid'], r['type'], r['title'], r['status'], r['created'], r['changed'])
        tables = [r[0] for r in self.db.execute(
            "select name from sqlite_master where type='table' and name like 'field_data_%'")]
        for t in tables:
            fname = t.removeprefix('field_data_')
            short = fname.removeprefix('field_')
            cols = [c[1] for c in self.db.execute(f'pragma table_info("{t}")')]
            if fname + '_lat' in cols:          # geofield
                sel = f'{fname}_lat, {fname}_lon'
            else:
                main = next((c for c in cols if c in (f'{fname}_value', f'{fname}_nid', f'{fname}_tid',
                                                       f'{fname}_fid', f'{fname}_uid')), None)
                if main is None:
                    continue
                sel = main
                if f'{fname}_format' in cols:
                    sel += f', {fname}_format'
            geo = fname + '_lat' in cols
            for r in self.db.execute(f'select entity_id, delta, {sel} from "{t}" '
                                     f"where entity_type='node' and deleted=0 order by entity_id, delta"):
                n = self.nodes.get(r[0])
                if n is None:
                    continue
                v = (r[2], r[3]) if geo else r[2]
                if v is None:
                    continue
                if not geo and len(r) == 4 and short not in n.fmt:
                    n.fmt[short] = r[3]
                n.f.setdefault(short, []).append(v)

    def _load_terms(self):
        self.vocabs = {r['vid']: dict(r) for r in self.db.execute('select * from taxonomy_vocabulary')}
        self.vocab_by_machine = {v['machine_name']: vid for vid, v in self.vocabs.items()}
        self.terms = {}
        for r in self.db.execute('select tid, vid, name, description, weight from taxonomy_term_data'):
            self.terms[r['tid']] = Term(r['tid'], r['vid'], r['name'], r['description'], r['weight'])
        for r in self.db.execute('select tid, parent from taxonomy_term_hierarchy'):
            t = self.terms.get(r['tid'])
            if not t:
                continue
            if r['parent'] and r['parent'] in self.terms:
                t.parents.append(r['parent'])
                self.terms[r['parent']].children.append(r['tid'])
        for t in self.terms.values():
            t.children.sort(key=lambda c: (self.terms[c].weight, self.terms[c].name.lower()))

    def _load_files(self):
        self.files = {r['fid']: dict(r) for r in self.db.execute('select fid, filename, uri, filemime, filesize from file_managed')}

    def _load_aliases(self):
        self.alias_of = {}
        for r in self.db.execute('select source, alias from url_alias order by pid'):
            self.alias_of[r['source']] = r['alias']          # latest wins (Drupal uses highest pid)
        for n in self.nodes.values():
            n.alias = self.alias_of.get(f'node/{n.nid}', f'node/{n.nid}')
        for t in self.terms.values():
            t.alias = self.alias_of.get(f'taxonomy/term/{t.tid}', f'taxonomy/term/{t.tid}')

    # ---------------------------------------------------------------- indexes
    def _index(self):
        self.by_type = defaultdict(list)
        for n in self.nodes.values():
            if n.status:
                self.by_type[n.type].append(n)
        # reverse references
        self.lines_of_text = defaultdict(list)
        self.texts_of_location = defaultdict(list)
        self.informants_of_location = defaultdict(list)
        self.lines_of_token = defaultdict(list)       # token nid -> [line, ...] (one entry per occurrence)
        self.tokens_of_lexeme = defaultdict(list)
        self.tokens_of_trait = defaultdict(list)      # linguistic_trait node -> tokens
        self.phrases_of_line = defaultdict(list)
        self.lines_of_term = defaultdict(list)
        for n in self.by_type['line']:
            t = n.get('text_reference')
            if t:
                self.lines_of_text[t].append(n)
            for tok in n.all('token_reference'):
                self.lines_of_token[tok].append(n)
            for fld in ('thematic_content', 'discourse_elements', 'narrative_structure'):
                for tid in n.all(fld):
                    self.lines_of_term[tid].append(n)
        for lst in self.lines_of_text.values():
            lst.sort(key=lambda l: (l.get('line_number') or 0, l.nid))
        for n in self.by_type['text']:
            loc = n.get('location_reference')
            if loc:
                self.texts_of_location[loc].append(n)
        for lst in self.texts_of_location.values():
            lst.sort(key=lambda t: (t.get('text_number') or 0, t.title))
        for n in self.by_type['informant']:
            loc = n.get('location_reference')
            if loc:
                self.informants_of_location[loc].append(n)
        for n in self.by_type['token']:
            for lx in n.all('lexeme'):
                self.tokens_of_lexeme[lx].append(n)
            for tr in n.all('ling_trait_ref'):
                self.tokens_of_trait[tr].append(n)
        for n in self.by_type['phrase']:
            for ln in n.all('line'):
                self.phrases_of_line[ln].append(n)

    # ---------------------------------------------------------------- helpers
    def node(self, nid):
        n = self.nodes.get(nid)
        return n if n is not None and n.status else None

    def url(self, obj):
        return '/' + obj.alias

    def label(self, field, key):
        return self.allowed.get(field, {}).get(str(key), key)

    def text_of_line(self, line):
        return self.node(line.get('text_reference'))

    def location_of_text(self, text):
        return self.node(text.get('location_reference')) if text else None

    def speaker(self, line):
        inf = self.node(line.get('informant_reference'))
        return inf.get('informant_id', '') if inf else ''

    def file_url(self, fid):
        f = self.files.get(fid)
        if not f:
            return None
        return '/' + re.sub(r'^public://', 'sites/default/files/', f['uri'])
