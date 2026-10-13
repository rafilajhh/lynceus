"""Knowledge base loading and BM25 retrieval over the plant documents."""

from __future__ import annotations

from pathlib import Path

import pytest

from lynceus import kb

SOP_IDS = {
    "SOP-RDF-2.1", "SOP-RDF-2.2", "SOP-RDF-3.2", "SOP-RDF-3.3",
    "SOP-RDF-4.1", "SOP-RDF-4.2", "SOP-RDF-4.3", "SOP-RDF-4.4",
    "SOP-RDF-5.1", "SOP-RDF-5.2", "SOP-RDF-5.3", "SOP-RDF-6.1", "SOP-RDF-7.1",
}
REG_IDS = {"REG-HH1", "REG-AP42", "REG-EN15359", "REG-NIOSH-H2S", "REG-IDN-RDF"}


@pytest.fixture(scope="module")
def chunks() -> list[kb.Chunk]:
    return kb.load_chunks()


def test_load_has_every_sop_and_reg_id_unique(chunks):
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert SOP_IDS | REG_IDS <= set(ids)


def test_chunk_fields_are_parsed(chunks):
    by_id = {c.id: c for c in chunks}
    c = by_id["SOP-RDF-5.3"]
    assert c.title == "Apply the contract moisture penalty"
    assert c.source_file == "sop-rdf-gate.md"
    assert c.text.startswith("Moisture is a cost")
    assert "##" not in c.text and "—" not in c.text.split("\n")[0][:5]
    assert by_id["REG-NIOSH-H2S"].source_file == "regulations.md"
    assert all(c.text.strip() and c.title for c in chunks)


def test_default_dir_is_the_package_knowledge_dir():
    assert (Path(kb.__file__).parent / "knowledge" / "regulations.md").is_file()


def test_search_moisture_penalty_wet_load(chunks):
    top = kb.search("moisture penalty wet load", chunks)
    assert top and top[0].id in {"SOP-RDF-5.3", "SOP-RDF-5.1"}


def test_search_hydrogen_sulfide_limit(chunks):
    top = kb.search("hydrogen sulfide limit", chunks)
    assert top[0].id == "REG-NIOSH-H2S"


def test_empty_and_unmatched_query_return_empty(chunks):
    assert kb.search("", chunks) == []
    assert kb.search("   !!! ", chunks) == []
    assert kb.search("zzzqqq", chunks) == []
    assert kb.search("moisture", []) == []


def test_k_limits_results_and_only_positive_scores(chunks):
    assert len(kb.search("moisture", chunks, k=2)) == 2
    assert kb.search("moisture", chunks, k=0) == []
    out = kb.search("moisture", chunks, k=100)
    assert 0 < len(out) < len(chunks)


def test_ties_broken_by_chunk_order():
    a = kb.Chunk("A", "alpha", "foo", "x.md")
    b = kb.Chunk("B", "alpha", "foo", "x.md")
    assert [c.id for c in kb.search("foo", [a, b])] == ["A", "B"]
    assert [c.id for c in kb.search("foo", [b, a])] == ["B", "A"]


def test_title_is_indexed():
    a = kb.Chunk("A", "unique heading", "nothing", "x.md")
    b = kb.Chunk("B", "other", "words", "x.md")
    assert [c.id for c in kb.search("heading", [a, b])] == ["A"]


def test_load_from_directory_skips_preamble_and_rejects_duplicates(tmp_path):
    (tmp_path / "one.md").write_text(
        "# Title — ignored\npreamble text\n\n## X-1 — First one\nbody one\n\n## X-2 — Second\nbody two\n",
        encoding="utf-8",
    )
    got = kb.load_chunks(tmp_path)
    assert [(c.id, c.title, c.text, c.source_file) for c in got] == [
        ("X-1", "First one", "body one", "one.md"),
        ("X-2", "Second", "body two", "one.md"),
    ]
    (tmp_path / "two.md").write_text("## X-2 — Dup\nz\n", encoding="utf-8")
    with pytest.raises(ValueError, match="X-2"):
        kb.load_chunks(tmp_path)


def test_regulation_sections_cite_only_known_sources(chunks):
    reg = {c.id: c for c in chunks if c.id.startswith("REG-")}
    assert "10 ppm" in reg["REG-NIOSH-H2S"].text
    assert "Equation HH-1" in reg["REG-HH1"].text
    assert "Table 2.4-1" in reg["REG-AP42"].text
