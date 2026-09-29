"""The package document and navigation: patching the publisher's OPF, building nav from the NCX."""
import datetime
import os

import pytest
from lxml import etree

from safaribooks import SafariBooks
from support import make_book

OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
NS = {"opf": OPF, "dc": DC}
NOW = datetime.datetime(2026, 9, 29, 12, 0, 0, tzinfo=datetime.timezone.utc)


def opf_xml(metadata="", manifest="", spine=""):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="%s" version="3.0" unique-identifier="bookid">'
            '<metadata xmlns:dc="%s" xmlns:opf="%s">'
            '<dc:identifier id="bookid">urn:isbn:9781098168827</dc:identifier>'
            '<dc:title>Fundamentals of Software Architecture</dc:title><dc:language>en</dc:language>%s</metadata>'
            '<manifest>%s</manifest><spine>%s</spine></package>' % (OPF, DC, OPF, metadata, manifest, spine)
            ).encode("utf-8")


DEFAULT_MANIFEST = ('<item id="ch1" href="xhtml/ch01.xhtml" media-type="application/xhtml+xml"/>'
                    '<item id="css" href="styles/book.css" media-type="text/css"/>'
                    '<item id="fig" href="images/fig1.png" media-type="image/png"/>')
DEFAULT_SPINE = '<itemref idref="ch1"/>'
FILES = ["content.opf", "xhtml/ch01.xhtml", "styles/book.css", "images/fig1.png"]


def on_disk(tmp_path, paths=FILES):
    root = tmp_path / "OEBPS"
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    return str(root)


def patch(tmp_path, opf=None, paths=FILES, **kwargs):
    kwargs.setdefault("book_info", {})
    out = SafariBooks.patch_opf_document(
        opf or opf_xml(manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE), "content.opf", on_disk(tmp_path, paths),
        now=NOW, **kwargs)
    return etree.fromstring(out)


def text_of(root, tag):
    return [e.text for e in root.findall("opf:metadata/dc:%s" % tag, NS)]


def items(root):
    return {i.get("id"): i for i in root.findall("opf:manifest/opf:item", NS)}


# ---------------------------------------------------------------- metadata
def test_patch_opf_replaces_title_and_language_of_a_translated_edition(tmp_path):
    root = patch(tmp_path, book_info={"title": "Fundamentos de la arquitectura de software, 2.\u00aa edici\u00f3n",
                                      "language": "es"})

    assert text_of(root, "title") == ["Fundamentos de la arquitectura de software, 2.\u00aa edici\u00f3n"]
    assert text_of(root, "language") == ["es"]


def test_patch_opf_updates_the_epub3_refinement_metas_too(tmp_path):
    opf = opf_xml(metadata='<meta property="dcterms:title">Old</meta><meta property="dcterms:language">en</meta>',
                  manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, book_info={"title": "Nuevo", "language": "es"})
    props = {m.get("property"): m.text for m in root.findall("opf:metadata/opf:meta", NS)}

    assert props["dcterms:title"] == "Nuevo" and props["dcterms:language"] == "es"


def test_patch_opf_keeps_the_publishers_metadata_when_nothing_better_is_known(tmp_path):
    root = patch(tmp_path, book_info={"title": "  ", "language": ""})
    assert text_of(root, "title") == ["Fundamentals of Software Architecture"] and text_of(root, "language") == ["en"]


def test_patch_opf_drops_blank_dublin_core_elements(tmp_path):
    opf = opf_xml(metadata="<dc:rights>  </dc:rights><dc:publisher/><dc:subject>Architecture</dc:subject>",
                  manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf)

    assert text_of(root, "rights") == [] and text_of(root, "publisher") == []
    assert text_of(root, "subject") == ["Architecture"]


def test_patch_opf_fills_a_missing_creator_and_publisher_from_the_book_info(tmp_path):
    root = patch(tmp_path, book_info={"authors": [{"name": "Neal Ford"}, {"name": "Mark Richards"}],
                                      "publishers": [{"name": "O'Reilly Media"}, {"name": "No Starch Press"}]})

    assert text_of(root, "creator") == ["Neal Ford", "Mark Richards"]
    assert text_of(root, "publisher") == ["O'Reilly Media, No Starch Press"]
    # right after the title, before language, as the EPUB 2 readers expect
    tags = [etree.QName(e).localname for e in root.find("opf:metadata", NS)]
    assert tags.index("creator") == tags.index("title") + 1


def test_patch_opf_never_overwrites_a_creator_or_publisher_the_publisher_supplied(tmp_path):
    opf = opf_xml(metadata="<dc:creator>Original Author</dc:creator><dc:publisher>Original House</dc:publisher>",
                  manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, book_info={"authors": [{"name": "Someone Else"}], "publishers": [{"name": "X"}]})

    assert text_of(root, "creator") == ["Original Author"] and text_of(root, "publisher") == ["Original House"]


def test_patch_opf_ignores_placeholder_and_blank_names(tmp_path):
    root = patch(tmp_path, book_info={"authors": [{"name": "n/a"}, {"name": " "}, {}], "publishers": [{"name": ""}]})
    assert text_of(root, "creator") == [] and text_of(root, "publisher") == []


def test_patch_opf_escapes_markup_in_metadata(tmp_path):
    root = patch(tmp_path, book_info={"title": "R&D <Handbook>"})
    assert text_of(root, "title") == ["R&D <Handbook>"]


# ---------------------------------------------------------------- manifest reconciliation
def test_patch_opf_drops_manifest_items_whose_file_was_not_downloaded(tmp_path):
    root = patch(tmp_path, paths=["content.opf", "xhtml/ch01.xhtml", "styles/book.css"])  # image pruned
    assert set(items(root)) >= {"ch1", "css"} and "fig" not in items(root)


def test_patch_opf_refuses_a_book_whose_spine_file_is_missing(tmp_path):
    with pytest.raises(ValueError, match="spine item xhtml/ch01.xhtml is missing"):
        patch(tmp_path, paths=["content.opf", "styles/book.css", "images/fig1.png"])


def test_patch_opf_follows_converted_images(tmp_path):
    root = patch(tmp_path, paths=["content.opf", "xhtml/ch01.xhtml", "styles/book.css", "images/fig1.jpg"],
                 rename_map={"images/fig1.png": "images/fig1.jpg"})
    fig = items(root)["fig"]

    assert fig.get("href") == "images/fig1.jpg" and fig.get("media-type") == "image/jpeg"


def test_patch_opf_adds_our_own_files_once_with_unique_valid_ids(tmp_path):
    paths = FILES + ["sb_styles/Style_Base.css", "sb_styles/Inline00.css", "fonts/My Font.ttf"]
    root = patch(tmp_path, paths=paths)
    added = {i.get("href"): i for i in root.findall("opf:manifest/opf:item", NS)}

    assert added["sb_styles/Style_Base.css"].get("media-type") == "text/css"
    assert added["fonts/My%20Font.ttf"].get("media-type") == "application/x-font-truetype"
    ids = [i.get("id") for i in root.findall("opf:manifest/opf:item", NS)]
    assert len(ids) == len(set(ids)) and all(i[0].isalpha() for i in ids)
    hrefs = [i.get("href") for i in root.findall("opf:manifest/opf:item", NS)]
    assert len(hrefs) == len(set(hrefs))
    assert "content.opf" not in hrefs


def test_patch_opf_resolves_hrefs_relative_to_an_opf_that_is_not_at_the_root(tmp_path):
    opf = opf_xml(manifest='<item id="ch1" href="../xhtml/ch01.xhtml" media-type="application/xhtml+xml"/>',
                  spine=DEFAULT_SPINE)
    root = etree.fromstring(SafariBooks.patch_opf_document(
        opf, "pkg/content.opf", on_disk(tmp_path, ["pkg/content.opf", "xhtml/ch01.xhtml", "sb_styles/Style_Base.css"]),
        {}, now=NOW))

    assert {i.get("href") for i in root.findall("opf:manifest/opf:item", NS)} == {
        "../xhtml/ch01.xhtml", "../sb_styles/Style_Base.css"}


def test_patch_opf_ignores_partial_download_leftovers(tmp_path):
    root = patch(tmp_path, paths=FILES + ["images/x.png.part", "xhtml/c.tmp"])
    assert not [i for i in root.findall("opf:manifest/opf:item", NS) if i.get("href").endswith((".part", ".tmp"))]


def test_patch_opf_rejects_a_package_without_metadata_manifest_or_spine(tmp_path):
    with pytest.raises(ValueError, match="no metadata, manifest or spine"):
        SafariBooks.patch_opf_document(('<package xmlns="%s"/>' % OPF).encode(), "content.opf", str(tmp_path), {})


# ---------------------------------------------------------------- cover
def cover_opf(content):
    return opf_xml(metadata='<meta name="cover" content="%s"/>' % content,
                   manifest=DEFAULT_MANIFEST + '<item id="cov" href="images/cover.png" media-type="image/png"/>',
                   spine=DEFAULT_SPINE)


def test_patch_opf_cover_meta_is_a_manifest_item_id(tmp_path):
    root = patch(tmp_path, cover_opf("cov"), paths=FILES + ["images/cover.png"])
    meta = root.find("opf:metadata/opf:meta[@name='cover']", NS)

    assert meta.get("content") in items(root)


def test_patch_opf_repairs_a_dangling_cover_meta_from_the_cover_image_property(tmp_path):
    opf = opf_xml(metadata='<meta name="cover" content="images/cover.png"/>',
                  manifest=DEFAULT_MANIFEST + '<item id="c2" href="images/cover.png" media-type="image/png" '
                                              'properties="cover-image"/>', spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, paths=FILES + ["images/cover.png"])

    assert root.find("opf:metadata/opf:meta[@name='cover']", NS).get("content") == "c2"


def test_patch_opf_drops_a_cover_meta_that_cannot_be_repaired(tmp_path):
    opf = opf_xml(metadata='<meta name="cover" content="nothing-like-it"/>',
                  manifest='<item id="ch1" href="xhtml/ch01.xhtml" media-type="application/xhtml+xml"/>',
                  spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, paths=["content.opf", "xhtml/ch01.xhtml"])

    assert root.find("opf:metadata/opf:meta[@name='cover']", NS) is None


# ---------------------------------------------------------------- fixed layout
def test_patch_opf_declares_epub3_pre_paginated_for_a_fixed_layout_book(tmp_path):
    opf = opf_xml(metadata='<meta name="cover" content="cov"/>',
                  manifest=DEFAULT_MANIFEST + '<item id="cov" href="images/cover.png" media-type="image/png"/>'
                           '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                  spine=DEFAULT_SPINE)
    opf = opf.replace(b'version="3.0"', b'version="2.0"')
    root = patch(tmp_path, opf, paths=FILES + ["images/cover.png", "nav.xhtml"], fixed_layout=True)
    props = {m.get("property"): m.text for m in root.findall("opf:metadata/opf:meta", NS) if m.get("property")}

    assert root.get("version") == "3.0"
    assert props["rendition:layout"] == "pre-paginated" and props["rendition:spread"] == "none"
    assert props["dcterms:modified"] == "2026-09-29T12:00:00Z"
    assert "cover-image" in items(root)["cov"].get("properties").split()


def test_patch_opf_keeps_a_modified_date_and_layout_the_publisher_already_set(tmp_path):
    opf = opf_xml(metadata='<meta property="dcterms:modified">2020-01-01T00:00:00Z</meta>'
                           '<meta property="rendition:layout">pre-paginated</meta>',
                  manifest=DEFAULT_MANIFEST + '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
                                              'properties="nav"/>', spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, paths=FILES + ["nav.xhtml"], fixed_layout=True)
    props = [m for m in root.findall("opf:metadata/opf:meta", NS) if m.get("property") == "dcterms:modified"]

    assert len(props) == 1 and props[0].text == "2020-01-01T00:00:00Z"


def test_patch_opf_refuses_fixed_layout_without_any_navigation_document(tmp_path):
    with pytest.raises(ValueError, match="navigation document"):
        patch(tmp_path, fixed_layout=True)


def test_patch_opf_leaves_a_reflowable_book_at_its_own_version_and_without_rendition(tmp_path):
    root = patch(tmp_path)
    assert not [m for m in root.findall("opf:metadata/opf:meta", NS) if (m.get("property") or "").startswith("rendition")]


# ---------------------------------------------------------------- nav
NCX = ('<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
       '<navPoint id="a" playOrder="1"><navLabel><text>Part  One &amp; Two</text></navLabel>'
       '<content src="xhtml/ch%2001.xhtml"/>'
       '<navPoint id="b" playOrder="2"><navLabel><text>Section</text></navLabel><content src="xhtml/ch01.xhtml#s1"/>'
       '</navPoint></navPoint>'
       '<navPoint id="c" playOrder="3"><navLabel><text>No target</text></navLabel><content src=""/></navPoint>'
       '</navMap></ncx>').encode("utf-8")


def test_nav_from_ncx_builds_a_nested_epub3_toc():
    nav = SafariBooks.nav_from_ncx(NCX, "toc.ncx", "nav.xhtml", "My <Book>")
    root = etree.fromstring(nav.encode("utf-8"))
    x = {"x": "http://www.w3.org/1999/xhtml", "epub": "http://www.idpf.org/2007/ops"}

    assert root.xpath("//x:nav/@epub:type", namespaces=x) == ["toc"]
    assert root.xpath("string(//x:title)", namespaces=x) == "My <Book>"
    outer = root.xpath("//x:nav/x:ol/x:li", namespaces=x)
    assert len(outer) == 1  # the target-less point is skipped
    assert outer[0].xpath("string(x:a)", namespaces=x) == "Part One & Two"
    assert outer[0].xpath("x:a/@href", namespaces=x) == ["xhtml/ch%2001.xhtml"]
    assert outer[0].xpath("x:ol/x:li/x:a/@href", namespaces=x) == ["xhtml/ch01.xhtml#s1"]


def test_nav_from_ncx_makes_hrefs_relative_to_where_the_nav_will_live():
    ncx = NCX.replace(b'src="xhtml/ch%2001.xhtml"', b'src="../xhtml/ch01.xhtml"')
    nav = SafariBooks.nav_from_ncx(ncx, "pkg/toc.ncx", "pkg/sub/nav.xhtml", "T")

    assert 'href="../../xhtml/ch01.xhtml"' in nav


def test_nav_from_ncx_returns_none_for_an_empty_toc():
    ncx = b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap/></ncx>'
    assert SafariBooks.nav_from_ncx(ncx, "toc.ncx", "nav.xhtml", "T") is None


def test_opf_has_nav_reads_the_manifest_properties():
    with_nav = opf_xml(manifest='<item id="n" href="nav.xhtml" media-type="application/xhtml+xml" '
                                'properties="scripted nav"/>')
    assert SafariBooks.opf_has_nav(with_nav) is True
    assert SafariBooks.opf_has_nav(opf_xml(manifest=DEFAULT_MANIFEST)) is False


# ---------------------------------------------------------------- create_epub (packaging on disk)
def test_create_epub_patches_the_opf_and_packages_an_ocf_zip(tmp_path):
    import zipfile

    book = make_book(tmp_path)
    book.opf_path, book.ncx_path = "content.opf", None
    book.book_info = {"title": "Nuevo T\u00edtulo", "language": "es", "authors": [{"name": "Neal Ford"}],
                      "publishers": []}
    book.save_text("content.opf", opf_xml(manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE).decode())
    for path in FILES[1:]:
        os.makedirs(os.path.dirname(book.destination(path)), exist_ok=True)
        open(book.destination(path), "wb").write(b"x")

    book.create_epub()
    epub = os.path.join(book.BOOK_PATH, book.book_id + ".epub")

    with zipfile.ZipFile(epub) as z:
        assert z.infolist()[0].filename == "mimetype" and z.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        assert "OEBPS/content.opf" in z.namelist() and "META-INF/container.xml" in z.namelist()
        container = etree.fromstring(z.read("META-INF/container.xml"))
        assert container.xpath("//@full-path")[0] == "OEBPS/content.opf"
        opf = etree.fromstring(z.read("OEBPS/content.opf"))
        assert opf.find("opf:metadata/dc:title", NS).text == "Nuevo T\u00edtulo"
        assert opf.find("opf:metadata/dc:creator", NS).text == "Neal Ford"
        assert z.testzip() is None


def test_create_epub_builds_a_nav_from_the_ncx_for_a_fixed_layout_book(tmp_path):
    book = make_book(tmp_path)
    book.opf_path, book.ncx_path, book.fixed_layout = "content.opf", "toc.ncx", True
    book.save_text("content.opf", opf_xml(manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE).decode())
    book.save_text("toc.ncx", NCX.decode())
    for path in FILES[1:]:
        os.makedirs(os.path.dirname(book.destination(path)), exist_ok=True)
        open(book.destination(path), "wb").write(b"x")

    book.create_epub()
    opf = etree.parse(book.destination("content.opf")).getroot()
    nav = [i for i in opf.findall("opf:manifest/opf:item", NS) if "nav" in (i.get("properties") or "").split()]

    assert len(nav) == 1 and nav[0].get("href") == "nav.xhtml" and os.path.isfile(book.destination("nav.xhtml"))
    assert opf.get("version") == "3.0"


def test_create_epub_exits_with_a_clear_message_when_the_spine_is_incomplete(tmp_path):
    book = make_book(tmp_path)
    book.opf_path, book.ncx_path = "content.opf", None
    book.save_text("content.opf", opf_xml(manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE).decode())  # no chapter file

    with pytest.raises(SystemExit):
        book.create_epub()

    assert "Package document: spine item xhtml/ch01.xhtml is missing" in book.display.of("exit")[0]
