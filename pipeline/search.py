"""Search data (JSON) + the five search pages and the All Tokens browser.

The old site ran these as Drupal Views queries on every request. Here the corpus is
exported once as compact JSON and the same filters run in the browser (assets/search.js)."""
import json, os

from render import esc, rich

GRAM = ['case', 'number', 'gram_gender', 'definiteness', 'person', 'tense', 'aspect', 'particle', 'clitic',
        'deictic', 'other', 'pragmatic']
GRAM_LABELS = {'case': 'Case', 'number': 'Number', 'gram_gender': 'Gender', 'definiteness': 'Definiteness',
               'person': 'Person', 'tense': 'Verb-form', 'aspect': 'Aspect', 'particle': 'Particle',
               'clitic': 'Clitic', 'deictic': 'Deictic', 'other': 'Other', 'pragmatic': 'Pragmatic'}
PHRASE = ['tense_mood', 'evidential', 'reflexive', 'clitic_objects', 'doubled_phrase', 'negation', 'word_order',
          'syntactic_cohesion', 'category_shift', 'accentuation', 'interrogative', 'verbal_phrase', 'style',
          'miscellaneous']
PHRASE_LABELS = {'tense_mood': 'Tense-mood', 'evidential': 'Evidential', 'reflexive': 'Reflexive',
                 'clitic_objects': 'Clitic objects', 'doubled_phrase': 'Doubled phrase', 'negation': 'Negation',
                 'word_order': 'Word order', 'syntactic_cohesion': 'Syntactic cohesion',
                 'category_shift': 'Category shift', 'accentuation': 'Accentuation', 'interrogative': 'Interrogative',
                 'verbal_phrase': 'Verbal phrase', 'style': 'Style', 'miscellaneous': 'Miscellaneous'}
ACCENT_SHIFT_NODES = [43193, 43192]   # options of the wordform search's "Accent shift types" filter


def export(site):
    c, url = site.c, None
    from build import url_path
    out = os.path.join(site.out, 'assets', 'data')
    os.makedirs(out, exist_ok=True)

    investigators = {n.nid for n in c.by_type['informant'] if n.get('investigator')}
    locs = {n.nid: [n.title, url_path(n.alias)] + (list(n.get('coordinates')) if n.get('coordinates') else [None, None])
            for n in c.by_type['location']}
    texts = {n.nid: [n.title, url_path(n.alias), n.get('location_reference')] for n in c.by_type['text']}
    lines = {}
    for l in c.by_type['line']:
        lines[l.nid] = [l.get('text_reference'), l.get('line_number'), url_path(l.alias), l.title,
                        l.get('full_line', ''), l.get('translation', ''),
                        1 if l.get('informant_reference') in investigators else 0, l.all('token_reference')]
    tokens = {}
    for t in c.by_type['token']:
        g = {f: t.all(f) for f in GRAM if t.all(f)}
        sem = c.node(t.get('semantics'))
        tokens[t.nid] = [t.title, url_path(t.alias), t.get('meaning', ''), g, t.get('lexeme'), t.all('ling_trait_ref'),
                         sem.title if sem else '']
    # [title, url, lexical trait tids, 1 = real lexeme record (0 = placeholder node some tokens point at)]
    lexemes = {n.nid: [n.title.strip(), url_path(n.alias), n.all('lexical_traits'), 1] for n in c.by_type['lexeme']}
    # tokens whose lexeme reference points at a non-lexeme node (e.g. the "." placeholder) still need a label
    for t in c.by_type['token']:
        lx = t.get('lexeme')
        if lx and lx not in lexemes and c.node(lx):
            n = c.node(lx)
            lexemes[lx] = [n.title, url_path(n.alias), [], 0]
    traits = {n.nid: n.all('ling_trait') for n in c.by_type['linguistic_trait']}
    v1 = c.vocab_by_machine['vocabulary_1']
    trait_terms = {t.tid: [t.name, t.parents[0] if t.parents else 0, t.weight]
                   for t in c.terms.values() if t.vid == v1}
    phrases = {}
    for p in c.by_type['phrase']:
        tags = {f: p.all(f) for f in PHRASE if p.all(f)}
        phrases[p.nid] = [p.title, url_path(p.alias), p.get('line'), tags]
    lex_traits = [[t.tid, t.name] for t in sorted(
        (t for t in c.terms.values() if t.vid == c.vocab_by_machine['lexical_traits']), key=lambda t: (t.weight, t.name))]

    def dump(name, obj):
        with open(os.path.join(out, name), 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    dump('core.json', {'locs': locs, 'texts': texts, 'lines': lines})
    lex_trait_names = {t.tid: [t.name, url_path(t.alias)] for t in c.terms.values()
                       if t.vid == c.vocab_by_machine['lexical_traits']}
    dump('tokens.json', {'tokens': tokens, 'lexemes': lexemes, 'lexTraits': lex_trait_names})
    dump('traits.json', {'traits': traits, 'terms': trait_terms})
    dump('phrases.json', {'phrases': phrases})
    allowed = {f: list(c.allowed.get(f, {}).items()) for f in GRAM + PHRASE}
    return {'allowed': allowed, 'lex_traits': lex_traits}


def multi_select(name, label, options, with_op=True):
    ops = ('<select name="{0}_op" aria-label="{1} operator"><option value="or">Is one of</option>'
           '<option value="and">Is all of</option><option value="not">Is none of</option>'
           '<option value="empty">Is empty (NULL)</option><option value="not empty">Is not empty (NOT NULL)</option>'
           '</select>').format(name, esc(label)) if with_op else ''
    opts = ''.join(f'<option value="{esc(k)}">{v}</option>' for k, v in options)
    size = max(2, min(len(options), 22))     # tall enough to show every option without scrolling
    return (f'<div><label>{esc(label)}</label>{ops}<select name="{name}[]" multiple size="{size}">{opts}</select>'
            '<div class="hint">Ctrl/⌘-click to pick several</div></div>')


def single_select(name, label, options):
    opts = '<option value="">- Any -</option>' + ''.join(f'<option value="{esc(k)}">{v}</option>' for k, v in options)
    return f'<div><label>{esc(label)}</label><select name="{name}">{opts}</select></div>'


def text_input(name, label, op_select=False, default_op='='):
    ops = ''
    if op_select:
        ops = (f'<select name="{name}_op" aria-label="{esc(label)} operator">' + ''.join(
            f'<option value="{v}"{" selected" if v == default_op else ""}>{l}</option>' for v, l in STRING_OPS) + '</select>')
    return f'<div><label>{esc(label)}</label>{ops}<input type="text" name="{name}"></div>'


STRING_OPS = [('=', 'Is equal to'), ('!=', 'Is not equal to'), ('contains', 'Contains'),
              ('word', 'Contains any word'), ('allwords', 'Contains all words'), ('starts', 'Starts with'),
              ('not_starts', 'Does not start with'), ('ends', 'Ends with'), ('not_ends', 'Does not end with'),
              ('not', 'Does not contain'), ('shorterthan', 'Length is shorter than'),
              ('longerthan', 'Length is longer than'), ('empty', 'Is empty (NULL)'),
              ('not empty', 'Is not empty (NOT NULL)'), ('regular_expression', 'Regular expression'),
              ('not_regular_expression', 'Not regular expression')]


def form(fields, kind, note=''):
    return (f'<form class="search-form" data-search="{kind}" method="get">{note}<fieldset>{"".join(fields)}</fieldset>'
            '<div class="search-actions"><button class="btn" type="submit">Apply</button>'
            '<button class="btn secondary" type="reset">Reset</button>'
            '<span class="result-count" aria-live="polite"></span>'
            '<span class="exports" hidden><button class="btn secondary" type="button" data-export="csv">Download CSV</button> '
            '<button class="btn secondary" type="button" data-export="doc">Download Word (.doc)</button></span></div></form>'
            '<div class="results-map leaflet-host" hidden></div><div class="results" aria-live="polite"></div>')


def pages(site, meta):
    c = site.c
    allowed = meta['allowed']
    js = '<script src="/assets/search.js?v=' + site.build_id + '"></script>'

    # Wordform search ---------------------------------------------------------
    f = [text_input('title', 'Lexeme Contains'), text_input('field_meaning_value', 'English Translation')]
    for g in GRAM:
        opts = allowed[g]
        if g == 'definiteness':
            f.append(multi_select(f'field_{g}_value', GRAM_LABELS[g], opts))
        else:
            f.append(multi_select(f'field_{g}_value', GRAM_LABELS[g], opts))
    f.append(text_input('title_1', 'Ending'))
    f.append(single_select('field_ling_trait_ref_nid', 'Accent shift types',
                           [(n, c.nodes[n].title) for n in ACCENT_SHIFT_NODES if n in c.nodes]))
    site.write('wordform-search', 'Wordform Search', form(f, 'wordform'), needs_map=True, scripts=js,
               breadcrumb=[('/', 'Home'), (None, 'Wordform Search')], page_class='search')

    # Lexeme search -----------------------------------------------------------
    f = [text_input('title', 'Lexeme search', True, 'starts'), text_input('field_meaning_value', 'English Gloss', True),
         multi_select('field_lexical_traits_tid', 'Lexical Traits', [(str(t), n) for t, n in meta['lex_traits']], False),
         text_input('title_1', 'Lexical variation')]
    note = site.view_area('tokens_by_lexeme', 'page_1')
    site.write('lexemes', 'Lexeme Search', form(f, 'lexeme', note), scripts=js,
               breadcrumb=[('/', 'Home'), (None, 'Lexeme Search')], page_class='search')

    # Linguistic trait search -------------------------------------------------
    labels = ['Linguistic Trait'] + ['Additional Trait'] * 4
    f = [f'<div class="shs" data-name="field_ling_trait_tid{"" if i == 0 else "_" + str(i)}">'
         f'<label>{labels[i]}</label><input type="hidden" name="field_ling_trait_tid{"" if i == 0 else "_" + str(i)}"></div>'
         for i in range(5)]
    note = site.view_area('map2', 'page_1')
    site.write('mapdev', 'Linguistic Trait Search', form(f, 'trait', f'<div class="search-note">{note}</div>'),
               needs_map=True, scripts=js, breadcrumb=[('/', 'Home'), (None, 'Linguistic Trait Search')],
               page_class='search trait-search')

    # Phrase search -----------------------------------------------------------
    f = [single_select(f'field_{p}_value', PHRASE_LABELS[p], allowed[p]) for p in PHRASE]
    note = site.view_area('phrase_search', 'page')
    site.write('phrase-search', 'Phrase Search', form(f, 'phrase', f'<div class="search-note">{note}</div>'),
               needs_map=True, scripts=js, breadcrumb=[('/', 'Home'), (None, 'Phrase Search')], page_class='search')

    # All tokens --------------------------------------------------------------
    f = [text_input('title', 'Token begins with', True, 'starts')]
    site.write('all_tokens_user', 'All Tokens', form(f, 'alltokens'), scripts=js,
               breadcrumb=[('/', 'Home'), (None, 'All Tokens')], page_class='search')

    # All lexemes (the old site's /all_lexemes view, without its editors-only Edit column) ----------
    f = [text_input('title', 'Search for a lexeme which', True, 'contains')]
    site.write('all_lexemes', 'All Lexemes', form(f, 'alllexemes'), scripts=js,
               breadcrumb=[('/', 'Home'), (None, 'All Lexemes')], page_class='search')

    # Thematic content: hierarchical list of terms, each linking to its passages
    v9 = c.vocab_by_machine['vocabulary_9']
    roots = sorted((t for t in c.terms.values() if t.vid == v9 and not t.parents), key=lambda t: (t.weight, t.name.lower()))

    def tree(ts):
        return '<ul>' + ''.join(
            f'<li>{site.link(t)}' + (tree([c.terms[x] for x in t.children]) if t.children else '') + '</li>'
            for t in ts) + '</ul>'
    note = site.view_area('thematic_list', 'page')
    site.write('thematic-list', 'Browse Thematic Content', note + '<div class="term-tree">' + tree(roots) + '</div>',
               breadcrumb=[('/', 'Home'), (None, 'Thematic Content Search')])
    alpha = sorted((t for t in c.terms.values() if t.vid == v9), key=lambda t: t.name.lower())
    site.write('browse-thematic', 'Thematic Content (alphabetical)',
               '<ul class="plain cols">' + ''.join(f'<li>{site.link(t)}</li>' for t in alpha) + '</ul>',
               breadcrumb=[('/', 'Home'), ('/thematic-list', 'Thematic Content'), (None, 'Alphabetical')])
