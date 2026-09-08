"""The Customer Quality Desk's documents say what the endpoint serves, and nothing the plant keeps.

`customer_documents.py` names the three documents the desk may read and the
reasons the rest stay out; `customer_projection.py` names the words and the
windows the customer status endpoint serves. These tests pin the two to each
other, so a promise in a document is the promise the status answer computes,
and hold the boundary from the document side: no simulated employee name, no
internal field name and none of the superseded guide's values appears in a
document a customer may read.
"""

import pathlib

import pytest

import customer_documents

ROOT = pathlib.Path(__file__).resolve().parent.parent


def included_texts():
    return {entry["source"]: (customer_documents.CUSTOMER_DOCS / entry["file"]).read_text(encoding="utf-8")
            for entry in customer_documents.INCLUDED}


def test_the_three_documents_exist_and_carry_their_headers():
    texts = included_texts()
    assert len(texts) == 3
    for entry in customer_documents.INCLUDED:
        text = texts[entry["source"]]
        assert "approved for customer use" in text, entry["file"]
        assert "fictional company" in text, entry["file"]


def test_the_guide_states_every_customer_word_of_the_projection():
    guide = included_texts()["Customer_Complaint_Handling_Guide_2026"]
    for word in customer_documents.vocabulary():
        assert word in guide, "the guide does not state %r" % word


def test_the_commitments_document_states_every_next_step():
    commitments = included_texts()["Quality_Commitments_and_Escalation_Contacts"]
    for stage in customer_documents.CUSTOMER_STAGES.values():
        if stage["next_step"]:
            assert stage["next_step"] in commitments, stage["next_step"]


@pytest.mark.parametrize("source", ["Customer_Complaint_Handling_Guide_2026", "Quality_Commitments_and_Escalation_Contacts"])
def test_both_commitment_documents_state_every_window(source):
    """Rendered from the numbers, so a changed window fails here until the documents change."""
    text = included_texts()[source]
    for phrase in customer_documents.commitment_phrases():
        assert phrase in text, "%s does not state %r" % (source, phrase)


def test_the_reference_format_is_quoted_where_a_customer_needs_it():
    texts = included_texts()
    for source in ("Customer_Complaint_Handling_Guide_2026", "Complaint_Submission_Checklist"):
        assert customer_documents.REFERENCE_FORMAT in texts[source], source
    assert customer_documents.REFERENCE_EXAMPLE in texts["Customer_Complaint_Handling_Guide_2026"]


def test_no_simulated_employee_is_named_in_a_customer_document():
    names = customer_documents.roster_names()
    assert names, "the roster is empty"
    for source, text in included_texts().items():
        for name in names:
            assert name not in text, "%s names %s" % (source, name)


def test_no_internal_field_name_appears_in_a_customer_document():
    for source, text in included_texts().items():
        assert customer_documents.internal_name_hits(text) == [], source


def test_no_superseded_value_appears_in_a_customer_document():
    for source, text in included_texts().items():
        for value in customer_documents.SUPERSEDED_VALUES:
            assert value not in text, "%s carries the superseded %r" % (source, value)


def test_the_written_distractors_carry_their_markers_and_their_reasons():
    superseded = (ROOT / "docs/customer/excluded/Customer_Complaint_Handling_Guide_2025.md").read_text(encoding="utf-8")
    draft = (ROOT / "docs/customer/excluded/Customer_Letter_Template_DRAFT.md").read_text(encoding="utf-8")
    assert "SUPERSEDED" in superseded
    assert any(value in superseded for value in customer_documents.SUPERSEDED_VALUES)
    assert "NOT APPROVED FOR CUSTOMER USE" in draft
    for entry in customer_documents.EXCLUDED:
        if entry["marker"]:
            text = (ROOT / entry["path"]).read_text(encoding="utf-8")
            assert entry["marker"] in text, entry["path"]


def test_every_source_label_is_unique_and_matches_its_file():
    sources = [entry["source"] for entry in customer_documents.INCLUDED]
    assert len(set(sources)) == len(sources)
    for entry in customer_documents.INCLUDED:
        assert entry["file"] == entry["source"] + ".md"


def test_paragraphs_fit_the_chunk_size_where_it_matters():
    """A paragraph longer than the chunk is split mid-fact. The stage paragraphs
    of the guide, which carry a status, a next step and a window together, must
    each fit one chunk; elsewhere an overrun is tolerated and reported."""
    guide = included_texts()["Customer_Complaint_Handling_Guide_2026"]
    stage_paragraphs = [p for p in guide.split("\n\n") if p.startswith("At stage ")]
    assert len(stage_paragraphs) == 5
    for paragraph in stage_paragraphs:
        assert len(paragraph) <= customer_documents.CHUNK_SIZE, paragraph[:60]


def test_the_ingestion_workflow_carries_the_documents_verbatim():
    import json

    workflow = json.loads((ROOT / "n8n" / "customer_desk_kb_v1.json").read_text(encoding="utf-8"))
    node = next(n for n in workflow["nodes"] if n["name"] == "Customer Documents")
    for document in customer_documents.read_included():
        assert json.dumps(document["text"], ensure_ascii=True) in node["parameters"]["jsCode"], document["source"]
    store = next(n for n in workflow["nodes"] if n["name"] == "Customer Desk Store")
    assert store["parameters"]["qdrantCollection"]["value"] == customer_documents.COLLECTION
    chunker = next(n for n in workflow["nodes"] if n["name"] == "Chunker")
    assert chunker["parameters"] == {"chunkSize": customer_documents.CHUNK_SIZE,
                                     "chunkOverlap": customer_documents.CHUNK_OVERLAP, "options": {}}
    for name in ("Document Embeddings", "Query Embeddings"):
        embeddings = next(n for n in workflow["nodes"] if n["name"] == name)
        assert embeddings["parameters"]["modelName"] == customer_documents.EMBEDDING_MODEL
