"""The package document and NCX of a real downloaded book (No Starch Press, reflowable, 24 spine items).

Captured from a finished EPUB, so the OPF is the pipeline's own output (it already has our stylesheet
entry and a dcterms:modified), not the publisher's raw file. That makes it a real-shaped test of two
things the hand-built OPFs cannot show: patching a genuine OPF again must be stable, and the publisher's
structure (guide, nav item, cover-image, EPUB 3 refinements) must survive. The synopsis keeps its tag
skeleton with placeholder words and the NCX labels are generic; ids, playOrder and targets are real.
"""
import posixpath
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from conftest import FIXTURES  # noqa: E402
from safaribooks import SafariBooks  # noqa: E402
from test_package import NOW, NS  # noqa: E402

OPF_FILE = FIXTURES / "real_reflowable_9781098128463.opf"
NCX_FILE = FIXTURES / "real_reflowable_9781098128463.ncx"
NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
BULLET = "\u2022"

INFO = {"title": "Machine Learning for Kids", "language": "en", "authors": [{"name": "Dale Lane"}],
        "publishers": [{"name": "No Starch Press"}], "subjects": [{"name": "Machine Learning"}],
        "issued": "2020-12-01", "description": "<div><p>Learn:</p><p>%sOne<br/>%sTwo</p></div>" % (BULLET, BULLET)}


def hrefs(opf_bytes):
    root = etree.fromstring(opf_bytes)
    return [i.get("href") for i in root.findall("opf:manifest/opf:item", NS)]


@pytest.fixture
def oebps(tmp_path):
    """A directory holding every file the OPF's manifest names (the manifest is reconciled with disk)."""
    root = tmp_path / "OEBPS"
    for href in hrefs(OPF_FILE.read_bytes()):
        target = root / href
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    return str(root)


def patched(oebps, **overrides):
    info = dict(INFO, **overrides)
    return SafariBooks.patch_opf_document(OPF_FILE.read_bytes(), "content.opf", oebps, book_info=info, now=NOW)


def test_the_real_opf_is_the_shape_the_tests_assume():
    root = etree.fromstring(OPF_FILE.read_bytes())

    assert root.get("version") == "3.0"
    assert [etree.QName(c).localname for c in root] == ["metadata", "manifest", "spine", "guide"]
    assert len(root.findall("opf:spine/opf:itemref", NS)) == 24
    assert len(root.findall("opf:manifest/opf:item", NS)) == 334


def test_patching_a_real_opf_keeps_the_publishers_structure(oebps):
    root = etree.fromstring(patched(oebps))

    assert [etree.QName(c).localname for c in root] == ["metadata", "manifest", "spine", "guide"]
    assert [(r.get("type"), r.get("href")) for r in root.findall("opf:guide/opf:reference", NS)] == \
        [("cover", "cover.xhtml"), ("toc", "toc.xhtml"), ("text", "c01.xhtml")]
    assert len(root.findall("opf:spine/opf:itemref", NS)) == 24
    assert root.find("opf:spine", NS).get("toc") == "ncx"
    props = {i.get("properties") for i in root.findall("opf:manifest/opf:item", NS)}
    assert {"nav", "cover-image"} <= props


def test_the_real_creator_and_its_epub3_refinements_are_left_alone(oebps):
    before = etree.fromstring(OPF_FILE.read_bytes())
    after = etree.fromstring(patched(oebps, authors=[{"name": "Someone Else"}]))
    creators = after.findall("opf:metadata/dc:creator", NS)

    assert [c.text for c in creators] == ["Dale Lane"] and dict(creators[0].attrib) == {"id": "creator"}
    refines = lambda r: sorted((m.get("property"), m.text) for m in r.findall("opf:metadata/opf:meta", NS)
                               if m.get("refines") == "#creator")
    assert refines(after) == refines(before) and refines(after)


def test_the_catalogue_publisher_and_a_listified_synopsis_replace_the_real_ones(oebps):
    root = etree.fromstring(patched(oebps))

    assert [e.text for e in root.findall("opf:metadata/dc:publisher", NS)] == ["No Starch Press"]
    assert [e.text for e in root.findall("opf:metadata/dc:description", NS)] == \
        ["<div><p>Learn:</p><ul><li>One</li><li>Two</li></ul></div>"]


def test_the_real_synopsis_skeleton_becomes_one_list_of_five_items(oebps):
    original = etree.fromstring(OPF_FILE.read_bytes()).findtext("opf:metadata/dc:description", namespaces=NS)
    assert original.count(BULLET) == 5 and "<ul>" not in original      # the shape found in a real book

    out = SafariBooks.listify_description(original)

    assert out.count("<ul>") == 1 and out.count("<li>") == 5 and BULLET not in out
    assert out.count("<p>") == original.count("<p>") - 1               # the bullet paragraph became the list


def test_patching_a_real_opf_twice_changes_nothing(oebps):
    once = patched(oebps)
    twice = SafariBooks.patch_opf_document(once, "content.opf", oebps, book_info=dict(INFO), now=NOW)

    assert twice == once


def test_every_manifest_item_is_still_listed_and_ids_stay_unique(oebps):
    root = etree.fromstring(patched(oebps))
    ids = [i.get("id") for i in root.findall("opf:manifest/opf:item", NS)]

    assert len(ids) == len(set(ids))
    assert set(hrefs(OPF_FILE.read_bytes())) <= set(hrefs(patched(oebps))) | {"sb_styles/Style_Base.css"}


def test_a_file_missing_from_disk_is_dropped_from_a_real_manifest(oebps):
    victim = next(h for h in hrefs(OPF_FILE.read_bytes()) if h.startswith("image_fi/500563c05/"))
    Path(oebps, victim).unlink()

    assert victim not in hrefs(patched(oebps))


def test_the_cover_meta_still_resolves_to_the_cover_image_item(oebps):
    root = etree.fromstring(patched(oebps))
    cover_id = root.find("opf:metadata/opf:meta[@name='cover']", NS).get("content")
    item = next(i for i in root.findall("opf:manifest/opf:item", NS) if i.get("id") == cover_id)

    assert "cover-image" in item.get("properties").split() and item.get("href").endswith("cover.jpg")


# ------------------------------------------------------------------------------------------ NCX
def test_the_real_ncx_has_the_publishers_thin_head():
    root = etree.fromstring(NCX_FILE.read_bytes())
    head = {m.get("name") for m in root.findall("ncx:head/ncx:meta", NCX_NS)}

    # documented so nobody assumes otherwise: the pipeline writes the publisher's NCX as it is
    assert head == {"dtb:uid"} and root.find("ncx:docAuthor", NCX_NS) is None


def test_the_real_ncx_becomes_a_nested_nav_with_every_entry_and_a_fragment_where_it_had_one():
    ncx = NCX_FILE.read_bytes()
    nav = SafariBooks.nav_from_ncx(ncx, "toc.ncx", "toc.xhtml", "Fixture Title")
    root = etree.fromstring(nav if isinstance(nav, bytes) else nav.encode("utf-8"))
    xhtml = {"h": "http://www.w3.org/1999/xhtml"}
    links = root.findall(".//h:nav//h:a", xhtml)
    points = etree.fromstring(ncx).findall(".//ncx:navPoint", NCX_NS)

    assert len(links) == len(points) == 146
    assert sum("#" in a.get("href") for a in links) == 123
    assert max(len(list(a.iterancestors("{%s}ol" % xhtml["h"]))) for a in links) == 3


def test_the_real_ncx_targets_are_the_manifests_documents():
    opf_hrefs = set(hrefs(OPF_FILE.read_bytes()))
    targets = {posixpath.normpath(p.find("ncx:content", NCX_NS).get("src").split("#")[0])
               for p in etree.fromstring(NCX_FILE.read_bytes()).findall(".//ncx:navPoint", NCX_NS)}

    assert targets <= opf_hrefs


# ---------------------------------------------------------------- publisher's raw fixed-layout package
FXL_OPF_FILE = FIXTURES / "real_fixed_9781718503519.opf"
FXL_NCX_FILE = FIXTURES / "real_fixed_9781718503519.ncx"
FXL_INFO = {"title": "Electronics for Kids, 2nd Edition", "language": "en", "isbn": "9781718503502",
            "authors": [{"name": "\u00d8yvind Nydal Dahl"}], "publishers": [{"name": "No Starch Press"}],
            "issued": "2026-06-30", "description": "<div><p>Synopsis.</p></div>"}


@pytest.fixture
def fxl_oebps(tmp_path):
    root = tmp_path / "OEBPS"
    for item in etree.fromstring(FXL_OPF_FILE.read_bytes()).findall("opf:manifest/opf:item", NS):
        target = root / item.get("href")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    return str(root)


def fxl_patch(oebps, opf_bytes=None):
    return etree.fromstring(SafariBooks.patch_opf_document(
        opf_bytes or FXL_OPF_FILE.read_bytes(), "content.opf", oebps, now=NOW, book_info=FXL_INFO, fixed_layout=True))


def rendition(root):
    return {m.get("property"): m.text for m in root.findall("opf:metadata/opf:meta", NS)
            if (m.get("property") or "").startswith("rendition:")}


def test_the_publishers_spread_and_orientation_survive_on_a_real_fixed_layout_opf(fxl_oebps):
    # The publisher declares spread "auto" and pages marked page-spread-left/right; "none" would forbid
    # the two-page spreads its spine is built for.
    assert rendition(fxl_patch(fxl_oebps)) == {
        "rendition:layout": "pre-paginated", "rendition:spread": "auto", "rendition:orientation": "landscape"}


def test_the_spread_defaults_to_none_when_the_publisher_declares_none(fxl_oebps):
    raw = FXL_OPF_FILE.read_bytes().replace(b'<meta property="rendition:spread">auto</meta>', b"")
    assert b"rendition:spread" not in raw

    assert rendition(fxl_patch(fxl_oebps, raw))["rendition:spread"] == "none"


def test_a_layout_that_disagrees_with_the_detected_fixed_layout_is_corrected(fxl_oebps):
    raw = FXL_OPF_FILE.read_bytes().replace(b">pre-paginated<", b">reflowable<")

    assert rendition(fxl_patch(fxl_oebps, raw))["rendition:layout"] == "pre-paginated"


def test_a_real_fixed_layout_opf_keeps_its_guide_spine_pages_and_cover(fxl_oebps):
    root = fxl_patch(fxl_oebps)
    spine = root.find("opf:spine", NS)

    assert [(g.get("type"), g.get("href")) for g in root.findall("opf:guide/opf:reference", NS)] == [
        ("cover", "xhtml/cover.xhtml"), ("text", "xhtml/page026.xhtml")]
    assert len(spine) == 247 and spine.get("toc") == "ncx"
    assert {r.get("properties") for r in spine if r.get("properties")} == {"page-spread-left", "page-spread-right"}
    assert len(root.findall("opf:manifest/opf:item", NS)) == 640


def test_a_real_fixed_layout_opf_gets_the_print_isbn_the_publisher_only_gave_as_source(fxl_oebps):
    root = fxl_patch(fxl_oebps)
    identifiers = [e.text for e in root.findall("opf:metadata/dc:identifier", NS)]

    assert identifiers == ["9781718503519", "urn:isbn:9781718503502"]
    assert root.get("unique-identifier") == "e9781718503519"


def test_a_real_fixed_layout_opf_is_stable_under_a_second_patch(fxl_oebps):
    first = SafariBooks.patch_opf_document(FXL_OPF_FILE.read_bytes(), "content.opf", fxl_oebps, now=NOW,
                                           book_info=FXL_INFO, fixed_layout=True)
    second = SafariBooks.patch_opf_document(first, "content.opf", fxl_oebps, now=NOW,
                                            book_info=FXL_INFO, fixed_layout=True)

    assert first == second


def test_the_real_fixed_layout_ncx_has_90_entries_every_one_in_the_manifest():
    ncx = etree.fromstring(FXL_NCX_FILE.read_bytes())
    manifest = {i.get("href") for i in etree.fromstring(FXL_OPF_FILE.read_bytes()).findall("opf:manifest/opf:item", NS)}
    targets = [c.get("src").split("#")[0] for c in ncx.iter("{%s}content" % NCX_NS["ncx"])]

    assert len(targets) == 90 and set(targets) <= manifest
