"""Asset stages on the /files/ pipeline: stylesheets, fonts, images, JPEG conversion, pruning, fixed layout."""
import os

import pytest
from PIL import Image

from safaribooks import SafariBooks
from support import FakeApi, files_entry, make_book, png_bytes, tree_files

BOOK = "9781098168827"
API = "/api/v2/epubs/urn:orm:book:%s/files/" % BOOK


def entry(path, kind, media, book=BOOK):
    e = files_entry(book, path, kind, media)
    e["path"] = path
    return e


def planned(book, *entries):
    """Give the book a plan bucketed like plan_files() does."""
    plan = {"chapter": [], "stylesheet": [], "image": [], "font": [], "documents": []}
    for e in entries:
        kind = SafariBooks.classify_file(e)
        if kind in plan:
            plan[kind].append(e)
    book.plan = plan
    return plan


BASELINE = "sb_styles/Style_Base.css"  # written by create_dirs() for every book


def files(book):
    """Every file of the book except the base stylesheet every book starts with."""
    return [p for p in tree_files(book.oebps_path) if p != BASELINE]


def read(book, path):
    with open(book.destination(path), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- stylesheets
CSS = "p{color:#333;margin:0}@font-face{font-family:X;src:url(../fonts/x.ttf)}a{background:url(%simages/bg.png)}" % API


def test_fetch_stylesheet_localizes_api_urls_strips_colour_and_records_fonts(tmp_path):
    book, api = make_book(tmp_path, BOOK), FakeApi()
    css = entry("styles/book.css", "stylesheet", "text/css")
    api.serve(css, CSS.encode("utf-8"))
    book.requests_provider = api.provider

    assert book.fetch_stylesheet(css) is None
    saved = read(book, "styles/book.css")

    assert "/api/v2/" not in saved and "url(../images/bg.png)" in saved
    assert "#333" not in saved and "margin:0" in saved
    assert book.font_sources == {"fonts/x.ttf"}


def test_fetch_stylesheet_keeps_colours_when_optimisation_is_off_or_the_book_is_fixed_layout(tmp_path):
    for label, kwargs, fixed in (("off", dict(no_optimize_css=True), False), ("fxl", {}, True)):
        book, api = make_book(tmp_path / label, BOOK, **kwargs), FakeApi()
        book.fixed_layout = fixed
        css = entry("styles/book.css", "stylesheet", "text/css")
        api.serve(css, CSS.encode("utf-8"))
        book.requests_provider = api.provider
        book.fetch_stylesheet(css)

        assert "#333" in read(book, "styles/book.css"), label


def test_fetch_stylesheet_reports_the_http_error_and_writes_nothing(tmp_path):
    book = make_book(tmp_path, BOOK)
    book.requests_provider = FakeApi().provider

    assert book.fetch_stylesheet(entry("styles/a.css", "stylesheet", "text/css")) == "HTTP 404: styles/a.css"
    assert not os.path.exists(book.destination("styles/a.css"))


def test_fetch_stylesheet_on_resume_does_not_refetch_but_still_records_its_fonts(tmp_path):
    book = make_book(tmp_path, BOOK)
    book.save_text("styles/book.css", "@font-face{font-family:X;src:url(../fonts/x.ttf)}")
    book.requests_provider = lambda *a, **k: pytest.fail("must not refetch")

    assert book.fetch_stylesheet(entry("styles/book.css", "stylesheet", "text/css")) is None
    assert book.font_sources == {"fonts/x.ttf"}


def test_collect_css_aborts_when_a_stylesheet_fails(tmp_path):
    book = make_book(tmp_path, BOOK)
    planned(book, entry("styles/a.css", "stylesheet", "text/css"))
    book.requests_provider = FakeApi().provider

    with pytest.raises(SystemExit):
        book.collect_css()


# ---------------------------------------------------------------- fonts
def test_collect_fonts_downloads_only_fonts_a_font_face_asks_for(tmp_path):
    book, api = make_book(tmp_path, BOOK), FakeApi()
    used, unused = entry("fonts/used.ttf", "font", "font/ttf"), entry("fonts/unused.ttf", "font", "font/ttf")
    planned(book, used, unused)
    api.serve(used, b"FONT")
    book.requests_provider = api.provider
    book.font_sources = {"fonts/used.ttf", "fonts/ghost.ttf"}

    book.collect_fonts()

    assert files(book) == ["fonts/used.ttf"]
    assert api.calls == [used["url"]]
    assert any("fonts/ghost.ttf" in w for w in book.display.of("warning"))
    assert any("unused.ttf" in m for m in book.display.of("log"))


def test_a_font_that_fails_to_download_only_warns(tmp_path):
    book = make_book(tmp_path, BOOK)
    font = entry("fonts/used.ttf", "font", "font/ttf")
    planned(book, font)
    book.requests_provider = FakeApi().provider  # 404
    book.font_sources = {"fonts/used.ttf"}

    book.collect_fonts()  # must not raise or exit

    assert any("fallback" in w for w in book.display.of("warning"))


# ---------------------------------------------------------------- image collection
def chapter_referencing(book, path, *image_paths, body_extra=""):
    imgs = "".join('<img src="%s"/>' % p for p in image_paths)
    book.save_text(path, '<html><body><div id="sbo-rt-content">%s%s</div></body></html>' % (imgs, body_extra))


def test_collect_images_downloads_only_what_pages_css_or_the_cover_use(tmp_path):
    book, api = make_book(tmp_path, BOOK), FakeApi()
    opf = entry("content.opf", "other_asset", "application/oebps-package+xml")
    images = {n: entry("images/%s.png" % n, "image", "image/png") for n in ("used", "css", "cover", "orphan")}
    planned(book, opf, *images.values())
    for e in images.values():
        api.serve(e, png_bytes())
    book.opf_path = "content.opf"
    book.save_text("content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata><meta name="cover" '
                                  'content="cov"/></metadata><manifest><item id="cov" href="images/cover.png" '
                                  'media-type="image/png"/></manifest><spine/></package>')
    chapter_referencing(book, "xhtml/ch01.xhtml", "../images/used.png")
    book.save_text("styles/book.css", "a{background:url(../images/css.png)}")
    book.requests_provider = api.provider

    book.collect_images()

    assert files(book) == [
        "content.opf", "images/cover.png", "images/css.png", "images/used.png",
        "styles/book.css", "xhtml/ch01.xhtml"]


def test_collect_images_mirrors_everything_when_optimisation_is_off(tmp_path):
    book, api = make_book(tmp_path, BOOK, no_optimize_images=True), FakeApi()
    imgs = [entry("images/%s.png" % n, "image", "image/png") for n in ("a", "orphan")]
    planned(book, *imgs)
    for e in imgs:
        api.serve(e, png_bytes())
    book.requests_provider = api.provider

    book.collect_images()

    assert files(book) == ["images/a.png", "images/orphan.png"]


def test_collect_images_aborts_and_keeps_partial_progress_when_one_fails(tmp_path):
    book, api = make_book(tmp_path, BOOK, no_optimize_images=True), FakeApi()
    ok, bad = entry("images/ok.png", "image", "image/png"), entry("images/bad.png", "image", "image/png")
    planned(book, ok, bad)
    api.serve(ok, png_bytes())
    book.requests_provider = api.provider

    with pytest.raises(SystemExit):
        book.collect_images()

    assert "images/ok.png" in files(book)  # nothing already downloaded is lost
    assert "HTTP 404: images/bad.png" in book.display.of("error")


def test_a_partial_download_never_leaves_a_half_written_file_behind(tmp_path):
    book = make_book(tmp_path, BOOK)
    img = entry("images/a.png", "image", "image/png")

    class Dies:
        status_code = 200

        def iter_content(self, size):
            yield b"abc"
            raise ConnectionError("cut")

    book.requests_provider = lambda *a, **k: Dies()
    with pytest.raises(ConnectionError):
        book.fetch_binary(img)

    assert not os.path.exists(book.destination("images/a.png"))  # only the .part exists, and is ignored


def test_fetch_binary_skips_a_file_already_on_disk_but_refetches_an_empty_one(tmp_path):
    book, api = make_book(tmp_path, BOOK), FakeApi()
    img = entry("images/a.png", "image", "image/png")
    api.serve(img, b"NEW")
    book.requests_provider = api.provider
    os.makedirs(os.path.dirname(book.destination(img["path"])))
    open(book.destination(img["path"]), "wb").close()  # zero bytes: an interrupted run

    assert book.fetch_binary(img) is None
    assert open(book.destination(img["path"]), "rb").read() == b"NEW"
    assert book.fetch_binary(img) is None and len(api.calls) == 1


# ---------------------------------------------------------------- finalize_images
def jpeg_book(tmp_path, images, chapter_imgs, css="", cover=None):
    book = make_book(tmp_path, BOOK)
    entries = [entry(p, "image", "image/png") for p in images]
    planned(book, entry("xhtml/ch01.xhtml", "chapter", "application/xhtml+xml"), *entries)
    for p in images:
        os.makedirs(os.path.dirname(book.destination(p)), exist_ok=True)
        with open(book.destination(p), "wb") as f:
            f.write(png_bytes())
    chapter_referencing(book, "xhtml/ch01.xhtml", *chapter_imgs)
    if css:
        book.save_text("styles/book.css", css)
    book.opf_path = "content.opf"
    book.save_text("content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata>%s</metadata>'
                                  '<manifest/><spine/></package>'
                   % ('<meta name="cover" content="cov"/>' if cover else ""))
    return book


def test_finalize_images_converts_to_jpeg_and_rewrites_pages_and_css(tmp_path):
    book = jpeg_book(tmp_path, ["images/a.png", "images/b.png"], ["../images/a.png"],
                     css="i{background:url(../images/b.png)}")
    book.finalize_images()

    assert files(book) == ["content.opf", "images/a.jpg", "images/b.jpg",
                                           "styles/book.css", "xhtml/ch01.xhtml"]
    assert 'src="../images/a.jpg"' in read(book, "xhtml/ch01.xhtml")
    assert "url(../images/b.jpg)" in read(book, "styles/book.css")
    assert book.rename_map == {"images/a.png": "images/a.jpg", "images/b.png": "images/b.jpg"}
    with Image.open(book.destination("images/a.jpg")) as img:
        assert img.format == "JPEG"


def test_finalize_images_prunes_unused_images_but_keeps_css_used_ones(tmp_path):
    book = jpeg_book(tmp_path, ["images/a.png", "images/css.png", "images/orphan.png"], ["../images/a.png"],
                     css="i{background:url(../images/css.png)}")
    book.finalize_images()

    assert sorted(p for p in files(book) if p.startswith("images/")) == [
        "images/a.jpg", "images/css.jpg"]


def test_finalize_images_never_deletes_the_publisher_own_jpeg_next_to_a_png(tmp_path):
    book = jpeg_book(tmp_path, ["images/a.png", "images/a.jpg"], ["../images/a.png", "../images/a.jpg"])
    book.finalize_images()

    assert sorted(p for p in files(book) if p.startswith("images/")) == [
        "images/a.jpg", "images/a_png.jpg"]
    page = read(book, "xhtml/ch01.xhtml")
    assert "../images/a_png.jpg" in page and "../images/a.jpg" in page


def test_finalize_images_refuses_to_prune_when_no_chapter_references_any_image(tmp_path):
    # The scanner being out of sync with the markup must never again wipe every image of a book.
    book = jpeg_book(tmp_path, ["images/a.png", "images/b.png"], [])
    book.finalize_images()

    assert sorted(p for p in files(book) if p.startswith("images/")) == [
        "images/a.jpg", "images/b.jpg"]
    assert any("skipping unused-image pruning" in e for e in book.display.of("error"))


def test_finalize_images_keeps_the_cover_even_if_no_chapter_shows_it(tmp_path):
    book = jpeg_book(tmp_path, ["images/cover.png", "images/a.png", "images/orphan.png"], ["../images/a.png"])
    book.save_text("content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata>'
                                  '<meta name="cover" content="cov"/></metadata><manifest><item id="cov" '
                                  'href="images/cover.png" media-type="image/png"/></manifest><spine/></package>')
    book.finalize_images()

    assert sorted(p for p in files(book) if p.startswith("images/")) == [
        "images/a.jpg", "images/cover.jpg"]


def test_finalize_images_keeps_a_file_it_cannot_convert(tmp_path):
    book = jpeg_book(tmp_path, ["images/bad.png"], ["../images/bad.png"])
    with open(book.destination("images/bad.png"), "wb") as f:
        f.write(b"not an image")
    book.finalize_images()

    assert "images/bad.png" in files(book) and book.rename_map == {}
    assert any("Unable to convert image" in e for e in book.display.of("error"))


def test_finalize_images_leaves_svg_and_jpeg_alone(tmp_path):
    book = jpeg_book(tmp_path, ["images/a.svg", "images/b.jpeg"], ["../images/a.svg", "../images/b.jpeg"])
    book.finalize_images()

    assert book.rename_map == {}
    assert sorted(p for p in files(book) if p.startswith("images/")) == ["images/a.svg", "images/b.jpeg"]


# ---------------------------------------------------------------- fixed layout (real captures)
def fxl_book(tmp_path, load_fixture):
    book = make_book(tmp_path, "0642572230319")
    chapter = entry("xhtml/page008.xhtml", "chapter", "application/xhtml+xml", "0642572230319")
    stylesheet = entry("styles/stylesheet_001-025.css", "stylesheet", "text/css", "0642572230319")
    planned(book, chapter, stylesheet)
    book.save_text("xhtml/page008.xhtml", load_fixture("fxl_page_0642572230319.xhtml"))
    book.save_text("styles/stylesheet_001-025.css", load_fixture("fxl_stylesheet_head_0642572230319.css"))
    book.fixed_layout = True
    return book


def test_prepare_fixed_layout_does_nothing_for_a_reflowable_book(tmp_path, load_fixture):
    book = fxl_book(tmp_path, load_fixture)
    book.fixed_layout = False
    before = read(book, "styles/stylesheet_001-025.css"), read(book, BASELINE), read(book, "xhtml/page008.xhtml")
    book.prepare_fixed_layout()

    assert (read(book, "styles/stylesheet_001-025.css"), read(book, BASELINE),
            read(book, "xhtml/page008.xhtml")) == before


def test_prepare_fixed_layout_pins_the_canvas_bakes_the_scale_and_adds_a_viewport(tmp_path, load_fixture):
    book = fxl_book(tmp_path, load_fixture)
    original = read(book, "styles/stylesheet_001-025.css")
    width, height = SafariBooks.detect_page_size(original)
    book.prepare_fixed_layout()

    assert book.page_size == (width, height)
    base = open(os.path.join(book.css_path, "Style_Base.css"), encoding="utf-8").read()
    assert "width:%dpx" % width in base and "height:%dpx" % height in base
    assert "scale(.25)" not in read(book, "styles/stylesheet_001-025.css").replace(" ", "")
    page = read(book, "xhtml/page008.xhtml")
    assert page.count('name="viewport"') == 1
    assert 'content="width=%d, height=%d"' % (width, height) in page


def test_prepare_fixed_layout_is_idempotent_on_a_resumed_run(tmp_path, load_fixture):
    book = fxl_book(tmp_path, load_fixture)
    book.prepare_fixed_layout()
    once = (read(book, "styles/stylesheet_001-025.css"), read(book, "xhtml/page008.xhtml"))
    book.prepare_fixed_layout()

    assert (read(book, "styles/stylesheet_001-025.css"), read(book, "xhtml/page008.xhtml")) == once


def test_prepare_fixed_layout_does_not_add_a_viewport_to_the_nav_document(tmp_path, load_fixture):
    book = fxl_book(tmp_path, load_fixture)
    nav = entry("nav.xhtml", "chapter", "application/xhtml+xml", "0642572230319")
    book.plan["chapter"].append(nav)
    book.save_text("nav.xhtml", "<html><head><title>t</title></head><body/></html>")
    book.prepare_fixed_layout()

    assert "viewport" not in read(book, "nav.xhtml")


def test_the_real_fixed_layout_stylesheet_survives_baking_with_its_positions_untouched(load_fixture):
    css = load_fixture("fxl_stylesheet_head_0642572230319.css")
    baked = SafariBooks.bake_fixed_layout_scale(css)

    def declarations(text, prop):
        import re
        return re.findall(r"\b%s:\s*[-\d.]+px" % prop, text)

    assert declarations(css, "left") == declarations(baked, "left")
    assert declarations(css, "top") == declarations(baked, "top")
    assert baked != css


# ---------------------------------------------------------------- polish gating
def test_polish_is_skipped_for_fixed_layout_books_and_when_images_are_left_alone(tmp_path):
    book = make_book(tmp_path, BOOK)
    args = book.args
    assert book.should_polish(args) is True

    book.fixed_layout = True
    assert book.should_polish(args) is False

    book.fixed_layout = False
    args.no_optimize_images = True
    assert book.should_polish(args) is False


def test_polish_epub_reports_a_missing_calibre_and_leaves_the_epub_alone(tmp_path, monkeypatch):
    book = make_book(tmp_path, BOOK)
    epub = tmp_path / "a.epub"
    epub.write_bytes(b"epub")
    monkeypatch.setattr("safaribooks.shutil.which", lambda name: None)

    assert SafariBooks.polish_epub(str(epub), book.display) is False
    assert epub.read_bytes() == b"epub"
    assert any("ebook-polish" in m for m in book.display.of("info"))


def test_polish_epub_replaces_the_epub_only_on_success(tmp_path, monkeypatch):
    book = make_book(tmp_path, BOOK)
    epub = tmp_path / "a.epub"
    epub.write_bytes(b"old")
    monkeypatch.setattr("safaribooks.shutil.which", lambda name: "/bin/ebook-polish")

    class Done:
        def __init__(self, code):
            self.returncode, self.stderr = code, "boom"

    def run_ok(cmd, **kw):
        open(cmd[-1], "wb").write(b"polished")
        return Done(0)

    monkeypatch.setattr("safaribooks.subprocess.run", run_ok)
    assert SafariBooks.polish_epub(str(epub), book.display) is True and epub.read_bytes() == b"polished"

    def run_bad(cmd, **kw):
        open(cmd[-1], "wb").write(b"half")
        return Done(1)

    epub.write_bytes(b"old")
    monkeypatch.setattr("safaribooks.subprocess.run", run_bad)
    assert SafariBooks.polish_epub(str(epub), book.display) is False
    assert epub.read_bytes() == b"old" and not os.path.exists(str(epub) + ".polishing")
