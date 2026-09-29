"""Builders for the /files/ pipeline tests: a book without network, a fake API, real-shaped entries."""
import json
import os
import posixpath
import types
from io import BytesIO

from PIL import Image

from safaribooks import SAFARI_BASE_URL, SafariBooks


class FakeDisplay:
    """Records what the book reports; `exit` raises like the real one (which calls sys.exit)."""

    book_ad_info = False
    in_error = False

    def __init__(self):
        self.messages = []
        self.state_status = types.SimpleNamespace(value=0)

    def _add(self, kind, message):
        self.messages.append((kind, str(message)))

    def info(self, message, state=False):
        self._add("info", message)

    def warning(self, message):
        self._add("warning", message)

    def error(self, message):
        self._add("error", message)

    def log(self, message):
        self._add("log", message)

    def state(self, total, done):
        pass

    def exit(self, message):
        self._add("exit", message)
        raise SystemExit(message)

    @staticmethod
    def api_error(response):
        return "API error: %r" % (response,)

    def of(self, kind):
        return [m for k, m in self.messages if k == kind]


def make_book(tmp_path, book_id="9781098168827", **arg_overrides):
    """A SafariBooks wired like after __init__ up to the plan, but with no session and no network."""
    args = dict(bookid=book_id, kindle=False, no_optimize_css=False, no_optimize_images=False,
                cred=False, no_cookies=True, log=False)
    args.update(arg_overrides)

    book = object.__new__(SafariBooks)
    book.args = types.SimpleNamespace(**args)
    book.display = FakeDisplay()
    book.book_id = book_id
    book.api_url = SafariBooks.API_TEMPLATE.format(book_id)
    book.book_title = "The Book"
    book.book_info = {"title": "The Book", "language": "en", "authors": [], "publishers": []}
    book.BOOK_PATH = str(tmp_path / "book")
    book.fixed_layout = False
    book.inline_stylesheets = {}
    book.font_sources = set()
    book.rename_map = {}
    book.chapter_stylesheets = []
    book.create_dirs()
    return book


def files_entry(book_id, path, kind, media_type):
    return {
        "full_path": path,
        "filename": posixpath.basename(path),
        "kind": kind,
        "media_type": media_type,
        "url": "%s/api/v2/epubs/urn:orm:book:%s/files/%s" % (SAFARI_BASE_URL, book_id, path),
    }


class FakeResponse:
    def __init__(self, body=b"", status=200, content_type="application/xhtml+xml; charset=utf-8", server="istio-envoy"):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": content_type, "Server": server}
        self.encoding = "utf-8"

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]

    def close(self):
        pass


class FakeApi:
    """url -> (status, body bytes, content type). Unknown URLs answer 404 and are remembered."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def serve(self, entry, body, status=200, content_type=None):
        self.routes[entry["url"]] = (status, body, content_type or entry["media_type"])

    def provider(self, url, *args, **kwargs):
        self.calls.append(url)
        status, body, content_type = self.routes.get(url, (404, b"", "text/plain"))
        return FakeResponse(body, status, content_type)


def png_bytes(color="red", size=(4, 4)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def tree_files(root):
    """Every file under root as a posix path relative to it."""
    found = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            found.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return sorted(found)
