/* Client-side versions of the site's Drupal Views searches.
 * Query-string parameter names match the old site, so bookmarked search URLs keep working. */
(function () {
  'use strict';
  var form = document.querySelector('form[data-search]');
  if (!form) return;
  var KIND = form.dataset.search;
  var resultsEl = document.querySelector('.results');
  var mapEl = document.querySelector('.results-map');
  var countEl = form.querySelector('.result-count');
  var exportsEl = form.querySelector('.exports');
  var PAGE = KIND === 'alltokens' ? 100 : 200;
  var D = {};           // loaded data
  var current = null;   // {rows, columns(row)->[], groups}

  // ---------------------------------------------------------------- utilities
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  // MySQL's utf8_general_ci comparisons ignore case and accents; do the same.
  function norm(s) {
    return String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  }
  function load(names) {
    return Promise.all(names.map(function (n) {
      if (D[n]) return D[n];
      D[n] = fetch('/assets/data/' + n + '.json').then(function (r) {
        if (!r.ok) throw new Error('Could not load ' + n);
        return r.json();
      }).then(function (j) { Object.assign(D, j); return j; });
      return D[n];
    }));
  }
  // alphabetical order of the site's transcription (assets/collation.js); keys cached because lists are long
  var keyCache = {};
  function ck(s) { s = s || ''; var k = keyCache[s]; if (k === undefined) k = keyCache[s] = (window.BDLT && BDLT.collateKey) ? BDLT.collateKey(s) : String(s).toLowerCase(); return k; }
  function cmp(a, b) { a = ck(a); b = ck(b); return a < b ? -1 : a > b ? 1 : 0; }
  function link(url, label) { return '<a href="' + esc(url) + '">' + esc(label) + '</a>'; }

  // Views string operators
  function strMatch(op, value, needle) {
    var v = norm(value), n = norm(needle);
    switch (op || 'contains') {
      case '=': return v === n;
      case '!=': return v !== n;
      case 'contains': return v.indexOf(n) >= 0;
      case 'not': return v.indexOf(n) < 0;
      case 'starts': return v.indexOf(n) === 0;
      case 'not_starts': return v.indexOf(n) !== 0;
      case 'ends': return n === '' || v.slice(-n.length) === n;
      case 'not_ends': return !(n === '' || v.slice(-n.length) === n);
      case 'word': return n.split(/\s+/).some(function (w) { return w && new RegExp('(^|[^\\p{L}])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|[^\\p{L}])', 'u').test(v); });
      case 'allwords': return n.split(/\s+/).every(function (w) { return !w || new RegExp('(^|[^\\p{L}])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|[^\\p{L}])', 'u').test(v); });
      case 'shorterthan': return [...String(value || '')].length < parseInt(needle, 10);
      case 'longerthan': return [...String(value || '')].length > parseInt(needle, 10);
      case 'empty': return !value;
      case 'not empty': return !!value;
      case 'regular_expression': try { return new RegExp(needle, 'iu').test(value || ''); } catch (e) { return false; }
      case 'not_regular_expression': try { return !new RegExp(needle, 'iu').test(value || ''); } catch (e) { return true; }
    }
    return true;
  }
  // Views many-to-one operators on a multi-valued list field
  function listMatch(op, have, wanted) {
    have = have || [];
    switch (op || 'or') {
      case 'empty': return have.length === 0;
      case 'not empty': return have.length > 0;
      case 'and': return wanted.every(function (w) { return have.indexOf(w) >= 0; });
      case 'not': return !wanted.some(function (w) { return have.indexOf(w) >= 0; });
      default: return wanted.some(function (w) { return have.indexOf(w) >= 0; });
    }
  }

  // ---------------------------------------------------------------- query string <-> form
  function readParams() {
    var p = {}, q = new URLSearchParams(location.search);
    q.forEach(function (v, k) {
      var m = /^(.*?)\[\d*\]$/.exec(k);           // field[] and field[0] forms
      if (m) { (p[m[1]] = p[m[1]] || []).push(v); }
      else p[k] = v;
    });
    return p;
  }
  function fillForm(p) {
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      var key = el.name.replace(/\[\]$/, '');
      if (!(key in p)) return;
      var v = p[key];
      if (el.multiple) Array.prototype.forEach.call(el.options, function (o) { o.selected = [].concat(v).indexOf(o.value) >= 0; });
      else el.value = [].concat(v)[0];
    });
  }
  function formParams() {
    var p = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.type === 'submit' || el.type === 'button') return;
      var key = el.name.replace(/\[\]$/, '');
      if (el.multiple) {
        var vals = Array.prototype.filter.call(el.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
        if (vals.length) p[key] = vals;
      } else if (el.value !== '') p[key] = el.value;
    });
    return p;
  }
  function toQuery(p) {
    var q = new URLSearchParams();
    Object.keys(p).forEach(function (k) {
      if (Array.isArray(p[k])) p[k].forEach(function (v) { q.append(k + '[]', v); });
      else q.append(k, p[k]);
    });
    return q.toString();
  }
  // which parameters are real criteria (operator selects alone don't count, except empty/not empty)
  function hasCriteria(p) {
    return Object.keys(p).some(function (k) {
      if (k === 'page') return false;
      if (/_op$/.test(k)) return p[k] === 'empty' || p[k] === 'not empty';
      return true;
    });
  }

  // ---------------------------------------------------------------- shared pieces
  var GRAM = ['case', 'number', 'gram_gender', 'definiteness', 'person', 'tense', 'aspect', 'particle', 'clitic', 'deictic', 'other', 'pragmatic'];
  var GLOSS_ORDER = ['case', 'number', 'gram_gender', 'definiteness', 'person', 'tense', 'aspect', 'particle', 'deictic', 'clitic', 'other', 'pragmatic'];
  function gloss(tok) {
    var bits = [tok[2]];
    GLOSS_ORDER.forEach(function (f) { if (tok[3][f]) bits.push(tok[3][f].join(', ')); });
    return bits.filter(Boolean).join(' ');
  }
  function textOf(line) { return D.texts[line[0]]; }
  function locOf(line) { var t = textOf(line); return t && D.locs[t[2]]; }

  function drawResultsMap(rows, locIdOfRow) {
    if (!mapEl || !window.L) return;
    var by = {};
    rows.forEach(function (r) {
      var id = locIdOfRow(r);
      if (!id || !D.locs[id] || D.locs[id][2] == null) return;
      (by[id] = by[id] || []).push(r);
    });
    var pts = Object.keys(by).map(function (id) {
      var L_ = D.locs[id];
      return [L_[2], L_[3], '<b>' + link(L_[1], L_[0]) + '</b><br>' + by[id].length + ' result' + (by[id].length === 1 ? '' : 's')];
    });
    mapEl.hidden = !pts.length;
    if (pts.length) { mapEl.style.height = '360px'; BDLT.drawMap(mapEl, pts); }
  }

  function pager(total, page, always) {
    var pages = Math.max(1, Math.ceil(total / PAGE));
    if (pages <= 1 && !always) return '';
    function a(p, label, cls) {
      if (p < 0 || p >= pages) return '<span class="pg disabled ' + (cls || '') + '">' + label + '</span>';
      return p === page ? '<span class="pg cur">' + label + '</span>' : '<a class="pg ' + (cls || '') + '" href="#" data-page="' + p + '">' + label + '</a>';
    }
    var h = '<nav class="pager" aria-label="Pages">' + a(page > 0 ? 0 : -1, '« First') + a(page - 1, '‹ Previous', 'wide');
    for (var i = Math.max(0, page - 3); i < Math.min(pages, page + 4); i++) h += a(i, String(i + 1));
    h += a(page + 1, 'Next ›', 'wide') + a(page < pages - 1 ? pages - 1 : -1, 'Last »');
    var first = page * PAGE + 1, last = Math.min(total, (page + 1) * PAGE);
    return h + '<span class="pg-info">Page ' + (page + 1) + ' of ' + pages + ' · showing ' + first.toLocaleString() + '–' + last.toLocaleString() + '</span></nav>';
  }

  // render rows grouped by a key, paginated
  function renderGrouped(rows, page, groupOf, item, wrapClass) {
    var slice = rows.slice(page * PAGE, (page + 1) * PAGE), h = '', last = null, open = false;
    slice.forEach(function (r) {
      var g = groupOf(r);
      if (g.key !== last) {
        if (open) h += '</div>';
        h += '<h3 class="group">' + g.html + '</h3><div class="' + (wrapClass || 'hits') + '">';
        open = true; last = g.key;
      }
      h += item(r);
    });
    if (open) h += '</div>';
    return pager(rows.length, page) + h + pager(rows.length, page);
  }

  // ---------------------------------------------------------------- searches
  var S = {};

  S.wordform = {
    data: ['core', 'tokens'],
    run: function (p) {
      var wantLex = p.title, wantMeaning = p.field_meaning_value, wantEnd = p.title_1, wantTrait = p.field_ling_trait_ref_nid;
      var gf = GRAM.filter(function (f) {
        var op = p['field_' + f + '_value_op'] || 'or';
        return (p['field_' + f + '_value'] && p['field_' + f + '_value'].length) || op === 'empty' || op === 'not empty';
      });
      var tokOk = {};
      Object.keys(D.tokens).forEach(function (id) {
        var t = D.tokens[id];
        if (wantMeaning && norm(t[2]) !== norm(wantMeaning)) return;
        if (wantEnd && !strMatch('ends', t[0], wantEnd)) return;
        if (wantLex) { var lx = D.lexemes[t[4]]; if (!lx || !strMatch('contains', lx[0], wantLex)) return; }
        if (wantTrait && t[5].indexOf(+wantTrait) < 0) return;
        for (var i = 0; i < gf.length; i++) {
          var f = gf[i];
          if (!listMatch(p['field_' + f + '_value_op'], t[3][f], [].concat(p['field_' + f + '_value'] || []))) return;
        }
        tokOk[id] = true;
      });
      var rows = [];
      Object.keys(D.lines).forEach(function (lid) {
        var l = D.lines[lid];
        if (l[6]) return;  // investigator's lines are excluded
        l[7].forEach(function (tid) { if (tokOk[tid]) rows.push([lid, tid]); });
      });
      rows.sort(function (a, b) {
        var la = D.lines[a[0]], lb = D.lines[b[0]];
        var ta = (textOf(la) || [''])[0], tb = (textOf(lb) || [''])[0];
        return cmp(ta, tb) || (la[1] - lb[1]);
      });
      return rows;
    },
    group: function (r) { var t = textOf(D.lines[r[0]]) || ['?', '#']; return { key: t[0], html: link(t[1], t[0]) }; },
    item: function (r) {
      var l = D.lines[r[0]], t = D.tokens[r[1]], lx = D.lexemes[t[4]], tx = textOf(l) || ['', '#'];
      return '<div class="hit"><div>Token: ' + link(t[1], t[0]) + ' <span class="g">' + esc(gloss(t)) + '</span> ' +
        (lx ? '<span class="lx">' + link(lx[1], lx[0]) + '</span>' : '') + '</div>' +
        '<div class="where">' + link(tx[1], tx[0]) + ' ' + link(l[2], 'Line ' + l[1]) + '</div>' +
        '<div class="fl">' + esc(l[4]) + '</div><div class="tr">' + esc(l[5]) + '</div></div>';
    },
    loc: function (r) { return (textOf(D.lines[r[0]]) || [])[2]; },
    csv: function (r) {
      var l = D.lines[r[0]], t = D.tokens[r[1]], lx = D.lexemes[t[4]] || [''], tx = textOf(l) || [''], lc = locOf(l) || [''];
      return { Location: lc[0], Text: tx[0], Line: l[1], Token: t[0], Gloss: gloss(t), Lexeme: lx[0], 'Full line': l[4], Translation: l[5] };
    }
  };

  S.lexeme = {
    data: ['core', 'tokens'],
    run: function (p) {
      var lexOk = {};
      Object.keys(D.lexemes).forEach(function (id) {
        var lx = D.lexemes[id];
        if (p.title || /empty/.test(p.title_op || '')) { if (!strMatch(p.title_op || 'starts', lx[0], p.title || '')) return; }
        if (p.field_lexical_traits_tid && p.field_lexical_traits_tid.length) {
          if (!p.field_lexical_traits_tid.some(function (t) { return lx[2].indexOf(+t) >= 0; })) return;
        }
        lexOk[id] = true;
      });
      // token -> texts it occurs in
      var textsOfTok = {};
      Object.keys(D.lines).forEach(function (lid) {
        var l = D.lines[lid];
        l[7].forEach(function (tid) { (textsOfTok[tid] = textsOfTok[tid] || {})[l[0]] = 1; });
      });
      var rows = [];
      Object.keys(D.tokens).forEach(function (tid) {
        var t = D.tokens[tid];
        if (!t[4] || !lexOk[t[4]]) return;
        if (p.field_meaning_value || /empty/.test(p.field_meaning_value_op || '')) {
          if (!strMatch(p.field_meaning_value_op || '=', t[2], p.field_meaning_value || '')) return;
        }
        if (p.title_1 && norm(t[6]) !== norm(p.title_1)) return;
        var txs = Object.keys(textsOfTok[tid] || {});
        if (!txs.length) txs = [''];
        txs.forEach(function (x) { rows.push([tid, x]); });
      });
      rows.sort(function (a, b) {
        var A = D.tokens[a[0]], B = D.tokens[b[0]];
        var la = (D.lexemes[A[4]] || [''])[0], lb = (D.lexemes[B[4]] || [''])[0];
        var ta = (D.texts[a[1]] || [''])[0], tb = (D.texts[b[1]] || [''])[0];
        return cmp(la, lb) || cmp(ta, tb) || cmp(A[0], B[0]);
      });
      return rows;
    },
    group: function (r) {
      var t = D.tokens[r[0]], lx = D.lexemes[t[4]], tx = D.texts[r[1]];
      return { key: t[4] + '/' + r[1], html: link(lx[1], lx[0]) + (tx ? ' <span class="sub">— ' + link(tx[1], tx[0]) + '</span>' : '') };
    },
    item: function (r) {
      var t = D.tokens[r[0]];
      return '<div class="hit compact">' + link(t[1], t[0]) + ' <span class="g">' + esc(gloss(t)) + '</span></div>';
    },
    loc: function (r) { var tx = D.texts[r[1]]; return tx && tx[2]; },
    csv: function (r) {
      var t = D.tokens[r[0]], lx = D.lexemes[t[4]] || [''], tx = D.texts[r[1]] || [''];
      return { Lexeme: lx[0], Text: tx[0], Token: t[0], Gloss: gloss(t), 'Lexical variation': t[6] };
    },
    wrap: 'hits grid'
  };

  S.trait = {
    data: ['core', 'tokens', 'traits'],
    run: function (p) {
      var want = ['field_ling_trait_tid', 'field_ling_trait_tid_1', 'field_ling_trait_tid_2', 'field_ling_trait_tid_3', 'field_ling_trait_tid_4']
        .map(function (k) { return p[k]; }).filter(Boolean).map(Number);
      if (!want.length) return [];
      var traitOk = {};
      Object.keys(D.traits).forEach(function (id) {
        var terms = D.traits[id];
        if (want.every(function (w) { return terms.indexOf(w) >= 0; })) traitOk[id] = true;
      });
      var tokOk = {};
      Object.keys(D.tokens).forEach(function (tid) {
        if (D.tokens[tid][5].some(function (n) { return traitOk[n]; })) tokOk[tid] = true;
      });
      // (the old view's "exclude investigator" filter never took effect here, so investigators' lines are included)
      var rows = [];
      Object.keys(D.lines).forEach(function (lid) {
        var l = D.lines[lid];
        l[7].forEach(function (tid) { if (tokOk[tid]) rows.push([lid, tid]); });
      });
      rows.sort(function (a, b) {
        var la = D.lines[a[0]], lb = D.lines[b[0]];
        var A = locOf(la) || [''], B = locOf(lb) || [''];
        var ta = (textOf(la) || [''])[0], tb = (textOf(lb) || [''])[0];
        return cmp(A[0], B[0]) || cmp(ta, tb) || (la[1] - lb[1]);
      });
      return rows;
    },
    group: function (r) { var t = textOf(D.lines[r[0]]) || ['?', '#']; return { key: t[0], html: link(t[1], t[0]) }; },
    item: function (r) {
      var l = D.lines[r[0]], t = D.tokens[r[1]];
      return '<div class="hit compact"><b>' + link(t[1], t[0]) + '</b> ' + link(l[2], 'Line ' + l[1]) +
        ' <span class="fl">' + esc(l[4]) + '</span></div>';
    },
    loc: function (r) { return (textOf(D.lines[r[0]]) || [])[2]; },
    csv: function (r) {
      var l = D.lines[r[0]], t = D.tokens[r[1]], tx = textOf(l) || [''], lc = locOf(l) || [''];
      return { Location: lc[0], Text: tx[0], Line: l[1], Token: t[0], 'Full line': l[4] };
    }
  };

  var PHRASE = ['tense_mood', 'evidential', 'reflexive', 'clitic_objects', 'doubled_phrase', 'negation', 'word_order',
    'syntactic_cohesion', 'category_shift', 'accentuation', 'interrogative', 'verbal_phrase', 'style', 'miscellaneous'];
  S.phrase = {
    data: ['core', 'phrases'],
    run: function (p) {
      var want = PHRASE.filter(function (f) { return p['field_' + f + '_value']; });
      var rows = [];
      Object.keys(D.phrases).forEach(function (id) {
        var ph = D.phrases[id];
        if (want.every(function (f) { return (ph[3][f] || []).indexOf([].concat(p['field_' + f + '_value'])[0]) >= 0; })) rows.push(id);
      });
      rows.sort(function (a, b) {
        var la = D.lines[D.phrases[a][2]] || [0, 0], lb = D.lines[D.phrases[b][2]] || [0, 0];
        var ta = (textOf(la) || [''])[0], tb = (textOf(lb) || [''])[0];
        return cmp(ta, tb) || (la[1] - lb[1]);
      });
      return rows;
    },
    group: function (id) {
      var l = D.lines[D.phrases[id][2]], lc = l && locOf(l);
      return lc ? { key: lc[0], html: link(lc[1], lc[0]) } : { key: '', html: '(no location)' };
    },
    item: function (id) {
      var ph = D.phrases[id], l = D.lines[ph[2]];
      var tags = PHRASE.map(function (f) { return (ph[3][f] || []).join(', '); }).filter(Boolean).join(' · ');
      return '<div class="hit"><div><b>' + link(ph[1], ph[0]) + '</b> <span class="tags">' + esc(tags) + '</span></div>' +
        (l ? '<div class="where">' + link(l[2], l[3]) + '</div><div class="fl">' + esc(l[4]) + '</div><div class="tr">' + esc(l[5]) + '</div>' : '') + '</div>';
    },
    loc: function (id) { var l = D.lines[D.phrases[id][2]]; return l && (textOf(l) || [])[2]; },
    csv: function (id) {
      var ph = D.phrases[id], l = D.lines[ph[2]] || [], o = { Location: (l.length && locOf(l) || [''])[0], Line: l[3] || '', Phrase: ph[0] };
      PHRASE.forEach(function (f) { o[f] = (ph[3][f] || []).join(', '); });
      o['Full line'] = l[4] || ''; o.Translation = l[5] || '';
      return o;
    }
  };

  var COLS = ['meaning'].concat(['case', 'number', 'gram_gender', 'definiteness', 'person', 'tense', 'aspect', 'particle', 'clitic', 'deictic', 'other', 'pragmatic']);
  var COL_LABELS = ['Meaning', 'Case', 'Number', 'Gender', 'Definiteness', 'Person', 'Verb Form', 'Aspect', 'Particle', 'Clitic', 'Deictic', 'Other', 'Pragmatic'];
  // All Tokens works like a dictionary: "begins with" jumps to that point in the full alphabetical list,
  // so First / Previous / Next / Last always move through every token. Other operators filter the list.
  var allSorted = null;
  S.alltokens = {
    data: ['tokens'],
    always: true,
    run: function (p) {
      if (!allSorted) {
        allSorted = Object.keys(D.tokens).sort(function (a, b) { return cmp(D.tokens[a][0], D.tokens[b][0]); });
      }
      var op = p.title_op || 'starts', q = p.title || '';
      S.alltokens.matches = null; S.alltokens.startPage = 0; S.alltokens.note = '';
      if (op === 'starts' && q) {
        var nq = norm(q), first = -1, n = 0, m = {};
        allSorted.forEach(function (id, i) {
          if (norm(D.tokens[id][0]).indexOf(nq) === 0) { if (first < 0) first = i; m[id] = 1; n++; }
        });
        if (first < 0) {                    // no exact start: go to where it would be in the alphabet
          var k = ck(q); first = 0;
          while (first < allSorted.length && ck(D.tokens[allSorted[first]][0]) < k) first++;
        }
        S.alltokens.matches = m;
        S.alltokens.startPage = Math.floor(Math.max(0, first) / PAGE);
        S.alltokens.note = n.toLocaleString() + ' token' + (n === 1 ? '' : 's') + ' begin with \u201c' + q + '\u201d (highlighted), shown in the full list of ';
        return allSorted;
      }
      if (!q && !/empty/.test(op)) return allSorted;
      return allSorted.filter(function (id) { return strMatch(op, D.tokens[id][0], q); });
    },
    render: function (rows, page) {
      var m = S.alltokens.matches || {};
      var filtered = rows !== allSorted;
      var bar = '<div class="dict-bar"><a class="pg" href="?">\u21e4 Beginning of all tokens</a>' +
        '<a class="pg" href="?page=last">End of all tokens \u21e5</a>' +
        (filtered ? '<span class="pg-info">Showing only matching tokens</span>' : '') + '</div>';
      var h = '<div class="table-scroll"><table class="data"><thead><tr><th>Token</th><th>ID</th>' +
        COL_LABELS.map(function (l) { return '<th>' + l + '</th>'; }).join('') + '<th>Lexeme</th></tr></thead><tbody>';
      rows.slice(page * PAGE, (page + 1) * PAGE).forEach(function (id) {
        var t = D.tokens[id], lx = D.lexemes[t[4]];
        h += '<tr' + (m[id] ? ' class="match"' : '') + '><td>' + link(t[1], t[0]) + '</td><td class="num">' + id + '</td><td>' + esc(t[2]) + '</td>' +
          COLS.slice(1).map(function (f) { return '<td>' + esc((t[3][f] || []).join(', ')) + '</td>'; }).join('') +
          '<td>' + (lx ? link(lx[1], lx[0]) : '') + '</td></tr>';
      });
      return bar + pager(rows.length, page, true) + h + '</tbody></table></div>' + pager(rows.length, page, true) + bar;
    },
    csv: function (id) {
      var t = D.tokens[id], o = { Token: t[0], ID: id, Meaning: t[2] };
      COLS.slice(1).forEach(function (f, i) { o[COL_LABELS[i + 1]] = (t[3][f] || []).join(', '); });
      o.Lexeme = (D.lexemes[t[4]] || [''])[0];
      return o;
    }
  };

  // ---------------------------------------------------------------- hierarchical trait selector (Simple Hierarchical Select)
  function setupShs() {
    var boxes = form.querySelectorAll('.shs');
    if (!boxes.length) return Promise.resolve();
    return load(['traits']).then(function () {
      var kids = {};
      Object.keys(D.terms).forEach(function (tid) {
        var t = D.terms[tid];
        (kids[t[1]] = kids[t[1]] || []).push(+tid);
      });
      Object.keys(kids).forEach(function (k) {
        kids[k].sort(function (a, b) { return (D.terms[a][2] - D.terms[b][2]) || cmp(D.terms[a][0], D.terms[b][0]); });
      });
      boxes.forEach(function (box) {
        var hidden = box.querySelector('input[type=hidden]');
        function addLevel(parent, selected) {
          if (!kids[parent]) return;
          var s = document.createElement('select');
          s.innerHTML = '<option value="">- ' + (parent ? 'Any' : 'None') + ' -</option>' + kids[parent].map(function (t) {
            return '<option value="' + t + '">' + esc(D.terms[t][0]) + '</option>';
          }).join('');
          if (selected) s.value = selected;
          s.addEventListener('change', function () {
            while (s.nextSibling) s.parentNode.removeChild(s.nextSibling);
            hidden.value = s.value || (s.previousElementSibling && s.previousElementSibling.tagName === 'SELECT' ? s.previousElementSibling.value : '');
            if (s.value) addLevel(+s.value);
          });
          box.appendChild(s);
        }
        box.rebuild = function (tid) {
          box.querySelectorAll('select').forEach(function (s) { s.remove(); });
          var chain = [], t = tid ? +tid : 0;
          while (t && D.terms[t]) { chain.unshift(t); t = D.terms[t][1]; }
          var parent = 0;
          chain.forEach(function (c) { addLevel(parent, c); parent = c; });
          addLevel(parent);
          hidden.value = tid || '';
        };
        box.rebuild(hidden.value);
      });
    });
  }

  // ---------------------------------------------------------------- export
  function download(kind) {
    if (!current) return;
    var objs = current.rows.map(S[KIND].csv);
    if (!objs.length) return;
    var cols = Object.keys(objs[0]), blob, name = KIND + '-search';
    if (kind === 'csv') {
      var q = function (v) { v = String(v == null ? '' : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
      var text = '﻿' + cols.map(q).join(',') + '\n' + objs.map(function (o) { return cols.map(function (c) { return q(o[c]); }).join(','); }).join('\n');
      blob = new Blob([text], { type: 'text/csv;charset=utf-8' }); name += '.csv';
    } else {   // same trick as views_data_export: an HTML table Word opens as a document
      var html = '<html><head><meta charset="utf-8"></head><body><table border="1"><tr>' + cols.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr>' +
        objs.map(function (o) { return '<tr>' + cols.map(function (c) { return '<td>' + esc(o[c]) + '</td>'; }).join('') + '</tr>'; }).join('') + '</table></body></html>';
      blob = new Blob([html], { type: 'application/msword' }); name += '.doc';
    }
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  form.addEventListener('click', function (e) {
    var b = e.target.closest('[data-export]');
    if (b) download(b.dataset.export);
  });

  // ---------------------------------------------------------------- main
  var s = S[KIND];
  function show(page) {
    var h = s.render ? s.render(current.rows, page) : renderGrouped(current.rows, page, s.group, s.item, s.wrap);
    resultsEl.innerHTML = current.rows.length ? h : '<p>No results</p>';
  }
  function execute(p, scroll) {
    if (!s.always && !hasCriteria(p)) {
      resultsEl.innerHTML = ''; countEl.textContent = ''; exportsEl.hidden = true; if (mapEl) mapEl.hidden = true;
      return;
    }
    countEl.textContent = 'Searching…';
    load(s.data).then(function () {
      var t0 = performance.now();
      current = { rows: s.run(p) };
      countEl.textContent = (s.note || '') + current.rows.length.toLocaleString() + ' result' + (current.rows.length === 1 ? '' : 's') +
        ' (' + Math.round(performance.now() - t0) + ' ms)';
      exportsEl.hidden = !current.rows.length;
      var pg = p.page === 'last' ? Math.max(0, Math.ceil(current.rows.length / PAGE) - 1)
             : (p.page !== undefined ? +p.page : (s.startPage || 0));
      show(pg);
      if (s.loc) drawResultsMap(current.rows, s.loc);
      if (scroll) resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }).catch(function (e) { countEl.textContent = 'Error: ' + e.message; });
  }
  resultsEl.addEventListener('click', function (e) {
    var d = e.target.closest('.dict-bar a');
    if (d) {
      e.preventDefault();
      form.querySelectorAll('input[type=text]').forEach(function (i) { i.value = ''; });   // (not form.reset(): its handler would re-run the search)
      var q = d.getAttribute('href').indexOf('last') >= 0 ? { page: 'last' } : {};
      history.pushState(null, '', location.pathname + (q.page ? '?page=last' : ''));
      execute(q, false);
      resultsEl.scrollIntoView({ block: 'start' });
      return;
    }
    var a = e.target.closest('a[data-page]');
    if (!a) return;
    e.preventDefault();
    var pg = +a.dataset.page, p = readParams();
    p.page = pg;
    history.pushState(null, '', '?' + toQuery(p));
    show(pg);
    resultsEl.scrollIntoView({ block: 'start' });
  });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var p = formParams();
    history.pushState(null, '', location.pathname + (Object.keys(p).length ? '?' + toQuery(p) : ''));
    execute(p, true);
  });
  form.addEventListener('reset', function () {
    setTimeout(function () {
      form.querySelectorAll('.shs').forEach(function (b) { b.rebuild && b.rebuild(''); });
      history.pushState(null, '', location.pathname);
      execute({}, false);
    }, 0);
  });
  window.addEventListener('popstate', function () { var p = readParams(); fillForm(p); syncShs(); execute(p, false); });
  function syncShs() { form.querySelectorAll('.shs').forEach(function (b) { if (b.rebuild) b.rebuild(b.querySelector('input').value); }); }

  setupShs().then(function () {
    var p = readParams();
    fillForm(p); syncShs();
    execute(p, false);
  });
})();
