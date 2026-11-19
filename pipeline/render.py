"""Small HTML helpers shared by the page generator."""
import html, re

SITE_HOST = re.compile(r'https?://(?:www\.)?bulgariandialectology\.org(?=/|")', re.I)
BLOCK_TAG = re.compile(r'<(p|div|table|ul|ol|h[1-6]|blockquote|pre|br)\b', re.I)


def esc(s):
    return html.escape(str(s), quote=True) if s is not None else ''


def autop(text):
    """Approximation of Drupal's filter_autop: blank lines -> paragraphs, single newlines -> <br>."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return ''
    paras = re.split(r'\n\s*\n', text)
    return '\n'.join('<p>' + p.strip().replace('\n', '<br>\n') + '</p>' for p in paras)


def fix_links(h):
    """Make links to the old site root-relative so the static copy works on any host."""
    h = SITE_HOST.sub('', h)
    return h


URL_RE = re.compile(r'(?<![="\'/>\w@])((?:https?://|www\.)[^\s<>"]+[^\s<>".,;:!?)\]]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)')


def autolink(h):
    """Drupal's filter_url: turn bare URLs and e-mail addresses into links (outside tags and existing links)."""
    out, depth = [], 0
    for part in re.split(r'(<[^>]+>)', h):
        if part.startswith('<'):
            tag = part[1:3].lower()
            if tag.startswith('a ') or part.lower() == '<a>':
                depth += 1
            elif part.lower().startswith('</a'):
                depth = max(0, depth - 1)
            out.append(part)
        elif depth:
            out.append(part)
        else:
            def sub(m):
                u = m.group(1)
                if '@' in u and '://' not in u:
                    return f'<a href="mailto:{u}">{u}</a>'
                href = u if '://' in u else 'http://' + u
                return f'<a href="{href}">{u}</a>'
            out.append(URL_RE.sub(sub, part))
    return ''.join(out)


def rich(value, fmt):
    """Render a Drupal text value according to its text format."""
    if value is None:
        return ''
    value = str(value)
    if fmt is None or fmt == 'plain_text':
        return autolink(autop(esc(value)))
    if not BLOCK_TAG.search(value):
        value = autop(value)
    return fix_links(autolink(value))
