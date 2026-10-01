"""A title page and a copyright page that share one chapter file must become two spine pages."""
import zipfile

import pytest
from lxml import etree

from safaribooks import SafariBooks
from support import FakeApi, files_entry, make_book, png_bytes

EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
XHTML = "application/xhtml+xml"
BOOK = "9781394270712"

# The shape a real Wiley/Dummies f01 chapter has after parse_chapter(): wrapper, two sibling sections,
# the inline page break on the title paragraph, an empty anchor span opening the copyright section.
PAGE = (
    '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">\n'
    '<head>\n<meta charset="utf-8"/>\n<title>f01</title>\n'
    '<link href="sb_styles/Style_Base.css" rel="stylesheet" type="text/css" />\n</head>\n'
    '<body><div id="sbo-rt-content">'
    '<section class="titlePage" epub:type="titlepage">\n'
    '<p id="titlepage1" style="text-align: center;page-break-after: always;">'
    '<img src="images/titlepg.jpg" alt="Title Page"/></p>\n</section>\n'
    '<section class="copyright" epub:type="copyright-page"><span id="f01-sec-0001"/>\n'
    '<p id="f01-para-0003" class="Copyright-Text-Title"><b>Placeholder Title</b></p>\n'
    '<p id="f01-para-0004" class="Copyright-Text">Placeholder rights <a href="#titlepage1">back</a></p>\n'
    '</section>\n</div></body>\n</html>'
).encode("utf-8")


def sections(page):
    root = etree.fromstring(page)
    wrapper = root.xpath("//*[@id='sbo-rt-content']")[0]
    return [c.get(EPUB_TYPE) for c in wrapper if isinstance(c.tag, str)]


def test_a_title_page_followed_by_a_copyright_page_is_split_in_two():
    first, second, stayed, moved = SafariBooks.split_before_copyright(PAGE)

    assert sections(first) == ["titlepage"]
    assert sections(second) == ["copyright-page"]
    assert stayed == {"titlepage1"} and moved == {"f01-sec-0001", "f01-para-0003", "f01-para-0004"}
    for half in (first, second):
        assert b"<!DOCTYPE html>" in half and b'href="sb_styles/Style_Base.css"' in half


def test_a_page_that_already_opens_with_the_copyright_page_is_left_alone():
    page = PAGE.replace(b'epub:type="titlepage"', b'epub:type="frontmatter"')
    only_copyright = page.split(b"<section")[0] + b"<section" + page.split(b"<section")[2]

    assert SafariBooks.split_before_copyright(only_copyright) is None


@pytest.mark.parametrize("decoy", [b"copyright-pages", b"copyright", b"not-copyright-page"])
def test_only_the_exact_copyright_page_type_splits(decoy):
    decoyed = PAGE.replace(b'epub:type="copyright-page"', b'epub:type="%s"' % decoy)

    assert SafariBooks.split_before_copyright(decoyed) is None


def test_a_copyright_page_nested_inside_another_section_is_not_split():
    nested = PAGE.replace(b'<section class="copyright"', b'<div><section class="copyright"') \
                 .replace(b"</section>\n</div></body>", b"</section></div>\n</div></body>")

    assert SafariBooks.split_before_copyright(nested) is None


def retarget(text, base, moved=("m1",), stayed=("s1",)):
    return SafariBooks.retarget_fragments(text, base, "xhtml/f01.xhtml", "xhtml/f01-copyright.xhtml",
                                          set(moved), set(stayed))


def test_links_into_the_moved_half_point_at_the_new_file():
    assert retarget('<a href="f01.xhtml#m1">', "xhtml/ch02.xhtml") == '<a href="f01-copyright.xhtml#m1">'
    assert retarget('<a href="../xhtml/f01.xhtml#m1">', "xhtml/ch02.xhtml") == '<a href="f01-copyright.xhtml#m1">'
    assert retarget('<a href="xhtml/f01.xhtml#m1">', "toc.ncx") == '<a href="xhtml/f01-copyright.xhtml#m1">'


def test_links_into_the_half_that_stayed_or_to_other_files_are_untouched():
    assert retarget('<a href="f01.xhtml#s1">', "xhtml/ch02.xhtml") == '<a href="f01.xhtml#s1">'
    assert retarget('<a href="f01.xhtml">', "xhtml/ch02.xhtml") == '<a href="f01.xhtml">'
    assert retarget('<a href="ch03.xhtml#m1">', "xhtml/ch02.xhtml") == '<a href="ch03.xhtml#m1">'
    assert retarget('<a href="f01.xhtml#unknown">', "xhtml/ch02.xhtml") == '<a href="f01.xhtml#unknown">'
    assert retarget('<a href="#m1">', "xhtml/ch02.xhtml") == '<a href="#m1">'


def test_same_document_links_crossing_the_split_gain_a_file_name():
    assert retarget('<a href="#m1">', "xhtml/f01.xhtml") == '<a href="f01-copyright.xhtml#m1">'
    assert retarget('<a href="#s1">', "xhtml/f01-copyright.xhtml") == '<a href="f01.xhtml#s1">'
    assert retarget('<a href="#m1">', "xhtml/f01-copyright.xhtml") == '<a href="#m1">'
    assert retarget('<a href="f01.xhtml#m1">', "xhtml/f01-copyright.xhtml") == '<a href="#m1">'


OPF = (
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="i"><metadata/>'
    '<manifest><item id="Af01" href="xhtml/f01.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="Ac00" href="xhtml/c00.xhtml" media-type="application/xhtml+xml"/></manifest>'
    '<spine><itemref idref="Af01"/><itemref idref="Ac00"/></spine></package>'
).encode()


def test_the_new_page_enters_the_manifest_and_the_spine_right_after_the_old_one():
    patched = SafariBooks.add_spine_page_after(OPF, "content.opf", "xhtml/f01.xhtml", "xhtml/f01-copyright.xhtml")
    root = etree.fromstring(patched)
    items = [(i.get("id"), i.get("href")) for i in root.findall("opf:manifest/opf:item", OPF_NS)]

    assert items[1][1] == "xhtml/f01-copyright.xhtml" and items[1][0] not in ("Af01", "Ac00")
    spine = [r.get("idref") for r in root.findall("opf:spine/opf:itemref", OPF_NS)]
    assert spine == ["Af01", items[1][0], "Ac00"]


def test_an_opf_that_does_not_list_the_page_is_returned_untouched():
    assert SafariBooks.add_spine_page_after(OPF, "content.opf", "xhtml/zzz.xhtml", "xhtml/zzz-copyright.xhtml") == OPF


# --------------------------------------------------------------- through the whole pipeline
BOOK_OPF = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="i">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="i">urn:isbn:%s</dc:identifier>'
    '<dc:title>T</dc:title><dc:language>en</dc:language></metadata><manifest>'
    '<item id="Af01" href="f01.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="Ac00" href="c00.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="img" href="images/titlepg.png" media-type="image/png"/>'
    '</manifest><guide><reference type="copyright-page" title="Copyright" href="f01.xhtml#f01-sec-0001"/></guide>'
    '<spine><itemref idref="Af01"/><itemref idref="Ac00"/></spine></package>' % BOOK
).encode()

BOOK_NCX = (
    '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
    '<navPoint id="n1" playOrder="1"><navLabel><text>Title Page</text></navLabel><content src="f01.xhtml#titlepage1"/>'
    '</navPoint><navPoint id="n2" playOrder="2"><navLabel><text>Copyright</text></navLabel>'
    '<content src="f01.xhtml#f01-sec-0001"/></navPoint><navPoint id="n3" playOrder="3"><navLabel><text>Intro</text>'
    '</navLabel><content src="c00.xhtml"/></navPoint></navMap></ncx>'
).encode()

SERVED_F01 = (
    '<div id="sbo-rt-content"><section class="titlePage" epub:type="titlepage">'
    '<p id="titlepage1" style="text-align:center;page-break-after:always"><img src="images/titlepg.png"/></p></section>'
    '<section class="copyright" epub:type="copyright-page"><span id="f01-sec-0001"/>'
    '<p id="f01-para-0003">Placeholder rights <a href="c00.xhtml#intro">next</a></p></section></div>'
)
SERVED_C00 = ('<div id="sbo-rt-content"><h1 id="intro">Intro</h1>'
              '<p><a href="f01.xhtml#f01-sec-0001">rights</a></p></div>')


@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.setattr("safaribooks.shutil.which", lambda name: None)
    book, api = make_book(tmp_path, BOOK), FakeApi()
    spec = {
        "content.opf": ("other_asset", "application/oebps-package+xml", BOOK_OPF),
        "toc.ncx": ("other_asset", "application/x-dtbncx+xml", BOOK_NCX),
        "f01.xhtml": ("chapter", XHTML, SERVED_F01.encode()),
        "c00.xhtml": ("chapter", XHTML, SERVED_C00.encode()),
        "images/titlepg.png": ("image", "image/png", png_bytes("white")),
    }
    entries = []
    for path, (kind, media, body) in spec.items():
        entry = files_entry(BOOK, path, kind, media)
        entries.append(entry)
        api.serve(entry, body)

    book.requests_provider = api.provider
    book.plan = book.plan_files(entries)
    book.chapter_stylesheets = book.plan_stylesheets(book.plan)
    book.download_and_build()
    return zipfile.ZipFile(book.BOOK_PATH + "/" + BOOK + ".epub")


def test_the_finished_epub_reads_title_page_then_copyright_page_then_the_rest(built):
    opf = etree.fromstring(built.read("OEBPS/content.opf"))
    manifest = {i.get("id"): i.get("href") for i in opf.findall("opf:manifest/opf:item", OPF_NS)}
    order = [manifest[r.get("idref")] for r in opf.findall("opf:spine/opf:itemref", OPF_NS)]

    assert order == ["f01.xhtml", "f01-copyright.xhtml", "c00.xhtml"]
    assert sections(built.read("OEBPS/f01.xhtml")) == ["titlepage"]
    assert sections(built.read("OEBPS/f01-copyright.xhtml")) == ["copyright-page"]


def test_the_toc_guide_and_links_follow_the_moved_copyright_page(built):
    ncx = etree.fromstring(built.read("OEBPS/toc.ncx"))
    srcs = [c.get("src") for c in ncx.findall(".//n:content", NCX_NS)]
    assert srcs == ["f01.xhtml#titlepage1", "f01-copyright.xhtml#f01-sec-0001", "c00.xhtml"]

    assert b'href="f01-copyright.xhtml#f01-sec-0001"' in built.read("OEBPS/content.opf")
    assert b'href="f01-copyright.xhtml#f01-sec-0001"' in built.read("OEBPS/c00.xhtml")
    assert b'href="c00.xhtml#intro"' in built.read("OEBPS/f01-copyright.xhtml")


def test_every_manifest_item_exists_and_the_split_pages_parse(built):
    opf = etree.fromstring(built.read("OEBPS/content.opf"))
    hrefs = [i.get("href") for i in opf.findall("opf:manifest/opf:item", OPF_NS)]

    assert [h for h in hrefs if "OEBPS/" + h not in built.namelist()] == []
    for name in ("OEBPS/f01.xhtml", "OEBPS/f01-copyright.xhtml"):
        etree.fromstring(built.read(name))
    assert b'src="images/titlepg.jpg"' in built.read("OEBPS/f01.xhtml")


def test_an_unknown_fragment_aimed_at_the_new_file_is_left_alone():
    assert retarget('<a href="f01-copyright.xhtml#unknown">', "xhtml/ch02.xhtml") == \
        '<a href="f01-copyright.xhtml#unknown">'
    assert retarget('<a href="f01-copyright.xhtml#s1">', "xhtml/ch02.xhtml") == '<a href="f01.xhtml#s1">'


def test_patching_the_opf_twice_adds_the_page_once():
    once = SafariBooks.add_spine_page_after(OPF, "content.opf", "xhtml/f01.xhtml", "xhtml/f01-copyright.xhtml")
    twice = SafariBooks.add_spine_page_after(once, "content.opf", "xhtml/f01.xhtml", "xhtml/f01-copyright.xhtml")

    assert twice == once
    assert once.count(b"f01-copyright.xhtml") == 1


def test_a_fixed_layout_book_is_never_split(tmp_path, monkeypatch):
    book = make_book(tmp_path, BOOK, no_optimize_images=True)
    book.fixed_layout = True
    calls = []
    for name in ("collect_documents", "collect_css", "collect_fonts", "collect_images", "prepare_fixed_layout",
                 "create_epub"):
        monkeypatch.setattr(book, name, lambda: None)
    monkeypatch.setattr(book, "split_front_matter", lambda: calls.append("split"))
    book.plan = {"documents": [], "stylesheet": []}

    book.download_and_build()

    assert calls == []
    book.fixed_layout = False
    book.download_and_build()
    assert calls == ["split"]
