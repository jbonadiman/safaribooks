"""Ledger rows that had no direct test on the /files/ pipeline.

* %2f / percent-encoded paths (old crawl bug: undecoded separators produced a spineless EPUB)
* image aspect ratio (height:auto in the base stylesheet)
* covers come from the publisher's OPF only, never from a chapter whose title contains "cover"
"""
import posixpath
import re

import pytest

from safaribooks import SafariBooks
from support import make_book


# ------------------------------------------------------------------ percent-encoded paths
@pytest.mark.parametrize("base, value, expected", [
    ("OEBPS/ch01.xhtml", "images/my%20pic.png", "OEBPS/images/my pic.png"),
    ("OEBPS/ch01.xhtml", "images%2Ffig1.png", "OEBPS/images/fig1.png"),
    ("OEBPS/xhtml/ch01.xhtml", "../images/a%2fb.png", "OEBPS/images/a/b.png"),
    ("OEBPS/ch01.xhtml", "ch02.xhtml%23sec1", "OEBPS/ch02.xhtml#sec1"),
])
def test_resolve_local_decodes_percent_escapes(base, value, expected):
    assert SafariBooks.resolve_local(base, value) == expected


def test_resolve_local_ignores_the_fragment_and_query():
    assert SafariBooks.resolve_local("OEBPS/ch01.xhtml", "ch02.xhtml#top") == "OEBPS/ch02.xhtml"
    assert SafariBooks.resolve_local("OEBPS/ch01.xhtml", "img.png?v=2") == "OEBPS/img.png"


@pytest.mark.parametrize("value", [
    "../../etc/passwd", "..%2f..%2fetc/passwd", "/absolute/path.png",
    "https://example.com/x.png", "//cdn.example.com/x.png", "data:image/png;base64,AAAA",
    "mailto:a@b.c", "javascript:alert(1)", "#anchor", "", None,
])
def test_resolve_local_refuses_anything_that_leaves_the_book(value):
    assert SafariBooks.resolve_local("OEBPS/ch01.xhtml", value) is None


# ------------------------------------------------------------------ aspect ratio
def test_base_stylesheet_keeps_the_image_aspect_ratio():
    css = SafariBooks.BASE_STYLE_CSS.replace(" ", "")

    # a fixed height would squash a wide image once max-width shrinks it
    assert "img{height:auto!important;max-width:100%!important;}" in css


def test_base_stylesheet_gives_code_blocks_room_between_lines():
    match = re.search(r"#sbo-rt-content pre\{([^}]*)\}", SafariBooks.BASE_STYLE_CSS)

    # the publisher's line-height:1 clips lines when a reader paints a box per token
    assert match is not None
    line_height = re.search(r"line-height:\s*([\d.]+)\s*!important", match.group(1))
    assert line_height is not None
    assert float(line_height.group(1)) >= 1.2


def test_base_stylesheet_gives_headings_room_between_lines():
    match = re.search(r"((?:#sbo-rt-content h[1-6],?)+)\{([^}]*)\}", SafariBooks.BASE_STYLE_CSS)

    assert match is not None
    assert {f"h{n}" for n in range(1, 7)} == set(re.findall(r"h[1-6]", match.group(1)))
    line_height = re.search(r"line-height:\s*([\d.]+)\s*!important", match.group(2))
    assert line_height is not None
    assert float(line_height.group(1)) >= 1.2


def test_base_stylesheet_is_written_into_every_book(tmp_path):
    book = make_book(tmp_path)
    book.create_dirs()

    written = open(posixpath.join(book.css_path, "Style_Base.css"), encoding="utf-8").read()
    assert written == SafariBooks.BASE_STYLE_CSS


# ------------------------------------------------------------------ covers
OPF_TEMPLATE = (
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata>{meta}</metadata>'
    "<manifest>{items}</manifest><spine/></package>"
).encode()


def opf(items, meta=""):
    return OPF_TEMPLATE.replace(b"{items}", items.encode()).replace(b"{meta}", meta.encode())


def test_cover_comes_from_the_cover_image_property():
    data = opf('<item id="c" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
               '<item id="d" href="images/other.jpg" media-type="image/jpeg"/>')

    assert SafariBooks.cover_image_paths(data, "OEBPS/content.opf") == {"OEBPS/images/cover.jpg"}


def test_cover_comes_from_the_legacy_cover_meta():
    data = opf('<item id="cov" href="images/front.png" media-type="image/png"/>',
               meta='<meta name="cover" content="cov"/>')

    assert SafariBooks.cover_image_paths(data, "OEBPS/content.opf") == {"OEBPS/images/front.png"}


def test_a_chapter_titled_cover_is_not_a_cover():
    # the old crawl promoted any chapter whose title merely contained "cover"; the /files/ pipeline
    # only trusts what the publisher's OPF declares
    data = opf('<item id="ch1" href="discovering_coverage.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="pic" href="images/fig.jpg" media-type="image/jpeg"/>')

    assert SafariBooks.cover_image_paths(data, "OEBPS/content.opf") == set()


def test_cover_paths_resolve_relative_to_the_opf_location():
    data = opf('<item id="c" href="../images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>')

    assert SafariBooks.cover_image_paths(data, "OEBPS/text/content.opf") == {"OEBPS/images/cover.jpg"}


def test_an_unparseable_opf_yields_no_cover_instead_of_crashing():
    assert SafariBooks.cover_image_paths(b"<package><oops", "OEBPS/content.opf") == set()
