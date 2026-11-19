"""Local preview server for the generated site.

Usage: python3 pipeline/serve.py site [port]

Unlike `python3 -m http.server`, this supports HTTP Range requests, which browsers need
in order to seek within audio files (click a timecode, drag the progress bar), and it
serves 404.html for missing pages the way a real host does."""
import http.server, os, re, sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else 'site')
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
RANGE = re.compile(r'bytes=(\d*)-(\d*)$')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=root, **k)

    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        m = RANGE.match(self.headers.get('Range', '').strip())
        if not m or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        start, end = m.groups()
        if start == '':                      # suffix range: last N bytes
            start, end = max(0, size - int(end or 0)), size - 1
        else:
            start, end = int(start), (int(end) if end else size - 1)
        end = min(end, size - 1)
        if start >= size or start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        f = open(path, 'rb')
        f.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, '_remaining', None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        self._remaining = None
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            try:
                outputfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break                        # browser cancelled the request while seeking
            remaining -= len(chunk)

    def send_error(self, code, message=None, explain=None):
        page = os.path.join(root, '404.html')
        if code == 404 and os.path.exists(page):
            body = open(page, 'rb').read()
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().send_error(code, message, explain)

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    print(f'Serving {root} at http://localhost:{port}  (Ctrl-C to stop)')
    try:
        http.server.ThreadingHTTPServer(('', port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
