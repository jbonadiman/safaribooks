"""Guard the fixture set itself: it must stay public-safe and well-formed."""
import re

import pytest
from lxml import etree

from conftest import FIXTURES

ALL_FIXTURES = sorted(p for p in FIXTURES.iterdir() if p.is_file())

# Anything that looks like a credential or personal data must never be committed.
FORBIDDEN = [
    (re.compile(r"orm-(jwt|rt)", re.I), "O'Reilly session cookie name"),
    (re.compile(r"\bBearer\s+\S+", re.I), "bearer token"),
    (re.compile(r"\b(access|refresh|id)_token\b", re.I), "OAuth token field"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."), "JWT"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "email address"),
    (re.compile(r"password", re.I), "password"),
]


def test_fixture_set_is_not_empty():
    assert len(ALL_FIXTURES) >= 8


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_fixture_has_no_secrets_or_personal_data(path):
    text = path.read_text(encoding="utf-8")
    for pattern, what in FORBIDDEN:
        assert not pattern.search(text), "%s contains a %s" % (path.name, what)


@pytest.mark.parametrize("path", [p for p in ALL_FIXTURES if p.suffix == ".json"], ids=lambda p: p.name)
def test_json_fixtures_parse(load_fixture, path):
    assert load_fixture(path.name) is not None


def test_ncx_fixture_is_a_truncated_head_with_a_readable_docauthor(load_fixture):
    """The capture stops after <docAuthor> on purpose (that is all the author lookup reads),
    so it is not well-formed on its own: parse it leniently and check what matters."""
    text = load_fixture("toc_9781098168827_head.ncx")
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(text.encode("utf-8"))  # truncated: strict parsing must fail
    root = etree.fromstring(text.encode("utf-8"), etree.XMLParser(recover=True))
    ns = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
    assert root.xpath("string(//n:docAuthor/n:text)", namespaces=ns).strip() == "Sebastian Raschka"


def test_files_listing_fixture_has_the_shape_the_downloader_relies_on(load_fixture):
    """/api/v2/epubs/<urn>/files/ is the core of the new pipeline; pin its shape."""
    listing = load_fixture("fxl_files_0642572230319.json")
    assert {"results", "next"} <= set(listing)
    for entry in listing["results"]:
        assert {"url", "full_path", "media_type", "kind"} <= set(entry), entry
