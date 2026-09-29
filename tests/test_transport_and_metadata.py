"""Transport (Akamai retry, redirects, decoding) and book metadata (credits, book info)."""
import json

import pytest
import requests

from safaribooks import SafariBooks
from support import FakeResponse, make_book

BOOK = "9781098168827"


class _Raw:
    def __init__(self, cookies=()):
        self.headers = self
        self._cookies = list(cookies)

    def getlist(self, name):
        return self._cookies


class Reply:
    """What a requests.Response offers to requests_provider."""

    def __init__(self, status=200, server="istio-envoy", text="", body=b"", location=None, cookies=()):
        self.status_code = status
        self.headers = {"Server": server, "Content-Type": "text/html; charset=utf-8"}
        self.text = text
        self.content = body
        self.raw = _Raw(cookies)
        self.is_redirect = location is not None
        self.next = type("N", (), {"url": location})() if location else None
        self.closed = False

    def close(self):
        self.closed = True


class ScriptedSession:
    """Answers each GET/POST from a script: a Reply, or an exception instance to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        return self._next("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._next("post", url, **kwargs)


def provider_book(tmp_path, script, monkeypatch):
    book = make_book(tmp_path, BOOK)
    book.session = ScriptedSession(script)
    slept = []
    monkeypatch.setattr("safaribooks.time.sleep", slept.append)
    book.slept = slept
    return book


AKAMAI_BLOCK = dict(status=403, server="AkamaiGHost")


# ---------------------------------------------------------------- Akamai retry
def test_akamai_edge_block_is_retried_until_the_real_answer(tmp_path, monkeypatch):
    ok = Reply(200, body=b"chapter")
    book = provider_book(tmp_path, [Reply(**AKAMAI_BLOCK), Reply(**AKAMAI_BLOCK), ok], monkeypatch)

    assert book.requests_provider("https://x/a") is ok
    assert len(book.session.calls) == 3 and len(book.slept) == 2


def test_a_real_403_from_the_backend_fails_fast(tmp_path, monkeypatch):
    forbidden = Reply(403, server="istio-envoy")
    book = provider_book(tmp_path, [forbidden], monkeypatch)

    assert book.requests_provider("https://x/a") is forbidden
    assert len(book.session.calls) == 1 and book.slept == []


def test_the_akamai_fingerprint_is_matched_case_insensitively(tmp_path, monkeypatch):
    book = provider_book(tmp_path, [Reply(403, server="AKAMAIGHOST"), Reply(200)], monkeypatch)
    assert book.requests_provider("https://x/a").status_code == 200


def test_akamai_retries_are_bounded_and_the_last_block_is_returned(tmp_path, monkeypatch):
    blocks = [Reply(**AKAMAI_BLOCK) for _ in range(SafariBooks.MAX_RETRIES + 1)]
    book = provider_book(tmp_path, blocks, monkeypatch)

    assert book.requests_provider("https://x/a") is blocks[-1]
    assert len(book.session.calls) == SafariBooks.MAX_RETRIES + 1
    assert all(reply.closed for reply in blocks[:-1])  # discarded connections are released


def test_backoff_grows_and_is_capped(tmp_path, monkeypatch):
    book = provider_book(tmp_path, [Reply(**AKAMAI_BLOCK) for _ in range(12)] + [Reply(200)], monkeypatch)
    book.requests_provider("https://x/a")
    caps = SafariBooks.RETRY_BACKOFF_MAX_SECONDS

    assert all(delay <= caps + 1 for delay in book.slept)  # + the sub-second jitter
    assert book.slept[0] < book.slept[3] and max(book.slept) > caps - 1


def test_transient_network_errors_are_retried(tmp_path, monkeypatch):
    ok = Reply(200)
    errors = [requests.ConnectionError("reset"), requests.Timeout("slow"),
              requests.exceptions.ChunkedEncodingError("cut")]
    book = provider_book(tmp_path, errors + [ok], monkeypatch)

    assert book.requests_provider("https://x/a") is ok
    assert len(book.slept) == 3


@pytest.mark.parametrize("error", [requests.exceptions.SSLError("bad cert"), requests.exceptions.InvalidURL("nope"),
                                   requests.exceptions.TooManyRedirects("loop")])
def test_deterministic_errors_fail_fast_without_retrying(tmp_path, monkeypatch, error):
    book = provider_book(tmp_path, [error], monkeypatch)

    assert book.requests_provider("https://x/a") == 0
    assert len(book.session.calls) == 1 and book.slept == []
    assert book.display.of("error")


def test_network_error_gives_up_after_the_retry_budget(tmp_path, monkeypatch):
    book = provider_book(tmp_path, [requests.ConnectionError("down")] * (SafariBooks.MAX_RETRIES + 1), monkeypatch)

    assert book.requests_provider("https://x/a") == 0
    assert len(book.session.calls) == SafariBooks.MAX_RETRIES + 1


def test_redirects_are_followed_by_hand_and_can_be_switched_off(tmp_path, monkeypatch):
    final = Reply(200)
    book = provider_book(tmp_path, [Reply(302, location="https://x/b"), final], monkeypatch)
    assert book.requests_provider("https://x/a") is final
    assert [c[1] for c in book.session.calls] == ["https://x/a", "https://x/b"]

    redirect = Reply(302, location="https://x/b")
    book = provider_book(tmp_path / "2", [redirect], monkeypatch)
    assert book.requests_provider("https://x/a", perform_redirect=False) is redirect


def test_float_max_age_cookies_are_repaired(tmp_path, monkeypatch):
    book = provider_book(tmp_path, [Reply(200, cookies=["orm-jwt=abc; max-age=3600.5; Path=/"])], monkeypatch)
    book.session.cookies = requests.cookies.RequestsCookieJar()
    book.requests_provider("https://x/a")

    assert book.session.cookies.get("orm-jwt") == "abc"


def test_the_last_request_is_recorded_for_the_error_log(tmp_path, monkeypatch):
    book = provider_book(tmp_path, [Reply(200, text="body")], monkeypatch)
    book.requests_provider("https://x/a")

    assert book.display.last_request[0] == "https://x/a" and book.display.last_request[3] == 200


# ---------------------------------------------------------------- response_text
def test_response_text_decodes_a_charsetless_utf8_body_correctly():
    body = "You\u2019ll see caf\u00e9".encode("utf-8")
    reply = FakeResponse(body, content_type="text/html")
    reply.encoding = "ISO-8859-1"  # what requests guesses for text/* without a charset

    assert SafariBooks.response_text(reply) == "You\u2019ll see caf\u00e9"


def test_response_text_honours_a_declared_charset():
    reply = FakeResponse("caf\u00e9".encode("latin-1"), content_type="text/html; charset=iso-8859-1")
    reply.encoding = "iso-8859-1"

    assert SafariBooks.response_text(reply) == "caf\u00e9"


def test_response_text_survives_an_unknown_declared_charset():
    reply = FakeResponse("caf\u00e9".encode("utf-8"), content_type="text/html; charset=bogus-xx")
    reply.encoding = "bogus-xx"

    assert SafariBooks.response_text(reply) == "caf\u00e9"


# ---------------------------------------------------------------- credits (search API, docAuthor fallback)
def credits_book(tmp_path, search=None, ncx=None):
    book = make_book(tmp_path, BOOK)

    def provider(url, *args, **kwargs):
        if "/api/v2/search/" in url:
            return search if search is not None else 0
        if url.endswith("files/toc.ncx"):
            return ncx if ncx is not None else 0
        raise AssertionError(url)

    book.requests_provider = provider
    return book


def test_credits_come_from_the_exact_search_match_of_the_real_capture(tmp_path, load_fixture):
    search = FakeResponse(json.dumps(load_fixture("search_9781098168827.json")), content_type="application/json")
    authors, publishers = credits_book(tmp_path, search=search).get_book_credits()

    assert authors and publishers
    assert all(set(entry) == {"name"} and entry["name"] for entry in authors + publishers)


def test_credits_never_take_the_first_hit_when_it_is_another_book(tmp_path):
    body = {"results": [
        {"archive_id": "1111111111111", "authors": ["Wrong Author"], "publishers": ["Wrong House"]},
        {"archive_id": BOOK, "authors": ["Right Author", ""], "publishers": ["Right House"]},
    ]}
    authors, publishers = credits_book(tmp_path, search=FakeResponse(json.dumps(body))).get_book_credits()

    assert authors == [{"name": "Right Author"}] and publishers == [{"name": "Right House"}]


def test_credits_fall_back_to_the_public_toc_author_when_search_needs_a_login(tmp_path, load_fixture):
    ncx = FakeResponse(load_fixture("toc_9781098168827_head.ncx"), content_type="application/x-dtbncx+xml")
    book = credits_book(tmp_path, search=FakeResponse("{}", status=401), ncx=ncx)
    authors, publishers = book.get_book_credits()

    assert len(authors) == 1 and authors[0]["name"] and publishers == []
    assert any("publisher" in m for m in book.display.of("warning"))


def test_credits_survive_a_dead_connection_and_report_what_is_missing(tmp_path):
    book = credits_book(tmp_path)
    assert book.get_book_credits() == ([], [])
    assert len(book.display.of("warning")) == 2


def test_credits_survive_a_search_reply_that_is_not_json(tmp_path):
    book = credits_book(tmp_path, search=FakeResponse("<html>oops</html>"))
    assert book.get_book_credits() == ([], [])


def test_the_toc_author_is_read_as_utf8_and_unescaped(tmp_path):
    ncx = ('<ncx><docAuthor><text>Jos\u00e9 &amp; Mar\u00eda</text></docAuthor></ncx>').encode("utf-8")
    reply = FakeResponse(ncx, content_type="application/x-dtbncx+xml")
    reply.encoding = "ISO-8859-1"

    assert credits_book(tmp_path, ncx=reply).get_ncx_authors() == [{"name": "Jos\u00e9 & Mar\u00eda"}]


# ---------------------------------------------------------------- get_book_info
def info_book(tmp_path, load_fixture, payload=None, status=200):
    book = make_book(tmp_path, BOOK)
    data = payload if payload is not None else load_fixture("epub_9781098168827.json")
    book.requests_provider = lambda url, *a, **k: FakeResponse(json.dumps(data), status, "application/json")
    book.get_book_credits = lambda: ([{"name": "A"}], [{"name": "P"}])
    return book


def test_book_info_from_the_real_capture_carries_title_language_and_credits(tmp_path, load_fixture):
    info = info_book(tmp_path, load_fixture).get_book_info()

    assert info["title"] and info["isbn"] and info["issued"]
    assert info["authors"] == [{"name": "A"}] and info["publishers"] == [{"name": "P"}]
    assert info["web_url"].endswith("/library/view/-/%s/" % BOOK)


def test_book_info_carries_the_editions_language(tmp_path, load_fixture):
    payload = dict(load_fixture("epub_9781098168827.json"), language="es")
    assert info_book(tmp_path, load_fixture, payload).get_book_info()["language"] == "es"


def test_book_info_exits_on_an_error_payload(tmp_path, load_fixture):
    with pytest.raises(SystemExit):
        info_book(tmp_path, load_fixture, payload={"detail": "Not found."}).get_book_info()
