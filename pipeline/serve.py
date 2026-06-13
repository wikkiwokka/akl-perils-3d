"""Local preview server for docs/ with HTTP byte-range support.

Python's stock http.server ignores Range headers and replies 200 with
the full body. PMTiles clients require real 206 partial responses to
read the archive header/directory and individual tiles, so without
this the pmtiles source fails to load (basemap renders, building and
flood layers do not).
"""

import functools
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from pipeline import config as C

PORT = 8000
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class RangeRequestHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        range_header = self.headers.get("Range")
        if not range_header or os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()

        m = RANGE_RE.fullmatch(range_header.strip())
        if not m:
            return super().send_head()

        file_size = os.path.getsize(path)
        start_s, end_s = m.groups()
        if start_s == "":
            length = int(end_s)
            start, end = max(0, file_size - length), file_size - 1
        else:
            start, end = int(start_s), (int(end_s) if end_s else file_size - 1)
        end = min(end, file_size - 1)

        if start > end or start >= file_size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return None

        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._range_remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_range_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


def main() -> None:
    handler = functools.partial(RangeRequestHandler, directory=str(C.DOCS))
    with ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"Serving {C.DOCS} at http://localhost:{PORT} (Range-enabled for PMTiles)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
