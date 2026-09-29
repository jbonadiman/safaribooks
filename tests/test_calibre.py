"""The real Calibre `ebook-polish`, run on an EPUB this pipeline built.

Skipped where Calibre is not installed (a developer laptop); the `calibre` CI job installs it, so
every push checks the polish step against the real binary instead of a stub.
"""
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from safaribooks import SafariBooks  # noqa: E402
from support import FakeApi, make_book  # noqa: E402
import test_end_to_end as e2e  # noqa: E402

pytestmark = [
    pytest.mark.calibre,
    pytest.mark.skipif(shutil.which("ebook-polish") is None, reason="Calibre's ebook-polish is not installed"),
]

OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


@pytest.fixture
def unpolished(tmp_path):
    """The reflowable end-to-end book, built with the polish step switched off."""
    book, api = make_book(tmp_path, e2e.BOOK), FakeApi()
    book.args.no_optimize_images = True  # should_polish() is False, so the build leaves the EPUB as is
    book.book_info = {"title": "T\u00edtulo Nuevo", "language": "es", "authors": [{"name": "Jane Doe"}],
                      "publishers": [{"name": "Editorial"}]}
    epub = e2e.run(book, e2e.serve_all(api, e2e.BOOK, e2e.REFLOWABLE), api)
    epub.close()
    return book, Path(book.BOOK_PATH) / (book.book_id + ".epub")


def test_ebook_polish_accepts_the_built_epub_and_keeps_it_a_valid_book(unpolished):
    book, path = unpolished
    before = path.stat().st_size

    assert SafariBooks.polish_epub(str(path), book.display) is True, book.display.of("error")

    with zipfile.ZipFile(path) as epub:
        names = epub.namelist()
        assert epub.testzip() is None
        assert names[0] == "mimetype" and epub.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        opf_name = next(n for n in names if n.endswith(".opf"))
        opf = etree.fromstring(epub.read(opf_name))
        assert opf.findtext("opf:metadata/dc:title", namespaces=OPF_NS) == "T\u00edtulo Nuevo"
        assert opf.findtext("opf:metadata/dc:creator", namespaces=OPF_NS) == "Jane Doe"
        assert len(opf.findall("opf:spine/opf:itemref", OPF_NS)) == 2
        assert [n for n in names if n.endswith((".xhtml", ".html"))]
    assert not Path(str(path) + ".polishing").exists() and path.stat().st_size > 0 and before > 0


def test_the_default_build_runs_the_real_polish_step(tmp_path):
    book, api = make_book(tmp_path, e2e.BOOK), FakeApi()
    book.book_info = {"title": "T", "language": "en", "authors": [{"name": "Jane Doe"}], "publishers": []}
    epub = e2e.run(book, e2e.serve_all(api, e2e.BOOK, e2e.REFLOWABLE), api)

    assert book.should_polish(book.args) is True
    assert epub.testzip() is None and not Path(book.BOOK_PATH, book.book_id + ".epub.polishing").exists()
    assert not [m for m in book.display.of("error") if "polish" in m.lower()]


# ---------------------------------------------------------------- identifiers as Calibre reads them
@pytest.mark.skipif(shutil.which("ebook-meta") is None, reason="Calibre's ebook-meta is not installed")
@pytest.mark.parametrize("bare_number_only", [True, False])
def test_calibre_reports_the_isbn_of_a_book_whose_opf_only_had_a_bare_number(tmp_path, bare_number_only):
    # A bare <dc:identifier>9781718500570</dc:identifier> is no ISBN to Calibre (verified against 7.6:
    # "NO Identifiers LINE"); the patch adds the urn:isbn: form, which Calibre reports as isbn:...
    import subprocess

    identifiers = '<dc:identifier id="pub-id">9781718500570</dc:identifier>'
    if not bare_number_only:
        identifiers += '<dc:identifier id="isbn-id">urn:isbn:9781718500570</dc:identifier>'

    package = SafariBooks.patch_opf_document(
        ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">'
         '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">%s<dc:title>Probe</dc:title>'
         '<dc:language>en</dc:language><dc:creator>A</dc:creator></metadata><manifest>'
         '<item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>'
         '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
         '<spine toc="ncx"><itemref idref="c"/></spine></package>' % identifiers).encode(),
        "content.opf", _oebps(tmp_path), book_info={"isbn": "9781718500570"})
    path = tmp_path / "probe.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", package)
        for name, body in (("c.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body><p>x</p></body></html>'),
                           ("toc.ncx", '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>T</text></docTitle>'
                                       '<navMap><navPoint id="n" playOrder="1"><navLabel><text>c</text></navLabel><content src="c.xhtml"/></navPoint></navMap></ncx>')):
            z.writestr("OEBPS/" + name, body)

    out = subprocess.run(["ebook-meta", str(path)], capture_output=True, text=True).stdout

    assert "isbn:9781718500570" in out, out


def _oebps(tmp_path):
    root = tmp_path / "OEBPS"
    for name in ("c.xhtml", "toc.ncx"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"x")
    return str(root)
