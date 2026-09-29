"""The catalogue synopsis: bullet-prefixed lines become real <ul>/<ol> lists.

The catalogue ships a list as one paragraph of `<br/>`-separated lines that start with a bullet character
(or as a paragraph per item), so readers show a run-on block of text. The skeletons below match a real
synopsis; the words are invented.
"""
import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))

from safaribooks import SafariBooks  # noqa: E402
from test_package import DEFAULT_MANIFEST, DEFAULT_SPINE, FILES, NOW, NS, on_disk, opf_xml, patch, text_of  # noqa: E402

B = "\u2022"
listify = SafariBooks.listify_description


def test_a_br_separated_bullet_paragraph_becomes_one_ul():
    source = ("<span><div><p>Intro.</p><p>You will build:</p>"
              "<p>{b}Alpha<br/>{b}Beta<br/>{b}Gamma</p><p>Outro.</p></div></span>").format(b=B)

    assert listify(source) == ("<span><div><p>Intro.</p><p>You will build:</p>"
                               "<ul><li>Alpha</li><li>Beta</li><li>Gamma</li></ul><p>Outro.</p></div></span>")


def test_one_paragraph_per_bullet_is_merged_into_a_single_list():
    source = "<div><p>Learn:</p><p>{b}One</p><p>{b}Two</p><p>{b}Three</p></div>".format(b=B)

    assert listify(source) == "<div><p>Learn:</p><ul><li>One</li><li>Two</li><li>Three</li></ul></div>"


def test_text_before_the_first_bullet_in_the_same_paragraph_stays_a_paragraph():
    source = "<div><p>You will learn:<br/>{b}One<br/>{b}Two</p></div>".format(b=B)

    assert listify(source) == "<div><p>You will learn:</p><ul><li>One</li><li>Two</li></ul></div>"


def test_text_after_the_last_bullet_in_the_same_paragraph_stays_a_paragraph():
    source = "<div><p>{b}One<br/>{b}Two<br/>And that is all.</p></div>".format(b=B)

    assert listify(source) == "<div><ul><li>One</li><li>Two</li></ul><p>And that is all.</p></div>"


@pytest.mark.parametrize("char", ["\u2022", "\u25cf", "\u25aa", "\u25e6", "\u2023", "\u2219"])
def test_every_common_bullet_character_is_recognised(char):
    assert listify("<div><p>%sOne<br/>%sTwo</p></div>" % (char, char)) == "<div><ul><li>One</li><li>Two</li></ul></div>"


def test_a_space_after_the_bullet_is_dropped_from_the_item():
    assert listify("<div><p>{b} One<br/>{b}  Two</p></div>".format(b=B)) == "<div><ul><li>One</li><li>Two</li></ul></div>"


def test_inline_markup_inside_an_item_is_kept():
    source = "<div><p>{b}<b>Bold</b> and <i>italic</i> text<br/>{b}Plain</p></div>".format(b=B)

    assert listify(source) == ("<div><ul><li><b>Bold</b> and <i>italic</i> text</li><li>Plain</li></ul></div>")


def test_numbered_lines_counting_from_one_become_an_ol():
    source = "<div><p>Steps:</p><p>1. First<br/>2. Second<br/>3. Third</p></div>"

    assert listify(source) == "<div><p>Steps:</p><ol><li>First</li><li>Second</li><li>Third</li></ol></div>"


@pytest.mark.parametrize("text", [
    "<div><p>1. Only one</p></div>",                           # a single number is a sentence, not a list
    "<div><p>2. Second<br/>3. Third</p></div>",                # does not start at 1
    "<div><p>1. First<br/>3. Third</p></div>",                 # not consecutive
    "<div><p>The year was 1999. It was fine.</p></div>",       # a number inside a sentence
])
def test_numbers_that_are_not_a_list_are_left_alone(text):
    assert listify(text) == text


def test_a_bulleted_run_and_a_numbered_run_in_one_paragraph_become_two_lists():
    source = "<div><p>{b}Alpha<br/>{b}Beta<br/>1. One<br/>2. Two</p></div>".format(b=B)

    assert listify(source) == "<div><ul><li>Alpha</li><li>Beta</li></ul><ol><li>One</li><li>Two</li></ol></div>"


def test_a_synopsis_without_lists_is_returned_untouched():
    # including inline tags followed by text: nothing may be dropped or reordered
    source = "<span><div><p><i>Title</i> is a book.</p><p><b>Bold</b><i>it</i> closing.</p></div></span>"

    assert listify(source) == source


def test_tails_after_inline_elements_survive_next_to_a_list():
    source = "<div><p><i>Title</i> more text.</p><p>{b}One<br/>{b}Two</p><p><b>B</b> end.</p></div>".format(b=B)

    assert listify(source) == ("<div><p><i>Title</i> more text.</p><ul><li>One</li><li>Two</li></ul>"
                               "<p><b>B</b> end.</p></div>")


def test_text_that_is_not_markup_and_blank_values_pass_through():
    for value in ("", None, "plain text with no tags"):
        assert listify(value) == value


def test_a_bullet_in_the_middle_of_a_line_is_not_a_list_item():
    source = "<div><p>Costs 5 {b} 6 dollars<br/>and more</p></div>".format(b=B)

    assert listify(source) == source


def test_markup_with_a_bullet_but_no_list_is_returned_byte_for_byte():
    # A bullet character triggers the parse; when nothing turns into a list, the caller must get the
    # original string back, not a re-serialisation (entities, quotes and <br/> spelling would change).
    source = "<div><p class='x'>It&#8217;s 5 {b} 6 &amp; more<br/>Line two</p></div>".format(b=B)

    assert listify(source) == source


def test_a_br_between_plain_lines_next_to_a_list_keeps_its_xml_spelling():
    # Serialising with the HTML writer would turn <br/> into <br>
    source = "<div><p>Line one<br/>Line two<br/>{b}One<br/>{b}Two</p></div>".format(b=B)

    assert listify(source) == "<div><p>Line one<br/>Line two</p><ul><li>One</li><li>Two</li></ul></div>"


def test_a_real_list_is_left_as_it_is():
    source = "<div><p>Learn:</p><ul><li>One</li><li>Two</li></ul></div>"

    assert listify(source) == source


def test_the_result_is_well_formed_markup():
    source = "<span><div><p>Intro &amp; more.</p><p>{b}A &lt; B<br/>{b}C &amp; D</p></div></span>".format(b=B)
    out = listify(source)

    etree.fromstring(out)
    assert "<li>A &lt; B</li><li>C &amp; D</li>" in out and "Intro &amp; more." in out


def test_listify_is_idempotent():
    source = "<div><p>{b}One<br/>{b}Two</p><p>1. A<br/>2. B</p></div>".format(b=B)
    once = listify(source)

    assert listify(once) == once


# ------------------------------------------------------------- through the OPF patch
def test_the_patched_opf_carries_the_synopsis_with_real_lists(tmp_path):
    source = "<span><div><p>Intro.</p><p>{b}One<br/>{b}Two</p></div></span>".format(b=B)
    root = patch(tmp_path, book_info={"description": source})

    assert text_of(root, "description") == ["<span><div><p>Intro.</p><ul><li>One</li><li>Two</li></ul></div></span>"]


def test_the_opf_is_patched_with_real_lists_even_over_the_publishers_flat_synopsis(tmp_path):
    flat = "Intro.{b}One{b}Two".format(b=B)
    opf = opf_xml(metadata="<dc:description>%s</dc:description>" % flat, manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE)
    root = patch(tmp_path, opf, book_info={"description": "<div><p>{b}One<br/>{b}Two</p></div>".format(b=B)})

    assert text_of(root, "description") == ["<div><ul><li>One</li><li>Two</li></ul></div>"]


def test_the_list_markup_is_escaped_in_the_file_and_parses_back(tmp_path):
    raw = SafariBooks.patch_opf_document(
        opf_xml(manifest=DEFAULT_MANIFEST, spine=DEFAULT_SPINE), "content.opf", on_disk(tmp_path, FILES),
        now=NOW, book_info={"description": "<div><p>{b}One<br/>{b}Two</p></div>".format(b=B)})

    assert b"&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;li&gt;Two&lt;/li&gt;&lt;/ul&gt;" in raw
    assert etree.fromstring(raw).findtext("opf:metadata/dc:description", namespaces=NS) == \
        "<div><ul><li>One</li><li>Two</li></ul></div>"
