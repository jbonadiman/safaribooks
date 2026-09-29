"""The /files/ layer: listing, classification, path safety, link rewriting, chapter parsing."""
import pytest
from lxml import etree

from safaribooks import SafariBooks
from support import FakeApi, FakeResponse, files_entry, make_book

BOOK = "9781098168827"
FXL = "0642572230319"
XHTML = "application/xhtml+xml"


# ---------------------------------------------------------------- clean_book_path
@pytest.mark.parametrize("raw, expected", [
    ("xhtml/ch01.xhtml", "xhtml/ch01.xhtml"),
    ("./xhtml//ch01.xhtml", "xhtml/ch01.xhtml"),
    ("a/b/../c.css", "a/c.css"),
    ("\\styles\\a.css", "styles/a.css"),
    ("/abs/x.png", "abs/x.png"),
])
def test_clean_book_path_normalises(raw, expected):
    assert SafariBooks.clean_book_path(raw) == expected


@pytest.mark.parametrize("raw", ["../evil.xhtml", "a/../../evil", "..", ".", "", None, 7, "a\x00b"])
def test_clean_book_path_refuses_anything_that_escapes_or_is_not_a_path(raw):
    assert SafariBooks.clean_book_path(raw) is None


# ---------------------------------------------------------------- classify_file
@pytest.mark.parametrize("entry, expected", [
    ({"full_path": "content.opf", "media_type": "application/oebps-package+xml", "kind": "other_asset"}, "opf"),
    ({"full_path": "pkg/book.opf", "media_type": "text/plain", "kind": "other_asset"}, "opf"),
    ({"full_path": "toc.ncx", "media_type": "application/x-dtbncx+xml", "kind": "other_asset"}, "ncx"),
    ({"full_path": "xhtml/ch01.xhtml", "media_type": XHTML, "kind": "chapter"}, "chapter"),
    ({"full_path": "styles/a.css", "media_type": "text/css", "kind": "stylesheet"}, "stylesheet"),
    ({"full_path": "images/a.png", "media_type": "image/png", "kind": "image"}, "image"),
    ({"full_path": "images/a.webp", "media_type": "application/octet-stream", "kind": "other_asset"}, "image"),
    ({"full_path": "fonts/a.ttf", "media_type": "font/ttf", "kind": "font"}, "font"),
    # the API files real fonts under kind "other_asset" (see the fixed-layout capture)
    ({"full_path": "fonts/b.otf", "media_type": "font/otf", "kind": "other_asset"}, "font"),
    ({"full_path": "fonts/c.woff2", "media_type": "application/octet-stream", "kind": "other_asset"}, "font"),
    ({"full_path": "notes.txt", "media_type": "text/plain", "kind": "other_asset"}, "other"),
])
def test_classify_file(entry, expected):
    assert SafariBooks.classify_file(entry) == expected


def test_classify_file_agrees_with_the_real_fixed_layout_listing(load_fixture):
    kinds = {e["full_path"]: SafariBooks.classify_file(e) for e in load_fixture("fxl_files_0642572230319.json")["results"]}
    assert kinds == {
        "xhtml/cover.xhtml": "chapter",
        "styles/stylesheet_001-025.css": "stylesheet",
        "images/cover.jpg": "image",
        "fonts/Avenir-Black.ttf": "font",
        "fonts/DogmaOT-Bold.otf": "font",
    }


# ---------------------------------------------------------------- plan_files
def _listing(load_fixture, extra=()):
    entries = list(load_fixture("fxl_files_0642572230319.json")["results"])
    entries += [files_entry(FXL, "content.opf", "other_asset", "application/oebps-package+xml"),
                files_entry(FXL, "toc.ncx", "other_asset", "application/x-dtbncx+xml")]
    return entries + list(extra)


def test_plan_files_buckets_the_real_listing_and_records_opf_and_ncx(tmp_path, load_fixture):
    book = make_book(tmp_path, FXL)
    plan = book.plan_files(_listing(load_fixture))

    assert book.opf_path == "content.opf" and book.ncx_path == "toc.ncx"
    assert [e["path"] for e in plan["chapter"]] == ["xhtml/cover.xhtml"]
    assert [e["path"] for e in plan["font"]] == ["fonts/Avenir-Black.ttf", "fonts/DogmaOT-Bold.otf"]
    assert [e["path"] for e in plan["image"]] == ["images/cover.jpg"]
    assert [e["path"] for e in plan["documents"]] == ["content.opf", "toc.ncx", "xhtml/cover.xhtml"]


def test_plan_files_exits_when_the_listing_has_no_opf(tmp_path, load_fixture):
    book = make_book(tmp_path, FXL)
    with pytest.raises(SystemExit):
        book.plan_files(load_fixture("fxl_files_0642572230319.json")["results"])

    assert "no OPF" in book.display.of("exit")[0]


def test_plan_files_skips_unsafe_paths_and_duplicates(tmp_path, load_fixture):
    book = make_book(tmp_path, FXL)
    entries = _listing(load_fixture, [
        files_entry(FXL, "../escape.xhtml", "chapter", XHTML),
        dict(files_entry(FXL, "images/nourl.png", "image", "image/png"), url=""),
        files_entry(FXL, "images/cover.jpg", "image", "image/jpeg"),  # duplicate of a listed path
    ])
    plan = book.plan_files(entries)

    assert [e["path"] for e in plan["image"]] == ["images/cover.jpg"]
    assert not any(".." in e["path"] for kind in plan.values() for e in kind)
    assert len(book.display.of("warning")) == 2


def test_plan_stylesheets_is_sorted_and_stable():
    plan = {"stylesheet": [{"path": "styles/b.css"}, {"path": "styles/a.css"}]}
    assert SafariBooks.plan_stylesheets(plan) == ["styles/a.css", "styles/b.css"]


# ---------------------------------------------------------------- get_book_files (pagination)
def _page(entries, next_url=None):
    import json
    return FakeResponse(json.dumps({"results": entries, "next": next_url}), content_type="application/json")


def test_get_book_files_follows_next_links_until_the_end(tmp_path):
    book = make_book(tmp_path)
    first = [files_entry(BOOK, "a.xhtml", "chapter", XHTML)]
    second = [files_entry(BOOK, "b.xhtml", "chapter", XHTML)]
    pages = {"https://x/files/?limit=200": _page(first, "https://x/page2"), "https://x/page2": _page(second)}
    seen = []

    def provider(url, *args, **kwargs):
        seen.append(url)
        return pages.get(url) or pages[next(iter(pages))]

    book.api_url = "https://x/"
    book.requests_provider = provider
    assert [e["full_path"] for e in book.get_book_files()] == ["a.xhtml", "b.xhtml"]
    assert seen == ["https://x/files/?limit=200", "https://x/page2"]


def test_get_book_files_exits_on_an_error_body_an_empty_book_or_a_dead_connection(tmp_path):
    for response in (FakeResponse('{"detail":"nope"}', content_type="application/json"),
                     FakeResponse("not json"), _page([]), 0):
        book = make_book(tmp_path)
        book.requests_provider = lambda url, *a, _r=response, **k: _r
        with pytest.raises(SystemExit):
            book.get_book_files()


# ---------------------------------------------------------------- localize_api_links
API = "/api/v2/epubs/urn:orm:book:%s/files/" % BOOK


@pytest.mark.parametrize("referrer, expected_prefix", [
    ("cover.xhtml", ""),               # flat book: chapters at OEBPS root
    ("xhtml/ch01.xhtml", "../"),       # the usual xhtml/ + images/ + styles/ layout
    ("text/part1/ch01.xhtml", "../../"),
])
def test_localize_api_links_gives_one_dotdot_per_directory_level(referrer, expected_prefix):
    text = '<img src="%simages/a.png"/><link href="https://learning.oreilly.com%sstyles/b.css"/>' % (API, API)
    out = SafariBooks.localize_api_links(text, referrer, BOOK)

    assert 'src="%simages/a.png"' % expected_prefix in out
    assert 'href="%sstyles/b.css"' % expected_prefix in out
    assert "/api/v2/" not in out


def test_localize_api_links_leaves_other_books_alone():
    other = '<img src="/api/v2/epubs/urn:orm:book:9999999999999/files/images/a.png"/>'
    assert SafariBooks.localize_api_links(other, "xhtml/c.xhtml", BOOK) == other


# ---------------------------------------------------------------- injected anti-bot markup
INJECTED = ('<?xml version="1.0"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<script src="/akam/x.js"></script><link href="/akam/y.css" rel="stylesheet"/>'
            '<link href="../styles/keep.css" rel="stylesheet"/></head>'
            '<body><div id="sec-overlay"><p>challenge</p></div><p>caf\u00e9</p></body></html>')


def test_strip_injected_document_removes_only_the_injected_markup_and_keeps_the_doctype():
    out = SafariBooks.strip_injected_document(INJECTED)

    assert "<script" not in out and "sec-overlay" not in out and "/akam/" not in out
    assert "../styles/keep.css" in out and "caf\u00e9" in out and "<!DOCTYPE html>" in out
    etree.fromstring(out.encode("utf-8"))


def test_strip_injected_document_falls_back_to_patterns_when_the_page_is_not_xml():
    broken = '<html><head><script>x</script><link href="/akam/y.css"></head><body><p>a<br>b</body></html>'
    out = SafariBooks.strip_injected_document(broken)

    assert "<script" not in out and "/akam/" not in out and "a<br>b" in out


def test_strip_injected_document_returns_clean_input_untouched():
    clean = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>hi</p></body></html>'
    assert SafariBooks.strip_injected_document(clean) is clean


# ---------------------------------------------------------------- parse_chapter
def _chapter_book(tmp_path, **args):
    book = make_book(tmp_path, BOOK, **args)
    book.chapter_stylesheets = ["styles/book.css"]
    return book


SERVED = ('<script src="/akam/x.js"></script>'
          '<div id="sbo-rt-content"><h1>Chapter <em>One</em></h1>'
          '<p style="color: red; margin: 0">text</p>'
          '<pre data-type="programlisting" class="output"></pre>'
          '<img src="../images/fig1.png" alt=""/></div>')


def test_parse_chapter_returns_wellformed_xhtml_with_the_right_links(tmp_path):
    book = _chapter_book(tmp_path)
    page = book.parse_chapter(SERVED, "xhtml/ch01.xhtml")
    root = etree.fromstring(page.encode("utf-8"))
    ns = {"x": "http://www.w3.org/1999/xhtml"}

    assert root.xpath("string(//x:title)", namespaces=ns) == "Chapter One"
    assert [l.get("href") for l in root.xpath("//x:head/x:link", namespaces=ns)] == [
        "../styles/book.css", "../sb_styles/Style_Base.css"]
    assert root.xpath("boolean(//x:div[@id='sbo-rt-content'])", namespaces=ns)
    assert "<script" not in page and "/akam/" not in page


def test_parse_chapter_link_prefix_follows_the_chapters_depth(tmp_path):
    book = _chapter_book(tmp_path)
    flat = book.parse_chapter(SERVED, "ch01.xhtml")

    assert 'href="styles/book.css"' in flat and 'href="sb_styles/Style_Base.css"' in flat


def test_parse_chapter_strips_forced_colour_and_empty_output_blocks(tmp_path):
    page = _chapter_book(tmp_path).parse_chapter(SERVED, "xhtml/ch01.xhtml")

    assert "color" not in page and "margin: 0" in page
    assert 'class="output"' not in page


def test_parse_chapter_keeps_colour_when_css_optimisation_is_off(tmp_path):
    page = _chapter_book(tmp_path, no_optimize_css=True).parse_chapter(SERVED, "xhtml/ch01.xhtml")
    assert "color: red" in page


def test_parse_chapter_adds_the_kindle_stylesheet_last_only_when_asked(tmp_path):
    plain = _chapter_book(tmp_path).parse_chapter(SERVED, "xhtml/ch01.xhtml")
    kindle = _chapter_book(tmp_path / "k", kindle=True).parse_chapter(SERVED, "xhtml/ch01.xhtml")

    assert "Style_Kindle.css" not in plain
    assert kindle.rindex("Style_Kindle.css") > kindle.rindex("Style_Base.css")


def test_parse_chapter_wraps_a_document_that_lacks_the_content_wrapper(tmp_path):
    bare = "<html><body><h2>Loose</h2><p>x</p></body></html>"
    page = _chapter_book(tmp_path).parse_chapter(bare, "xhtml/ch01.xhtml")

    assert 'id="sbo-rt-content"' in page and "Loose" in page


def test_parse_chapter_flags_a_real_fixed_layout_page_and_keeps_its_colours(tmp_path, load_fixture):
    book = _chapter_book(tmp_path)
    served = load_fixture("fxl_page_0642572230319.xhtml")
    served = served.replace('<span id="t1_8" class="t s1_8"', '<span id="t1_8" class="t s1_8" style="color:#fff"')
    page = book.parse_chapter(served, "xhtml/page008.xhtml")

    assert book.fixed_layout is True
    assert "color:#fff" in page


def test_parse_chapter_leaves_a_reflowable_book_reflowable(tmp_path):
    book = _chapter_book(tmp_path)
    book.parse_chapter(SERVED, "xhtml/ch01.xhtml")
    assert book.fixed_layout is False


def test_parse_chapter_turns_svg_wrapped_covers_into_plain_images(tmp_path):
    served = ('<div id="sbo-rt-content"><svg xmlns="http://www.w3.org/2000/svg" '
              'xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="../images/cover.jpg"/></svg></div>')
    page = _chapter_book(tmp_path).parse_chapter(served, "xhtml/cover.xhtml")

    assert "<img" in page and 'src="../images/cover.jpg"' in page and "<svg" not in page


def test_parse_chapter_is_utf8_safe(tmp_path):
    served = '<div id="sbo-rt-content"><h1>Fundamentos de la arquitectura \u2014 2.\u00aa edici\u00f3n</h1></div>'
    page = _chapter_book(tmp_path).parse_chapter(served, "xhtml/ch01.xhtml")
    assert "2.\u00aa edici\u00f3n" in page


def test_parse_chapter_exits_on_unparseable_input(tmp_path):
    with pytest.raises(SystemExit):
        _chapter_book(tmp_path).parse_chapter("", "xhtml/ch01.xhtml")


# ---------------------------------------------------------------- book_link
def test_book_link_relativises_only_links_into_this_book(tmp_path):
    book = _chapter_book(tmp_path)
    mine = "https://learning.oreilly.com/library/view/x/%s/xhtml/ch02.xhtml#a" % BOOK
    other = "https://learning.oreilly.com/library/view/x/9999999999999/ch02.xhtml"

    assert book.book_link(mine, "xhtml/ch01.xhtml") == "../xhtml/ch02.xhtml#a"
    assert book.book_link(other, "xhtml/ch01.xhtml") == other
    assert book.book_link("mailto:a@b.c", "xhtml/ch01.xhtml") == "mailto:a@b.c"
    assert book.book_link("ch02.xhtml", "xhtml/ch01.xhtml") == "ch02.xhtml"


# ---------------------------------------------------------------- transport: retry / decoding via the new fetchers
def test_fetch_document_saves_a_served_chapter_as_a_full_page(tmp_path):
    book = _chapter_book(tmp_path)
    api = FakeApi()
    entry = dict(files_entry(BOOK, "xhtml/ch01.xhtml", "chapter", XHTML), path="xhtml/ch01.xhtml")
    api.serve(entry, SERVED.replace("../images/fig1.png", API + "images/fig1.png").encode("utf-8"))
    book.requests_provider = api.provider

    assert book.fetch_document(entry) is None
    saved = open(book.destination("xhtml/ch01.xhtml"), encoding="utf-8").read()
    assert saved.startswith("<?xml") and "../images/fig1.png" in saved and "/api/v2/" not in saved


def test_fetch_document_decodes_a_charsetless_response_as_utf8(tmp_path):
    book = _chapter_book(tmp_path)
    api = FakeApi()
    entry = dict(files_entry(BOOK, "xhtml/ch01.xhtml", "chapter", XHTML), path="xhtml/ch01.xhtml")
    body = '<div id="sbo-rt-content"><p>You\u2019ll see \u2588 and caf\u00e9</p></div>'.encode("utf-8")
    api.serve(entry, body, content_type="text/html")
    book.requests_provider = api.provider

    assert book.fetch_document(entry) is None
    assert "You\u2019ll see \u2588 and caf\u00e9" in open(book.destination("xhtml/ch01.xhtml"), encoding="utf-8").read()


def test_fetch_document_reports_http_errors_by_path_without_writing(tmp_path):
    book = _chapter_book(tmp_path)
    entry = dict(files_entry(BOOK, "xhtml/gone.xhtml", "chapter", XHTML), path="xhtml/gone.xhtml")
    book.requests_provider = FakeApi().provider

    assert book.fetch_document(entry) == "HTTP 404: xhtml/gone.xhtml"
    assert not __import__("os").path.exists(book.destination("xhtml/gone.xhtml"))


def test_fetch_document_resumes_and_still_detects_fixed_layout_from_the_page_on_disk(tmp_path, load_fixture):
    book = _chapter_book(tmp_path)
    entry = dict(files_entry(BOOK, "xhtml/page008.xhtml", "chapter", XHTML), path="xhtml/page008.xhtml")
    book.save_text("xhtml/page008.xhtml", load_fixture("fxl_page_0642572230319.xhtml"))
    book.requests_provider = lambda *a, **k: pytest.fail("a page already on disk must not be fetched again")

    assert book.fetch_document(entry) is None
    assert book.fixed_layout is True


def test_run_parallel_collects_errors_and_survives_a_crashing_worker(tmp_path):
    book = _chapter_book(tmp_path)

    def work(item):
        if item["path"] == "boom":
            raise RuntimeError("worker died")
        return "bad: " + item["path"] if item["path"] == "bad" else None

    errors = book.run_parallel(work, [{"path": p} for p in ("ok", "bad", "boom")])
    assert sorted(errors) == ["RuntimeError: worker died (boom)", "bad: bad"]
    assert book.run_parallel(work, []) == []


def test_abort_on_errors_exits_only_when_there_are_errors(tmp_path):
    book = _chapter_book(tmp_path)
    book.abort_on_errors([], "image(s)")
    with pytest.raises(SystemExit):
        book.abort_on_errors(["HTTP 500: x"], "image(s)")

    assert "run the same command again" in book.display.of("exit")[0]


# The injected markup can also sit INSIDE the content wrapper, where extracting the wrapper does not
# drop it and only strip_injected() can. (A script outside the wrapper is lost either way, so the
# sample above cannot tell a working strip from a broken one.)
INSIDE = ('<div id="sbo-rt-content"><script>track()</script><link href="/akam/y.css" rel="stylesheet"/>'
          '<div id="sec-overlay"><p>challenge</p></div><p>real text</p></div>')


def test_parse_chapter_strips_injected_markup_that_sits_inside_the_wrapper(tmp_path):
    page = _chapter_book(tmp_path).parse_chapter(INSIDE, "xhtml/ch01.xhtml")

    assert "real text" in page
    assert "<script" not in page and "track()" not in page
    assert "sec-overlay" not in page and "challenge" not in page
    assert "/akam/" not in page
    etree.fromstring(page.encode("utf-8"))
