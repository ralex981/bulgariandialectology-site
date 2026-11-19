"""Stage 1: Pantheon/MySQL dump (.sql.gz) -> raw SQLite copy of the Drupal tables we need.
Pure Python; no MySQL server required.  Usage: python3 extract.py DUMP.sql.gz raw.sqlite"""
import gzip, re, sqlite3, sys

WANTED = re.compile(r'^(node|field_data_\w+|field_config|field_config_instance|taxonomy_\w+|url_alias|'
                    r'file_managed|menu_links|variable|users|block|block_custom|block_node_type|block_role|quicktabs|ds_\w+|field_group|date_format_type|date_formats|views_view|views_display)$')
ESC = {'0': '\0', "'": "'", '"': '"', 'b': '\b', 'n': '\n', 'r': '\r', 't': '\t', 'Z': '\x1a', '\\': '\\'}

def parse_values(s, i):
    """Parse '(..),(..);' starting at s[i]; yield tuples."""
    n = len(s)
    while i < n:
        c = s[i]
        if c == '(':
            row, i = [], i + 1
            while True:
                c = s[i]
                if c == "'":
                    i += 1; buf = []; start = i
                    while True:
                        c = s[i]
                        if c == '\\':
                            buf.append(s[start:i]); buf.append(ESC.get(s[i+1], s[i+1])); i += 2; start = i
                        elif c == "'":
                            if s[i+1:i+2] == "'":
                                buf.append(s[start:i+1]); i += 2; start = i
                            else:
                                buf.append(s[start:i]); i += 1; break
                        else:
                            i += 1
                    row.append(''.join(buf))
                else:
                    j = i
                    while s[j] not in ',)': j += 1
                    tok = s[i:j].strip(); i = j
                    if tok == 'NULL': row.append(None)
                    elif tok.startswith('_binary'): row.append(tok)
                    else:
                        try: row.append(int(tok))
                        except ValueError: row.append(float(tok))
                c = s[i]
                if c == ',': i += 1; continue
                if c == ')': i += 1; break
            yield tuple(row)
        elif c in ',;\n ': i += 1
        else: raise ValueError(f'unexpected {s[i:i+40]!r}')

def fix(v):
    # strings containing invalid UTF-8 (rare; serialized blobs) are stored as raw bytes
    if isinstance(v, str):
        try: v.encode('utf-8')
        except UnicodeEncodeError: return v.encode('utf-8', 'surrogateescape')
    return v

def main(dump, out):
    db = sqlite3.connect(out); db.execute('pragma journal_mode=off'); db.execute('pragma synchronous=off')
    cols, cur_table, counts = {}, None, {}
    with gzip.open(dump, 'rt', encoding='utf-8', errors='surrogateescape') as f:
        for line in f:
            if line.startswith('CREATE TABLE `'):
                cur_table = line.split('`')[1]; cols[cur_table] = []
            elif cur_table and line.startswith('  `'):
                cols[cur_table].append(line.split('`')[1])
            elif line.startswith(') ENGINE'):
                t = cur_table; cur_table = None
                if WANTED.match(t):
                    db.execute(f'drop table if exists "{t}"')
                    db.execute(f'create table "{t}" ({",".join(chr(34)+c+chr(34) for c in cols[t])})')
            elif line.startswith('INSERT INTO `'):
                t = line.split('`')[1]
                if not WANTED.match(t): continue
                start = line.index(' VALUES ') + 8
                ph = ','.join('?' * len(cols[t]))
                rows = [tuple(fix(v) for v in r) for r in parse_values(line, start)]
                db.executemany(f'insert into "{t}" values ({ph})', rows)
                counts[t] = counts.get(t, 0) + len(rows)
    db.commit()
    print(f'{len(counts)} tables, {sum(counts.values())} rows ->', out)

if __name__ == '__main__':
    main(*sys.argv[1:3])
