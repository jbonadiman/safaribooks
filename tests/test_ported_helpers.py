import json


import os


import re


import types


from io import BytesIO


from unittest.mock import patch


import pytest


from lxml import html


from PIL import Image


from safaribooks import SafariBooks


def make_png_bytes(color="red"):
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return buf.getvalue()


def test_sanitize_xml_id_prefixes_digit_leading_names():
    assert SafariBooks.sanitize_xml_id("01intro")[0].isalpha() or SafariBooks.sanitize_xml_id("01intro")[0] == "_"


def test_sanitize_xml_id_replaces_slashes():
    assert "/" not in SafariBooks.sanitize_xml_id("xhtml/ch01")


def test_sanitize_xml_id_leaves_valid_names_untouched():
    assert SafariBooks.sanitize_xml_id("ch01") == "ch01"


def test_strip_empty_output_blocks_removes_empty_pre():
    root = html.fromstring(
        '<div><pre data-type="programlisting" class="output"></pre></div>'
    )
    SafariBooks.strip_empty_output_blocks(root)
    assert not root.xpath("//pre")


def test_strip_empty_output_blocks_removes_literal_empty_quotes():
    root = html.fromstring(
        "<div><pre data-type=\"programlisting\" class=\"output\">''</pre></div>"
    )
    SafariBooks.strip_empty_output_blocks(root)
    assert not root.xpath("//pre")


def test_strip_empty_output_blocks_keeps_pre_with_real_content():
    root = html.fromstring(
        '<div><pre data-type="programlisting" class="output">42</pre></div>'
    )
    SafariBooks.strip_empty_output_blocks(root)
    assert len(root.xpath("//pre")) == 1


def test_strip_empty_output_blocks_ignores_unrelated_pre():
    root = html.fromstring(
        '<div><pre data-type="programlisting" class="input"></pre></div>'
    )
    SafariBooks.strip_empty_output_blocks(root)
    assert len(root.xpath("//pre")) == 1


def test_needs_jpg_conversion_true_for_png():
    assert SafariBooks.needs_jpg_conversion("cover.png") is True


def test_needs_jpg_conversion_false_for_jpeg():
    assert SafariBooks.needs_jpg_conversion("photo.jpeg") is False
    assert SafariBooks.needs_jpg_conversion("photo.JPG") is False


def test_needs_jpg_conversion_false_for_svg():
    assert SafariBooks.needs_jpg_conversion("diagram.svg") is False


def test_convert_image_to_jpg_produces_valid_jpeg(tmp_path):
    src = tmp_path / "cover.png"
    src.write_bytes(make_png_bytes())
    dest = tmp_path / "cover.jpg"

    SafariBooks.convert_image_to_jpg(str(src), str(dest))

    with Image.open(dest) as img:
        assert img.format == "JPEG"


def test_convert_image_to_jpg_handles_transparency(tmp_path):
    src = tmp_path / "icon.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(src, "PNG")
    dest = tmp_path / "icon.jpg"

    SafariBooks.convert_image_to_jpg(str(src), str(dest))

    with Image.open(dest) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"


def test_convert_image_to_jpg_composites_transparent_pixels_onto_white(tmp_path):
    # Fully-transparent pixels commonly store black/garbage RGB underneath
    # (encoders don't bother writing meaningful color where alpha=0), so a
    # naive convert("RGB") leaves visible dark smudges instead of background.
    src = tmp_path / "logo.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for x in range(15, 25):
        for y in range(15, 25):
            img.putpixel((x, y), (255, 0, 0, 255))
    img.save(src, "PNG")
    dest = tmp_path / "logo.jpg"

    SafariBooks.convert_image_to_jpg(str(src), str(dest))

    with Image.open(dest) as out:
        corner = out.getpixel((0, 0))
        assert all(channel > 200 for channel in corner)
        center = out.getpixel((20, 20))
        assert center[0] > 200 and center[1] < 100 and center[2] < 100


def test_polish_epub_skips_when_calibre_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("safaribooks.shutil.which", lambda name: None)
    display = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    result = SafariBooks.polish_epub(str(tmp_path / "book.epub"), display)

    assert result is False


def test_polish_epub_replaces_file_on_success(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"original")

    def fake_run(argv, capture_output, text):
        out_path = argv[-1]
        with open(out_path, "wb") as f:
            f.write(b"polished")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("safaribooks.shutil.which", lambda name: "/usr/bin/ebook-polish")
    monkeypatch.setattr("safaribooks.subprocess.run", fake_run)
    display = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    result = SafariBooks.polish_epub(str(epub_path), display)

    assert result is True
    assert epub_path.read_bytes() == b"polished"


def test_polish_epub_cleans_up_on_failure(tmp_path, monkeypatch):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"original")

    def fake_run(argv, capture_output, text):
        out_path = argv[-1]
        with open(out_path, "wb") as f:
            f.write(b"broken")
        return types.SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr("safaribooks.shutil.which", lambda name: "/usr/bin/ebook-polish")
    monkeypatch.setattr("safaribooks.subprocess.run", fake_run)
    display = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)

    result = SafariBooks.polish_epub(str(epub_path), display)

    assert result is False
    assert epub_path.read_bytes() == b"original"
    assert not os.path.isfile(str(epub_path) + ".polishing")


def test_strip_color_from_stylesheet_removes_color_keeps_background():
    css = ".a { color: red; background-color: blue; }"
    result = SafariBooks.strip_color_from_stylesheet(css)
    assert "color: red" not in result
    assert "background-color: blue" in result


def test_strip_color_from_stylesheet_handles_nested_media_rules():
    css = "@media (min-width: 100px) { p { color: #fff !important; margin: 0; } }"
    result = SafariBooks.strip_color_from_stylesheet(css)
    assert "color" not in result
    assert "margin: 0" in result


def test_strip_color_from_stylesheet_preserves_other_declarations():
    css = ".a { color: red; font-weight: bold; }"
    result = SafariBooks.strip_color_from_stylesheet(css)
    assert "font-weight: bold" in result


def test_strip_color_from_stylesheet_drops_malformed_declarations_instead_of_raising():
    css = ".a { color: red; garbage-no-colon-value }"
    result = SafariBooks.strip_color_from_stylesheet(css)
    assert "color" not in result


def test_strip_color_from_stylesheet_drops_malformed_rules_instead_of_raising():
    css = "@invalid-at-rule-with-no-block .a { color: red; }"
    result = SafariBooks.strip_color_from_stylesheet(css)
    assert "color" not in result


def test_strip_color_from_style_attr_removes_color():
    result = SafariBooks.strip_color_from_style_attr("color: red; font-weight: bold")
    assert "color" not in result
    assert "font-weight: bold" in result


def test_strip_color_from_style_attr_returns_empty_when_only_color():
    result = SafariBooks.strip_color_from_style_attr("color: red")
    assert result == ""


def test_strip_color_from_style_attr_preserves_background_color():
    result = SafariBooks.strip_color_from_style_attr("background-color: blue")
    assert "background-color: blue" in result


def test_strip_inline_style_color_removes_attr_when_empty():
    root = html.fromstring('<div><span style="color: red">hi</span></div>')
    SafariBooks.strip_inline_style_color(root)
    assert root.xpath("//span/@style") == []


def test_strip_inline_style_color_keeps_other_declarations():
    root = html.fromstring('<div><span style="color: red; font-weight: bold">hi</span></div>')
    SafariBooks.strip_inline_style_color(root)
    style = root.xpath("//span/@style")[0]
    assert "color" not in style
    assert "font-weight" in style


def test_strip_inline_style_color_ignores_elements_without_style():
    root = html.fromstring('<div><span>hi</span></div>')
    SafariBooks.strip_inline_style_color(root)
    assert root.xpath("//span/@style") == []


def test_create_dirs_writes_base_stylesheet(tmp_path):
    instance = object.__new__(SafariBooks)
    instance.BOOK_PATH = str(tmp_path / "book")
    instance.args = types.SimpleNamespace(kindle=False)
    instance.display = types.SimpleNamespace(
        log=lambda *a, **k: None,
    )
    instance.display.book_ad_info = False
    instance.display.css_ad_info = types.SimpleNamespace(value=0)
    instance.display.images_ad_info = types.SimpleNamespace(value=0)

    instance.create_dirs()

    base_css = os.path.join(instance.css_path, "Style_Base.css")
    assert os.path.isfile(base_css)
    assert not os.path.isfile(os.path.join(instance.css_path, "Style_Kindle.css"))


def test_create_dirs_writes_kindle_stylesheet_when_enabled(tmp_path):
    instance = object.__new__(SafariBooks)
    instance.BOOK_PATH = str(tmp_path / "book")
    instance.args = types.SimpleNamespace(kindle=True)
    instance.display = types.SimpleNamespace(
        log=lambda *a, **k: None,
    )
    instance.display.book_ad_info = False
    instance.display.css_ad_info = types.SimpleNamespace(value=0)
    instance.display.images_ad_info = types.SimpleNamespace(value=0)

    instance.create_dirs()

    assert os.path.isfile(os.path.join(instance.css_path, "Style_Kindle.css"))


def make_parse_html_instance(css_path):
    instance = object.__new__(SafariBooks)
    instance.display = types.SimpleNamespace(
        log=lambda *a, **k: None, info=lambda *a, **k: None, error=lambda *a, **k: None,
        exit=lambda *a, **k: (_ for _ in ()).throw(SystemExit("exit called: " + str(a))),
        api_error=lambda *a: "api_error",
    )
    instance.filename = "ch01.html"
    instance.chapter_title = "Chapter 1"
    instance.chapter_stylesheets = []
    instance.css = []
    instance.css_path = css_path
    instance.inline_stylesheets = {}
    instance.base_url = "https://example.com/"
    instance.book_id = "999999"
    instance.cover = False
    instance.args = types.SimpleNamespace(no_optimize_css=False)
    return instance


def make_css_download_instance(tmp_path, css_url, no_optimize_css):
    instance = object.__new__(SafariBooks)
    instance.css = [css_url]
    instance.fonts = {}
    instance.css_path = str(tmp_path)
    instance.BOOK_PATH = str(tmp_path)
    instance.args = types.SimpleNamespace(no_optimize_css=no_optimize_css)
    instance.css_done_queue = types.SimpleNamespace(put=lambda *a, **k: None, qsize=lambda: 1)
    instance.display = types.SimpleNamespace(
        css_ad_info=types.SimpleNamespace(value=0),
        info=lambda *a, **k: None, error=lambda *a, **k: None, state=lambda *a, **k: None,
    )
    instance.requests_provider = lambda url: types.SimpleNamespace(content=b".a{color:red;font-weight:bold;}")
    return instance


class _FakeResponse:
    def __init__(self, status_code, server_header="istio-envoy", is_redirect=False, text=""):
        self.status_code = status_code
        self.headers = {"Server": server_header}
        self.is_redirect = is_redirect
        self.text = text
        self.raw = types.SimpleNamespace(headers=types.SimpleNamespace(getlist=lambda k: []))
        self.closed = False

    def close(self):
        self.closed = True


def make_requests_provider_instance():
    instance = SafariBooks.__new__(SafariBooks)
    instance.session = types.SimpleNamespace()
    instance.display = types.SimpleNamespace(
        last_request=None,
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    return instance


def test_requests_provider_retries_akamai_edge_block_then_succeeds():
    # Regression: an Akamai edge WAF intermittently 403s otherwise-valid
    # requests (Server: AkamaiGHost, body links to errors.edgesuite.net),
    # completely independent of auth state -- confirmed by replaying the same
    # URL/session dozens of times against the real book and seeing it flip
    # between success and this block at a ~30-45% rate. Previously any non-200
    # was instantly fatal (display.exit -> sys.exit(1)), so one unlucky flip on
    # any one of dozens of chapters killed the entire download.
    instance = make_requests_provider_instance()
    responses = [
        _FakeResponse(403, server_header="AkamaiGHost"),
        _FakeResponse(403, server_header="AkamaiGHost"),
        _FakeResponse(200, server_header="istio-envoy", text="<html>real content</html>"),
    ]
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        return responses[len(calls) - 1]

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/ch24.xhtml")

    assert result.status_code == 200
    assert result.text == "<html>real content</html>"
    assert len(calls) == 3


def test_requests_provider_does_not_retry_genuine_app_level_403():
    # A real backend rejection (e.g. actual auth failure) comes from the
    # actual application server, not the edge WAF -- fingerprinted here by
    # Server: istio-envoy rather than AkamaiGHost. Retrying that would just
    # waste time on something that will never succeed, so it must return
    # immediately on the first attempt.
    instance = make_requests_provider_instance()
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        return _FakeResponse(403, server_header="istio-envoy", text="real app-level rejection")

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep") as fake_sleep:
        result = instance.requests_provider("https://example.com/ch24.xhtml")

    assert result.status_code == 403
    assert len(calls) == 1
    fake_sleep.assert_not_called()


def test_requests_provider_gives_up_after_max_retries_on_persistent_akamai_block():
    instance = make_requests_provider_instance()
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        return _FakeResponse(403, server_header="AkamaiGHost")

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/ch24.xhtml")

    assert result.status_code == 403
    assert len(calls) == SafariBooks.MAX_RETRIES + 1


def test_requests_provider_retries_connection_errors_then_succeeds():
    instance = make_requests_provider_instance()
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        if len(calls) < 2:
            import requests
            raise requests.ConnectionError("simulated transient network failure")
        return _FakeResponse(200, text="<html>ok</html>")

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/ch24.xhtml")

    assert result.status_code == 200
    assert len(calls) == 2


def test_requests_provider_does_not_retry_deterministic_network_errors():
    # SSL verification failures, bad URLs etc. can never succeed on retry, so they
    # must fail fast instead of burning the whole backoff budget.
    import requests

    for exc in (requests.exceptions.SSLError("bad cert"),
                requests.exceptions.MissingSchema("no scheme"),
                requests.exceptions.InvalidURL("bad url")):
        instance = make_requests_provider_instance()
        calls = []

        def fake_get(url, data=None, allow_redirects=False, _exc=exc, **kwargs):
            calls.append(url)
            raise _exc

        instance.session.get = fake_get

        with patch("safaribooks.time.sleep") as fake_sleep:
            result = instance.requests_provider("https://example.com/x")

        assert result == 0
        assert len(calls) == 1
        fake_sleep.assert_not_called()


def test_requests_provider_retries_timeouts():
    import requests

    instance = make_requests_provider_instance()
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise requests.Timeout("simulated read timeout")
        return _FakeResponse(200, text="ok")

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/x")

    assert result.status_code == 200
    assert len(calls) == 3


def test_requests_provider_backoff_is_capped():
    instance = make_requests_provider_instance()
    instance.session.get = lambda *a, **k: _FakeResponse(403, server_header="AkamaiGHost")

    with patch("safaribooks.time.sleep") as fake_sleep:
        instance.requests_provider("https://example.com/x")

    delays = [c.args[0] for c in fake_sleep.call_args_list]
    assert len(delays) == SafariBooks.MAX_RETRIES
    assert all(d <= SafariBooks.RETRY_BACKOFF_MAX_SECONDS + 1 for d in delays)
    assert delays[0] < delays[3]  # still exponential before the cap


def test_requests_provider_akamai_fingerprint_is_case_insensitive():
    instance = make_requests_provider_instance()
    responses = [_FakeResponse(403, server_header="AkamaiNetStorage"), _FakeResponse(200)]
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        return responses[len(calls) - 1]

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/x")

    assert result.status_code == 200
    assert len(calls) == 2


def test_requests_provider_closes_discarded_akamai_responses():
    instance = make_requests_provider_instance()
    blocked = _FakeResponse(403, server_header="AkamaiGHost")
    responses = [blocked, _FakeResponse(200)]
    calls = []

    def fake_get(url, data=None, allow_redirects=False, **kwargs):
        calls.append(url)
        return responses[len(calls) - 1]

    instance.session.get = fake_get

    with patch("safaribooks.time.sleep"):
        result = instance.requests_provider("https://example.com/x", stream=True)

    assert blocked.closed
    assert not result.closed


def _finalize_instance(book_path, cover=False):
    instance = object.__new__(SafariBooks)
    instance.BOOK_PATH = str(book_path)
    instance.images_path = str(book_path / "OEBPS" / "Images")
    instance.cover = cover
    instance.display = types.SimpleNamespace(
        info=lambda *a, **k: None, log=lambda *a, **k: None, error=lambda *a, **k: None
    )
    return instance


def test_write_epub_archive_puts_stored_mimetype_first(tmp_path):
    # EPUB OCF: "mimetype" must be the first entry and uncompressed. shutil.make_archive
    # gets both wrong, and only Calibre's optional polish step used to repair it.
    import zipfile

    book = tmp_path / "book"
    (book / "META-INF").mkdir(parents=True)
    (book / "OEBPS" / "xhtml").mkdir(parents=True)
    (book / "mimetype").write_text("application/epub+zip")
    (book / "META-INF" / "container.xml").write_text("<c/>")
    (book / "OEBPS" / "content.opf").write_text("<opf/>")
    (book / "OEBPS" / "xhtml" / "ch01.xhtml").write_text("<html/>")
    (book / "stray.epub").write_text("must not be packed into itself")

    epub = tmp_path / "out.epub"
    SafariBooks.write_epub_archive(str(book), str(epub))

    with zipfile.ZipFile(epub) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        names = z.namelist()
        assert "OEBPS/xhtml/ch01.xhtml" in names and "META-INF/container.xml" in names
        assert not any(n.endswith("/") for n in names)  # no directory entries
        assert "stray.epub" not in names
        assert z.testzip() is None


def _book_with_default_cover(tmp_path, chapter_ref, extra_images=("fig1.jpg",)):
    # default_cover.xhtml lives at the OEBPS root and always references
    # Images/default_cover.jpg; that must not make the scanner look "healthy".
    book = tmp_path / "book"
    oebps = book / "OEBPS"
    (oebps / "xhtml").mkdir(parents=True)
    (oebps / "Images").mkdir()
    (oebps / "default_cover.xhtml").write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="Images/default_cover.jpg"/></body></html>'
    )
    (oebps / "xhtml" / "ch01.xhtml").write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="%s"/></body></html>' % chapter_ref
    )
    for name in ("default_cover.jpg",) + tuple(extra_images):
        (oebps / "Images" / name).write_bytes(make_png_bytes("red"))
    return book, oebps / "Images"


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8", newline="") as fh:
        return fh.read()


def make_metadata_instance(routes):
    """SafariBooks whose requests_provider serves `routes` (substring -> (status, body))."""
    warnings = []
    instance = object.__new__(SafariBooks)
    instance.book_id = "9781098168827"
    instance.api_url = SafariBooks.API_TEMPLATE.format(instance.book_id)
    instance.display = types.SimpleNamespace(
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
        warning=lambda msg, *a, **k: warnings.append(msg),
        exit=lambda msg: (_ for _ in ()).throw(AssertionError("display.exit: %s" % msg)),
        api_error=lambda r: "api error",
    )
    instance.warnings = warnings

    def provider(url, *args, **kwargs):
        for needle, (status, body) in routes.items():
            if needle in url:
                return types.SimpleNamespace(
                    status_code=status,
                    text=body,
                    content=body.encode("utf-8"),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    encoding="utf-8",
                    json=lambda body=body: json.loads(body),
                )
        return types.SimpleNamespace(
            status_code=404, text="{}", content=b"{}",
            headers={"Content-Type": "application/json; charset=utf-8"}, encoding="utf-8",
            json=lambda: {},
        )

    instance.requests_provider = provider
    return instance


def live_routes(search_status=200):
    return {
        "/search/": (search_status, load_fixture("search_9781098168827.json")),
        "files/toc.ncx": (200, load_fixture("toc_9781098168827_head.ncx")),
        "/epubs/urn:orm:book:9781098168827/": (200, load_fixture("epub_9781098168827.json")),
    }


def test_get_book_info_reads_authors_and_publishers_from_search_api():
    instance = make_metadata_instance(live_routes())

    info = instance.get_book_info()

    assert info["authors"] == [{"name": "Sebastian Raschka"}]
    assert info["publishers"] == [{"name": "No Starch Press"}]


def test_get_book_info_picks_the_search_result_matching_the_book_id():
    search = json.loads(load_fixture("search_9781098168827.json"))
    decoy = dict(search["results"][0], archive_id="1111111111111", authors=["Wrong Person"],
                 publishers=["Wrong House"])
    search["results"].insert(0, decoy)
    routes = live_routes()
    routes["/search/"] = (200, json.dumps(search))
    instance = make_metadata_instance(routes)

    info = instance.get_book_info()

    assert info["authors"] == [{"name": "Sebastian Raschka"}]
    assert info["publishers"] == [{"name": "No Starch Press"}]


def test_get_book_info_falls_back_to_ncx_author_when_search_is_unauthorized():
    instance = make_metadata_instance(live_routes(search_status=401))

    info = instance.get_book_info()

    assert info["authors"] == [{"name": "Sebastian Raschka"}]
    assert info["publishers"] == []
    assert instance.warnings, "a missing publisher must be reported, not silently dropped"


def test_get_book_info_falls_back_to_ncx_when_search_has_no_exact_match():
    routes = live_routes()
    search = json.loads(load_fixture("search_9781098168827.json"))
    search["results"][0]["archive_id"] = "2222222222222"
    routes["/search/"] = (200, json.dumps(search))
    instance = make_metadata_instance(routes)

    info = instance.get_book_info()

    assert info["authors"] == [{"name": "Sebastian Raschka"}]
    assert info["publishers"] == []


def test_get_book_info_returns_empty_lists_when_no_source_has_metadata():
    routes = live_routes(search_status=401)
    routes["files/toc.ncx"] = (404, "")
    instance = make_metadata_instance(routes)

    info = instance.get_book_info()

    assert info["authors"] == []
    assert info["publishers"] == []
    assert info["title"] == "Machine Learning Q and AI"


def make_opf_instance(tmp_path, book_info):
    (tmp_path / "Styles").mkdir(exist_ok=True)
    (tmp_path / "Images").mkdir(exist_ok=True)
    instance = object.__new__(SafariBooks)
    instance.css_path = str(tmp_path / "Styles")
    instance.images_path = str(tmp_path / "Images")
    instance.book_chapters = [{"filename": "ch01.html", "title": "Chapter 1"}]
    instance.book_info = book_info
    instance.book_title = "Test Book"
    instance.book_id = "123"
    instance.cover = False
    return instance


class _NoCharsetResponse:
    """Mimics requests when the server sends `Content-Type: text/html` with no
    charset: `.encoding` falls back to ISO-8859-1 (RFC 2616 default), so `.text`
    decodes the UTF-8 body as Latin-1 while `.content` holds the real bytes."""

    def __init__(self, body_utf8, content_type="text/html"):
        self.status_code = 200
        self.headers = {"Content-Type": content_type}
        self.content = body_utf8
        if "charset" in content_type.lower():
            self.encoding = "utf-8"
        else:
            self.encoding = "ISO-8859-1"
        self.text = body_utf8.decode(self.encoding)


def make_get_html_instance(response):
    instance = object.__new__(SafariBooks)
    instance.filename = "chapter-2.html"
    instance.chapter_title = "t"
    instance.display = types.SimpleNamespace(
        info=lambda *a, **k: None, error=lambda *a, **k: None,
        exit=lambda msg: (_ for _ in ()).throw(AssertionError(msg)),
    )
    instance.requests_provider = lambda url, **kw: response
    return instance


def test_response_text_falls_back_to_utf8_on_unknown_declared_charset():
    # Regression guard: response.text tolerated a bogus charset (LookupError is
    # swallowed inside requests), so decoding by hand must not turn a mislabelled
    # Content-Type into a crash.
    body = "<html><body><p>You\u2019ll</p></body></html>".encode("utf-8")
    response = _NoCharsetResponse(body, "text/html; charset=bogus-xx")
    response.encoding = "bogus-xx"

    assert "You\u2019ll" in SafariBooks.response_text(response)


def test_response_text_docstring_has_no_control_characters():
    doc = SafariBooks.response_text.__doc__
    assert not any(0x80 <= ord(c) <= 0x9F for c in doc)


def test_get_ncx_authors_decodes_charsetless_ncx_as_utf8():
    # Same bug class as chapters: toc.ncx must not go through response.text.
    ncx = (
        "<ncx><docAuthor><text>Jos\u00e9 \u00d1and\u00fa</text></docAuthor></ncx>"
    ).encode("utf-8")
    instance = object.__new__(SafariBooks)
    instance.api_url = "https://example.com/api/v2/epubs/urn:orm:book:1/"
    instance.requests_provider = lambda url, **kw: _NoCharsetResponse(ncx, "application/x-dtbncx+xml")

    assert instance.get_ncx_authors() == [{"name": "Jos\u00e9 \u00d1and\u00fa"}]


def test_add_generic_font_family_appends_serif_fallback_to_unknown_font():
    result = SafariBooks.add_generic_font_family_to_stylesheet('p { font-family: "JansonTextLTStd"; margin: 0 }')
    assert 'font-family: "JansonTextLTStd", serif' in result
    assert "margin: 0" in result


def test_add_generic_font_family_picks_sans_serif_for_gothic_and_arial():
    css = 'a { font-family: "TradeGothicLTStd" } b { font-family: "ArialUnicodeMS" }'
    result = SafariBooks.add_generic_font_family_to_stylesheet(css)
    assert '"TradeGothicLTStd", sans-serif' in result
    assert '"ArialUnicodeMS", sans-serif' in result


def test_add_generic_font_family_picks_monospace_for_code_fonts():
    css = 'pre { font-family: "UbuntuMono" } code { font-family: Courier New } samp { font-family: "Lucida Console" }'
    result = SafariBooks.add_generic_font_family_to_stylesheet(css)
    assert result.count("monospace") == 3


def test_add_generic_font_family_leaves_existing_generic_alone():
    css = 'p { font-family: Foo, serif } q { font-family: "Bar", Monospace !important } r { font-family: inherit }'
    assert SafariBooks.add_generic_font_family_to_stylesheet(css) == css


def test_add_generic_font_family_keeps_important_flag_after_fallback():
    result = SafariBooks.add_generic_font_family_to_stylesheet("p { font-family: Foo !important }")
    assert "Foo, serif" in result
    assert "!important" in result


def test_add_generic_font_family_skips_font_face_descriptors():
    css = '@font-face { font-family: "Foo"; src: url(foo.woff) }'
    assert SafariBooks.add_generic_font_family_to_stylesheet(css) == css


def test_add_generic_font_family_handles_nested_media_rules_and_style_attr():
    css = "@media print { p { font-family: Foo } }"
    assert "Foo, serif" in SafariBooks.add_generic_font_family_to_stylesheet(css)
    assert "Foo, serif" in SafariBooks.add_generic_font_family_to_style_attr("font-family: Foo; margin: 0")


def test_strip_color_from_stylesheet_also_adds_generic_font_family():
    result = SafariBooks.strip_color_from_stylesheet('p { color: red; font-family: "JansonTextLTStd" }')
    assert "color" not in result
    assert '"JansonTextLTStd", serif' in result


def test_strip_inline_style_color_also_adds_generic_font_family():
    root = html.fromstring('<div><span style="color: red; font-family: Foo">hi</span></div>')
    SafariBooks.strip_inline_style_color(root)
    style = root.xpath("//span")[0].get("style")
    assert "color" not in style
    assert "Foo, serif" in style


FONT_CSS_URL = "https://learning.oreilly.com/api/v2/epubs/urn:orm:book:1/files/styles/book.css"


FONT_FACE_CSS = (
    '@font-face{font-family:"Foo";src:url(../fonts/Foo-Regular.otf);font-style:normal;font-weight:normal}'
    '@font-face{font-family:"Foo";src:url(../fonts/Foo-Bold.otf);font-weight:bold}'
)


def test_strip_color_keeps_font_face_body():
    result = SafariBooks.strip_color_from_stylesheet(FONT_FACE_CSS)
    assert result.count("src:url(../fonts/") == 2
    assert 'font-family:"Foo"' in result
    assert "font-weight:bold" in result


def test_strip_color_keeps_page_rule_body_but_drops_its_color():
    result = SafariBooks.strip_color_from_stylesheet("@page{margin:1em;color:red}")
    assert "margin:1em" in result
    assert "color" not in result


class _FakeFontResponse:
    def __init__(self, payload):
        self.payload = payload

    def iter_content(self, size):
        yield self.payload


def make_font_instance(tmp_path, responses):
    instance = object.__new__(SafariBooks)
    instance.fonts_path = str(tmp_path / "fonts")
    instance.fonts = {
        "https://x/fonts/A.otf": "A.otf",
        "https://x/fonts/B.ttf": "B.ttf",
    }
    warnings = []
    instance.display = types.SimpleNamespace(
        info=lambda *a, **k: None, warning=warnings.append, error=lambda *a, **k: None,
    )
    instance.warnings = warnings
    instance.requests_provider = lambda url, **kw: responses[url]
    return instance


def make_chapters_instance(results):
    """SafariBooks whose /epub-chapters/ endpoint answers with `results` (one page)."""
    instance = object.__new__(SafariBooks)
    instance.book_id = "9781718505049"
    instance.display = types.SimpleNamespace(exit=lambda msg: (_ for _ in ()).throw(AssertionError(msg)))
    payload = {"count": len(results), "next": None, "previous": None, "results": results}
    instance.requests_provider = lambda url, **kw: types.SimpleNamespace(json=lambda: payload)
    return instance


def chapter_result(name, title):
    return {
        "ourn": "urn:orm:book:9781718505049:chapter:xhtml%2f{0}.xhtml".format(name),
        "title": title,
        "content_url": "https://example.invalid/{0}.xhtml".format(name),
        "related_assets": {"stylesheets": [], "images": []},
    }


def chapter_names(instance):
    return [c["filename"] for c in instance.get_book_chapters()]


FXL_ID = "0642572230319"


def fxl_page():
    return load_fixture("fxl_page_0642572230319.xhtml")


def fxl_content(name="fxl_page_0642572230319.xhtml"):
    root = html.fromstring(load_fixture(name))
    return root.xpath("//div[@id='sbo-rt-content']")[0]


REFLOWABLE = (
    '<div id="sbo-rt-content"><section><h1 id="a">Title</h1>'
    '<p>Some <span id="term1" class="term">text</span> <span class="t-note">x</span></p>'
    '<div id="pagenote"></div><img src="Images/f.jpg" width="800" height="600"/>'
    '</section></div>'
)


def test_is_fixed_layout_page_detects_positioned_text_lines():
    assert SafariBooks.is_fixed_layout_page(fxl_content())


def test_is_fixed_layout_page_detects_image_only_pages():
    assert SafariBooks.is_fixed_layout_page(fxl_content("fxl_imageonly_page_0642572230319.xhtml"))


def test_is_fixed_layout_page_ignores_reflowable_markup():
    root = html.fromstring(REFLOWABLE)
    assert not SafariBooks.is_fixed_layout_page(root)


def test_detect_page_size_reads_publisher_stylesheet():
    css = load_fixture("fxl_stylesheet_head_0642572230319.css")
    assert SafariBooks.detect_page_size(css) == (770, 1017)


def test_detect_page_size_falls_back_to_default():
    assert SafariBooks.detect_page_size(".a{color:red}") == SafariBooks.DEFAULT_PAGE_SIZE


def test_fixed_layout_stylesheet_pins_page_image_to_canvas():
    css = SafariBooks.fixed_layout_stylesheet((770, 1017))
    assert "height:auto" not in css
    assert "max-width:none!important" in css
    assert "width:770px!important" in css and "height:1017px!important" in css
    # the image must sit inside the page's own stacking context, not behind <body>
    assert "isolation:isolate" in css
    assert "z-index:0!important" in css


def make_fxl_book(tmp_path, fixed=True, page_css=None):
    oebps = tmp_path / "OEBPS"
    (oebps / "Styles").mkdir(parents=True)
    (oebps / "Images").mkdir()
    (oebps / "xhtml").mkdir()
    (oebps / "Styles" / "Style00.css").write_text(
        page_css if page_css is not None else load_fixture("fxl_stylesheet_head_0642572230319.css")
    )
    (oebps / "Styles" / "Style_Base.css").write_text(SafariBooks.BASE_STYLE_CSS)
    (oebps / "xhtml" / "page008.xhtml").write_text(fxl_page())
    instance = object.__new__(SafariBooks)
    instance.BOOK_PATH = str(tmp_path)
    instance.css_path = str(oebps / "Styles")
    instance.images_path = str(oebps / "Images")
    instance.fonts_path = str(oebps / "fonts")
    instance.fixed_layout = fixed
    instance.book_id = FXL_ID
    instance.book_title = "Electronics for Kids"
    instance.book_info = {"isbn": "9781718503502", "authors": [{"name": "A Author"}]}
    instance.book_chapters = [{"filename": "xhtml/page008.html", "title": "About"}]
    instance.cover = False
    instance.display = types.SimpleNamespace(
        info=lambda *a, **k: None, log=lambda *a, **k: None, error=lambda *a, **k: None
    )
    return instance, oebps


def test_prepare_fixed_layout_is_a_noop_for_reflowable_books(tmp_path):
    instance, oebps = make_fxl_book(tmp_path, fixed=False)
    before = (oebps / "xhtml" / "page008.xhtml").read_text()
    instance.prepare_fixed_layout()
    assert (oebps / "Styles" / "Style_Base.css").read_text() == SafariBooks.BASE_STYLE_CSS
    assert (oebps / "xhtml" / "page008.xhtml").read_text() == before


def fxl_files_payload():
    return json.loads(load_fixture("fxl_files_0642572230319.json"))


OPF_NS = {"o": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def build_fxl_opf(tmp_path):
    from lxml import etree
    instance, oebps = make_fxl_book(tmp_path)
    (oebps / "Images" / "cover.jpg").write_bytes(make_png_bytes())
    (oebps / "fonts").mkdir()
    (oebps / "fonts" / "Avenir-Black.ttf").write_bytes(b"x")
    (oebps / "fonts" / "DogmaOT-Bold.otf").write_bytes(b"x")
    instance.cover = "cover.jpg"
    return etree.fromstring(instance.create_content_opf().encode("utf-8")), instance


def test_calibre_polish_is_skipped_for_fixed_layout_books(tmp_path):
    instance, _ = make_fxl_book(tmp_path)
    assert instance.should_polish(types.SimpleNamespace(no_optimize_images=False)) is False
    instance.fixed_layout = False
    assert instance.should_polish(types.SimpleNamespace(no_optimize_images=False)) is True
    assert instance.should_polish(types.SimpleNamespace(no_optimize_images=True)) is False


BAKE_SAMPLE = (
    "#sbo-rt-content .t{-webkit-transform-origin:top left;-webkit-transform:scale(.25);"
    "transform:scale(.25);position:absolute;white-space:nowrap}"
    "#sbo-rt-content #t1_8{left:211px;top:148px;letter-spacing:-.8px;word-spacing:.6px}"
    "#sbo-rt-content .s2_8{font-size:67.2px;font-family:Nunito;margin-top:-2px;color:rgb(35,31,32)}"
)


def css_declarations(css, selector):
    match = re.search(re.escape(selector) + r"\{([^{}]*)\}", css)
    assert match, "selector %s missing from %s" % (selector, css)
    return dict(item.split(":", 1) for item in match.group(1).split(";") if item.strip())


def test_bake_scale_multiplies_font_size_and_spacing_but_not_positions():
    baked = SafariBooks.bake_fixed_layout_scale(BAKE_SAMPLE)
    style = css_declarations(baked, "#sbo-rt-content .s2_8")
    assert float(style["font-size"][:-2]) == pytest.approx(16.8)
    assert float(style["margin-top"][:-2]) == pytest.approx(-0.5)
    assert style["font-family"] == "Nunito" and style["color"].startswith("rgb(35,31,32)")
    line = css_declarations(baked, "#sbo-rt-content #t1_8")
    assert line["left"] == "211px" and line["top"] == "148px"
    assert float(line["letter-spacing"][:-2]) == pytest.approx(-0.2)
    assert float(line["word-spacing"][:-2]) == pytest.approx(0.15)


def test_bake_scale_drops_the_transform_but_keeps_the_origin():
    baked = SafariBooks.bake_fixed_layout_scale(BAKE_SAMPLE)
    assert "scale(" not in baked
    rule = css_declarations(baked, "#sbo-rt-content .t")
    assert "transform" not in rule and "-webkit-transform" not in rule
    assert rule["position"] == "absolute" and rule["white-space"] == "nowrap"


def test_bake_scale_keeps_rotation_and_rescales_anisotropic_scale():
    css = (
        "#sbo-rt-content .t.m1_2{transform:matrix(.98,0,-.17,.98,0,0) scale(.25)}"
        "#sbo-rt-content .t.v1_4{transform:scale(.277,.25)}"
    )
    baked = SafariBooks.bake_fixed_layout_scale(css)
    assert "matrix(.98,0,-.17,.98,0,0)" in baked and "scale(.25)" not in baked
    stretch = css_declarations(baked, "#sbo-rt-content .t.v1_4")["transform"]
    assert stretch.startswith("scale(") and "1.108" in stretch


def test_bake_scale_leaves_font_faces_and_unrelated_rules_alone():
    css = '@font-face{font-family:"A";src:url(../fonts/A.ttf)}#sbo-rt-content p{margin:0;font-size:12px;color:red}'
    assert SafariBooks.bake_fixed_layout_scale(css) == css


def test_bake_scale_only_touches_text_line_rules_when_a_scale_is_present():
    # the scale rule makes the function do real work; the unrelated selectors around it must not change
    unrelated = '#sbo-rt-content p{font-size:12px;letter-spacing:2px;color:red}#sbo-rt-content .caption{margin-top:-2px}'
    baked = SafariBooks.bake_fixed_layout_scale(BAKE_SAMPLE + unrelated)
    assert baked.endswith(unrelated)
    assert css_declarations(baked, "#sbo-rt-content .s2_8")["font-size"] == "16.8px"


def test_bake_scale_is_idempotent():
    once = SafariBooks.bake_fixed_layout_scale(BAKE_SAMPLE)
    assert SafariBooks.bake_fixed_layout_scale(once) == once


def test_bake_scale_forces_text_colours_over_reader_theme_overrides():
    baked = SafariBooks.bake_fixed_layout_scale(BAKE_SAMPLE)
    assert css_declarations(baked, "#sbo-rt-content .s2_8")["color"] == "rgb(35,31,32)!important"
    assert SafariBooks.bake_fixed_layout_scale(baked) == baked


def test_fixed_layout_stylesheet_keeps_text_backgrounds_transparent_against_reader_overrides():
    css = SafariBooks.fixed_layout_stylesheet((770, 1017))
    # a reader's `body *{background-color:X!important}` (specificity 0,0,1) paints a box behind every line
    assert "#sbo-rt-content .t,#sbo-rt-content .t *{background-color:transparent!important;}" in css
