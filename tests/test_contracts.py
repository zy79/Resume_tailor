import pytest
from pydantic import ValidationError

from resume_tailor.contracts import (
    FactCandidates,
    SemanticReview,
    SourceText,
    UnparsedSection,
    content_sha256,
    sha256_json,
)


def test_json_hash_is_canonical_across_mapping_order() -> None:
    assert sha256_json({"alpha": 1, "beta": 2}) == sha256_json({"beta": 2, "alpha": 1})


def test_fact_candidates_are_unconfirmed_by_default() -> None:
    candidates = FactCandidates.model_validate({"schema_version": 1})

    assert candidates.user_id == "local"
    assert candidates.work_experiences == []


def test_semantic_review_cannot_pass_without_a_review_mode() -> None:
    with pytest.raises(ValidationError):
        SemanticReview(
            payload_sha256="0" * 64,
            mode="NONE",
            status="PASSED",
        )


def test_unparsed_section_title_is_bounded_and_single_line() -> None:
    with pytest.raises(ValidationError):
        UnparsedSection(title="x" * 121, source_block_ids=["blk_source"])


def test_newer_source_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceText.model_validate(
            {
                "schema_version": 2,
                "source_sha256": "0" * 64,
                "format": "txt",
                "extractor": "plain-text",
                "extractor_version": "1",
                "blocks": [],
                "redaction": {"enabled": True},
            }
        )


def test_fact_content_hash_changes_with_fact_content() -> None:
    first = FactCandidates.model_validate({"schema_version": 1})
    second = first.model_copy(update={"version": 2})

    assert content_sha256(first) != content_sha256(second)