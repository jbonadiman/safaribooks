"""End to end, offline: a fake /files/ API -> plan -> download_and_build -> a real EPUB, then read it back."""
import zipfile

import pytest
from lxml import etree

from support import FakeApi, files_entry, make_book, png_bytes

OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
XHTML = "application/xhtml+xml"


@pytest.fixture(autouse=True)
def no_calibre(monkeypatch):
    # The suite must not depend on (or be slowed by) a local Calibre install.
    monkeypatch.setattr("safaribooks.shutil.which", lambda name: None)


def serve_all(api, book_id, spec):
    """spec: {path: (kind, media, body)} -> the listing entries, with every file served."""
    entries = []
    for path, (kind, media, body) in spec.items():
        e = files_entry(book_id, path, kind, media)
        entries.append(e)
        api.serve(e, body)
    return entries


def run(book, entries, api):
    book.requests_provider = api.provider
    book.plan = book.plan_files(entries)
    book.chapter_stylesheets = book.plan_stylesheets(book.plan)
    book.download_and_build()
    return zipfile.ZipFile(book.BOOK_PATH + "/" + book.book_id + ".epub")


# ---------------------------------------------------------------- a small reflowable book
BOOK = "9781098168827"
API = "/api/v2/epubs/urn:orm:book:%s/files/" % BOOK

OPF = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="i">'
       '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="i">urn:isbn:%s</dc:identifier>'
       '<dc:title>Old English Title</dc:title><dc:language>en</dc:language><meta name="cover" content="cov"/>'
       '</metadata><manifest>'
       '<item id="c1" href="xhtml/ch01.xhtml" media-type="application/xhtml+xml"/>'
       '<item id="c2" href="xhtml/ch02.xhtml" media-type="application/xhtml+xml"/>'
       '<item id="cov" href="images/cover.png" media-type="image/png"/>'
       '<item id="fig" href="images/fig1.png" media-type="image/png"/>'
       '<item id="orp" href="images/orphan.png" media-type="image/png"/>'
       '<item id="css" href="styles/book.css" media-type="text/css"/>'
       '<item id="fnt" href="fonts/body.ttf" media-type="font/ttf"/>'
       '</manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>' % BOOK)

NCX = ('<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><docAuthor><text>Jane Doe</text></docAuthor><navMap>'
       '<navPoint id="a" playOrder="1"><navLabel><text>One</text></navLabel><content src="xhtml/ch01.xhtml"/>'
       '</navPoint></navMap></ncx>')


def chapter(title, image=None):
    img = '<img src="%simages/%s"/>' % (API, image) if image else ""
    return ('<script src="/akam/t.js"></script><div id="sbo-rt-content"><h1>%s</h1>'
            '<p style="color:red;margin:0">body</p>%s</div>' % (title, img))


REFLOWABLE = {
    "content.opf": ("other_asset", "application/oebps-package+xml", OPF.encode()),
    "toc.ncx": ("other_asset", "application/x-dtbncx+xml", NCX.encode()),
    "xhtml/ch01.xhtml": ("chapter", XHTML, chapter("Chapter One", "fig1.png").encode()),
    "xhtml/ch02.xhtml": ("chapter", XHTML, chapter("Chapter Two").encode()),
    "styles/book.css": ("stylesheet", "text/css",
                        ("p{color:#333}@font-face{font-family:B;src:url(../fonts/body.ttf)}").encode()),
    "fonts/body.ttf": ("font", "font/ttf", b"FONTDATA"),
    "images/cover.png": ("image", "image/png", png_bytes("blue")),
    "images/fig1.png": ("image", "image/png", png_bytes("green")),
    "images/orphan.png": ("image", "image/png", png_bytes("black")),
}


@pytest.fixture
def reflowable(tmp_path):
    book, api = make_book(tmp_path, BOOK), FakeApi()
    book.book_info = {"title": "T\u00edtulo Nuevo", "language": "es", "authors": [{"name": "Jane Doe"}],
                      "publishers": [{"name": "Editorial"}]}
    return book, api, serve_all(api, BOOK, REFLOWABLE)


def test_a_reflowable_book_becomes_a_valid_epub_with_the_publishers_structure(reflowable):
    book, api, entries = reflowable
    epub = run(book, entries, api)
    names = epub.namelist()

    assert epub.testzip() is None
    assert names[0] == "mimetype" and epub.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
    assert {"META-INF/container.xml", "OEBPS/content.opf", "OEBPS/xhtml/ch01.xhtml", "OEBPS/xhtml/ch02.xhtml",
            "OEBPS/styles/book.css", "OEBPS/fonts/body.ttf", "OEBPS/sb_styles/Style_Base.css"} <= set(names)
    # the publisher's layout is kept, not flattened into Images/ + Styles/ + one big file
    assert not [n for n in names if n.startswith("OEBPS/Images") or n.startswith("OEBPS/Styles")]


def test_the_opf_is_patched_and_every_manifest_item_exists_in_the_zip(reflowable):
    book, api, entries = reflowable
    epub = run(book, entries, api)
    opf = etree.fromstring(epub.read("OEBPS/content.opf"))
    hrefs = [i.get("href") for i in opf.findall("opf:manifest/opf:item", OPF_NS)]

    assert opf.find("opf:metadata/dc:title", OPF_NS).text == "T\u00edtulo Nuevo"
    assert opf.find("opf:metadata/dc:language", OPF_NS).text == "es"
    assert opf.find("opf:metadata/dc:creator", OPF_NS).text == "Jane Doe"
    assert [h for h in hrefs if "OEBPS/" + h not in epub.namelist()] == []
    ids = {i.get("id") for i in opf.findall("opf:manifest/opf:item", OPF_NS)}
    assert opf.find("opf:metadata/opf:meta[@name='cover']", OPF_NS).get("content") in ids
    spine = [r.get("idref") for r in opf.findall("opf:spine/opf:itemref", OPF_NS)]
    assert spine == ["c1", "c2"]  # the publisher's reading order, untouched


def test_images_are_jpegs_the_orphan_is_gone_and_the_cover_survives(reflowable):
    book, api, entries = reflowable
    epub = run(book, entries, api)
    images = sorted(n for n in epub.namelist() if n.startswith("OEBPS/images/"))

    assert images == ["OEBPS/images/cover.jpg", "OEBPS/images/fig1.jpg"]
    assert b'src="../images/fig1.jpg"' in epub.read("OEBPS/xhtml/ch01.xhtml")
    opf = epub.read("OEBPS/content.opf").decode()
    assert "orphan" not in opf and 'href="images/fig1.jpg"' in opf


def test_chapters_are_clean_wellformed_xhtml(reflowable):
    book, api, entries = reflowable
    epub = run(book, entries, api)

    for name in ("OEBPS/xhtml/ch01.xhtml", "OEBPS/xhtml/ch02.xhtml"):
        page = epub.read(name)
        etree.fromstring(page)
        assert b"<script" not in page and b"/akam/" not in page and b"/api/v2/" not in page
        assert b"color:red" not in page and b"margin:0" in page
    assert b"../styles/book.css" in epub.read("OEBPS/xhtml/ch01.xhtml")
    assert b"#333" not in epub.read("OEBPS/styles/book.css")


def test_only_the_fonts_a_stylesheet_uses_are_shipped(reflowable):
    book, api, entries = reflowable
    epub = run(book, entries, api)

    assert "OEBPS/fonts/body.ttf" in epub.namelist()
    assert epub.read("OEBPS/fonts/body.ttf") == b"FONTDATA"


def test_a_failed_image_stops_the_build_and_a_rerun_resumes_without_refetching(reflowable):
    book, api, entries = reflowable
    fig_url = [e for e in entries if e["full_path"] == "images/fig1.png"][0]["url"]
    good = api.routes[fig_url]
    api.routes[fig_url] = (500, b"", "text/plain")
    book.requests_provider = api.provider
    book.plan = book.plan_files(entries)
    book.chapter_stylesheets = book.plan_stylesheets(book.plan)
    with pytest.raises(SystemExit):
        book.download_and_build()

    api.routes[fig_url] = good
    api.calls.clear()
    book.fixed_layout = False
    book.download_and_build()

    assert api.calls == [fig_url]  # only the one that failed comes over the wire again
    assert zipfile.ZipFile(book.BOOK_PATH + "/" + BOOK + ".epub").testzip() is None


def test_no_optimize_images_mirrors_the_publishers_images_untouched(tmp_path):
    book, api = make_book(tmp_path, BOOK, no_optimize_images=True), FakeApi()
    epub = run(book, serve_all(api, BOOK, REFLOWABLE), api)
    images = sorted(n for n in epub.namelist() if n.startswith("OEBPS/images/"))

    assert images == ["OEBPS/images/cover.png", "OEBPS/images/fig1.png", "OEBPS/images/orphan.png"]


# ---------------------------------------------------------------- a fixed-layout book from the real captures
FXL = "0642572230319"


def test_a_fixed_layout_book_is_declared_pre_paginated_and_keeps_its_pages(tmp_path, load_fixture):
    book, api = make_book(tmp_path, FXL), FakeApi()
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="i">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="i">x</dc:identifier>'
           '<dc:title>t</dc:title><dc:language>en</dc:language></metadata><manifest>'
           '<item id="p8" href="xhtml/page008.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="css" href="styles/stylesheet_001-025.css" media-type="text/css"/></manifest>'
           '<spine><itemref idref="p8"/></spine></package>')
    spec = {
        "content.opf": ("other_asset", "application/oebps-package+xml", opf.encode()),
        "toc.ncx": ("other_asset", "application/x-dtbncx+xml", NCX.replace("xhtml/ch01", "xhtml/page008").encode()),
        "xhtml/page008.xhtml": ("chapter", XHTML, load_fixture("fxl_page_0642572230319.xhtml").encode()),
        "styles/stylesheet_001-025.css": ("stylesheet", "text/css",
                                          load_fixture("fxl_stylesheet_head_0642572230319.css").encode()),
    }
    epub = run(book, serve_all(api, FXL, spec), api)
    root = etree.fromstring(epub.read("OEBPS/content.opf"))
    props = {m.get("property"): m.text for m in root.findall("opf:metadata/opf:meta", OPF_NS) if m.get("property")}

    assert book.fixed_layout is True and root.get("version") == "3.0"
    assert props["rendition:layout"] == "pre-paginated"
    assert "OEBPS/nav.xhtml" in epub.namelist()  # built from the NCX: EPUB 3 requires one
    assert b'name="viewport"' in epub.read("OEBPS/xhtml/page008.xhtml")
    assert b"scale(.25)" not in epub.read("OEBPS/styles/stylesheet_001-025.css").replace(b" ", b"")


def test_a_fixed_layout_book_keeps_its_text_colours(tmp_path, load_fixture):
    book, api = make_book(tmp_path, FXL), FakeApi()
    css = "p{color:#fff}"
    opf = ('<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><metadata/><manifest>'
           '<item id="p8" href="xhtml/page008.xhtml" media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="p8"/></spine></package>')
    spec = {
        "content.opf": ("other_asset", "application/oebps-package+xml", opf.encode()),
        "toc.ncx": ("other_asset", "application/x-dtbncx+xml", NCX.replace("xhtml/ch01", "xhtml/page008").encode()),
        "xhtml/page008.xhtml": ("chapter", XHTML, load_fixture("fxl_page_0642572230319.xhtml").encode()),
        "styles/s.css": ("stylesheet", "text/css", css.encode()),
    }
    # chapters are fetched before stylesheets, so the flag is set by the time the CSS is processed
    epub = run(book, serve_all(api, FXL, spec), api)

    assert b"#fff" in epub.read("OEBPS/styles/s.css")


def test_catalogue_metadata_reaches_the_finished_epub(reflowable):
    # A No Starch Press OPF says "No Starch Press Inc." and has no synopsis, subjects or date; the
    # catalogue has all of them, and readers showed those before the /files/ rebuild.
    book, api, entries = reflowable
    book.book_info.update({
        "publishers": [{"name": "No Starch Press"}],
        "description": "<span><div><p>A synopsis from the catalogue.</p></div></span>",
        "subjects": [{"name": "Python"}, {"name": "Machine Learning"}],
        "issued": "2024-04-16",
    })
    for i, entry in enumerate(entries):
        if entry["full_path"] == "content.opf":
            body = OPF.encode().replace(b"</metadata>", b"<dc:publisher>No Starch Press Inc.</dc:publisher></metadata>")
            api.serve(entry, body)

    epub = run(book, entries, api)
    opf = etree.fromstring(epub.read("OEBPS/content.opf"))
    text = lambda tag: [e.text for e in opf.findall("opf:metadata/dc:" + tag, OPF_NS)]

    assert text("publisher") == ["No Starch Press"]
    assert text("description") == ["<span><div><p>A synopsis from the catalogue.</p></div></span>"]
    assert text("subject") == ["Python", "Machine Learning"]
    assert text("date") == ["2024-04-16"]
