import stat
from pathlib import Path

import pytest

from resume_tailor.contracts import (
    ConfirmationEntry,
    ConfirmationRecords,
    EvidenceBullet,
    FactCandidates,
    RedactionSummary,
    SourceBlock,
    SourceText,
    UnparsedSection,
    WorkExperienceFact,
    content_sha256,
    sha256_json,
)
from resume_tailor.exchange import (
    build_fact_snapshot,
    extract_source_text,
    validate_fact_candidates,
)
from resume_tailor.storage import ProtocolError


def _write_candidates(path: Path, candidates: FactCandidates) -> None:
    path.write_text(candidates.model_dump_json(), encoding="utf-8")


def _candidate(source_blocks: list[tuple[str, str]]) -> FactCandidates:
    bullets = [
        EvidenceBullet(
            fact_id=f"fact_{index}",
            raw_source_text=statement,
            source_kind="resume_extract",
            source_block_ids=[block_id],
            verified_statement=statement,
        )
        for index, (block_id, statement) in enumerate(source_blocks, start=1)
    ]
    return FactCandidates(
        work_experiences=[
            WorkExperienceFact(
                exp_id="exp_backend",
                company_name="Synthetic Systems",
                role_title="Engineer",
                start_date="2020",
                end_date="2022",
                bullets=bullets,
            )
        ]
    )


def _candidate_with_quote(
    source_block_ids: list[str],
    statement: str,
    *,
    unparsed_block_ids: list[str] | None = None,
) -> FactCandidates:
    return FactCandidates(
        work_experiences=[
            WorkExperienceFact(
                exp_id="exp_backend",
                company_name="Synthetic Systems",
                role_title="Engineer",
                start_date="2020",
                end_date="2022",
                bullets=[
                    EvidenceBullet(
                        fact_id="fact_1",
                        raw_source_text=statement,
                        source_kind="resume_extract",
                        source_block_ids=source_block_ids,
                        verified_statement=statement,
                    )
                ],
            )
        ],
        unparsed_sections=[
            UnparsedSection(title="Other", source_block_ids=unparsed_block_ids)
        ]
        if unparsed_block_ids
        else [],
    )


def _write_source_blocks(path: Path, texts: list[str]) -> SourceText:
    source = SourceText(
        source_sha256="a" * 64,
        format="pdf",
        extractor="pypdf",
        extractor_version="1",
        blocks=[
            SourceBlock(block_id=f"block_{index}", text=text)
            for index, text in enumerate(texts, start=1)
        ],
        redaction=RedactionSummary(enabled=True),
    )
    path.write_text(source.model_dump_json(), encoding="utf-8")
    return source


def test_extract_redacts_contact_details_to_private_sidecars(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    output_path = tmp_path / "source.json"
    source_path.write_text(
        "Engineer 2020-2022\n2019 - 2023\nreader@example.test\n"
        "+1 202 555 0146\nhttps://example.test/profile",
        encoding="utf-8",
    )

    source, outputs = extract_source_text(source_path, output_path)
    serialized_source = output_path.read_text(encoding="utf-8")

    assert source.redaction.enabled is True
    assert source.redaction.counts == {"email": 1, "link": 1, "phone": 1}
    assert "reader@example.test" not in serialized_source
    assert "+1 202 555 0146" not in serialized_source
    assert "https://example.test/profile" not in serialized_source
    assert "2020-2022" in serialized_source
    assert "2019 - 2023" in serialized_source
    assert len(outputs) == 3
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in outputs)
    mapping_path = next(path for path in outputs if path.name.endswith("redaction.json"))
    assert "reader@example.test" in mapping_path.read_text(encoding="utf-8")


def test_extract_is_deterministic_and_never_overwrites(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built an API service.", encoding="utf-8")
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first, _ = extract_source_text(source_path, first_path)
    second, _ = extract_source_text(source_path, second_path)

    assert [block.block_id for block in first.blocks] == [block.block_id for block in second.blocks]
    with pytest.raises(ProtocolError, match="already exists"):
        extract_source_text(source_path, first_path)
    assert first_path.exists()


def test_validate_facts_rejects_nonverbatim_source_claim(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built an API service.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates = _candidate([(source.blocks[0].block_id, "Designed a cloud platform.")])
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(candidates_path, candidates)

    with pytest.raises(ProtocolError) as error:
        validate_fact_candidates(
            source_path=tmp_path / "source.json",
            candidates_path=candidates_path,
        )

    assert error.value.blocked is True
    assert error.value.code == "source_quote_not_found"


def test_validate_facts_accepts_quote_across_consecutive_source_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source = _write_source_blocks(
        source_path,
        [
            "Built a forecasting agent that investigates pipeline",
            "failures and reduces triage time.",
        ],
    )
    quote = "Built a forecasting agent that investigates pipeline failures and reduces triage time."
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        _candidate_with_quote(
            [source.blocks[0].block_id, source.blocks[1].block_id],
            quote,
        ),
    )

    validate_fact_candidates(source_path, candidates_path, tmp_path / "ledger.md")

    assert (tmp_path / "ledger.md").exists()


def test_validate_facts_accepts_hyphenated_pdf_line_wrap(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source = _write_source_blocks(
        source_path,
        ["Delivered an emulator integrated into Rolls-\nRoyce suite."],
    )
    quote = "Delivered an emulator integrated into Rolls-Royce suite."
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        _candidate_with_quote([source.blocks[0].block_id], quote),
    )

    validate_fact_candidates(source_path, candidates_path, tmp_path / "ledger.md")

    assert (tmp_path / "ledger.md").exists()


def test_validate_facts_does_not_join_nonconsecutive_source_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    source = _write_source_blocks(
        source_path,
        ["Built a model for", "An unrelated note.", "forecast triage."],
    )
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        _candidate_with_quote(
            [source.blocks[0].block_id, source.blocks[2].block_id],
            "Built a model for forecast triage.",
            unparsed_block_ids=[source.blocks[1].block_id],
        ),
    )

    with pytest.raises(ProtocolError) as error:
        validate_fact_candidates(source_path, candidates_path, tmp_path / "ledger.md")

    assert error.value.code == "source_quote_not_found"


def test_validate_facts_rejects_empty_source_quote(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built an API service.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(candidates_path, _candidate([(source.blocks[0].block_id, "")]))

    with pytest.raises(ProtocolError) as error:
        validate_fact_candidates(tmp_path / "source.json", candidates_path)

    assert error.value.code == "missing_source_quote"


def test_validate_facts_rejects_unaccounted_source_blocks(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built an API service.\nWon an award.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        _candidate([(source.blocks[0].block_id, source.blocks[0].text)]),
    )

    with pytest.raises(ProtocolError) as error:
        validate_fact_candidates(tmp_path / "source.json", candidates_path)

    assert error.value.code == "source_blocks_unaccounted"


def test_validate_facts_returns_unparsed_block_ids_not_titles(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Synthetic content not yet modeled.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        FactCandidates(
            unparsed_sections=[
                UnparsedSection(
                    title="Other",
                    source_block_ids=[source.blocks[0].block_id],
                )
            ]
        ),
    )

    _, _, _, unparsed_block_ids = validate_fact_candidates(
        tmp_path / "source.json", candidates_path, tmp_path / "ledger.md"
    )

    assert unparsed_block_ids == [[source.blocks[0].block_id]]


def test_confirmation_ledger_uses_one_source_level_approval(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built a synthetic API service.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(
        candidates_path,
        _candidate([(source.blocks[0].block_id, source.blocks[0].text)]),
    )
    ledger_path = tmp_path / "ledger.md"

    validate_fact_candidates(tmp_path / "source.json", candidates_path, ledger_path)
    ledger = ledger_path.read_text(encoding="utf-8")

    assert "One source-level confirmation covers all facts" in ledger
    assert "High-risk labels are informational" in ledger
    assert "do not request a second typed confirmation" in ledger
    assert "HIGH RISK" in ledger
    assert "- [ ]" not in ledger


def test_build_snapshot_saves_versioned_profile_under_private_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source_path = tmp_path / "resume.txt"
    source_path.write_text("Built a synthetic API service.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates = _candidate([(source.blocks[0].block_id, source.blocks[0].text)]).model_copy(
        update={"user_id": "resume_owner"}
    )
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(candidates_path, candidates)
    ledger_path = tmp_path / "ledger.md"
    _, ledger_hash, _, _ = validate_fact_candidates(
        tmp_path / "source.json", candidates_path, ledger_path
    )
    experience = candidates.work_experiences[0]
    bullet = experience.bullets[0]
    confirmations = ConfirmationRecords(
        ledger_sha256=ledger_hash,
        entries=[
            ConfirmationEntry(
                object_type="work_experience",
                object_id=experience.exp_id,
                content_sha256=content_sha256(experience),
                decision="confirmed",
            ),
            ConfirmationEntry(
                object_type="evidence_bullet",
                object_id=bullet.fact_id,
                content_sha256=content_sha256(bullet),
                decision="confirmed",
            ),
        ],
    )
    confirmations_path = tmp_path / "confirmations.json"
    confirmations_path.write_text(confirmations.model_dump_json(), encoding="utf-8")

    snapshot = build_fact_snapshot(
        candidates_path,
        confirmations_path,
        None,
        profile_name="resume_owner",
        profile_source_path=tmp_path / "source.json",
    )
    profile_path = (
        tmp_path
        / "private_data"
        / "profiles"
        / "resume_owner"
        / f"profile-v0001-{source.source_sha256}.json"
    )

    assert snapshot.schema_version == 2
    assert snapshot.profile_name == "resume_owner"
    assert snapshot.resume_source_sha256 == source.source_sha256
    assert snapshot.fact_base.user_id == "resume_owner"
    assert profile_path.exists()
    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(profile_path.parent.stat().st_mode) == 0o700


def test_snapshot_contains_only_confirmed_bullets_and_is_immutable(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Built an API service.\nAdded request tracing.", encoding="utf-8")
    source, _ = extract_source_text(source_path, tmp_path / "source.json")
    candidates = _candidate([(block.block_id, block.text) for block in source.blocks])
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(candidates_path, candidates)
    ledger_path = tmp_path / "ledger.md"
    _, ledger_hash, _, _ = validate_fact_candidates(
        source_path=tmp_path / "source.json",
        candidates_path=candidates_path,
        ledger_out=ledger_path,
    )
    experience = candidates.work_experiences[0]
    first_bullet = experience.bullets[0]
    confirmations = ConfirmationRecords(
        ledger_sha256=ledger_hash,
        entries=[
            ConfirmationEntry(
                object_type="work_experience",
                object_id=experience.exp_id,
                content_sha256=content_sha256(experience),
                decision="confirmed",
            ),
            ConfirmationEntry(
                object_type="evidence_bullet",
                object_id=first_bullet.fact_id,
                content_sha256=content_sha256(first_bullet),
                decision="confirmed",
            ),
        ],
    )
    confirmations_path = tmp_path / "confirmations.json"
    confirmations_path.write_text(confirmations.model_dump_json(), encoding="utf-8")
    snapshot_path = tmp_path / "snapshot.json"

    snapshot = build_fact_snapshot(candidates_path, confirmations_path, snapshot_path)

    assert [bullet.fact_id for bullet in snapshot.fact_base.work_experiences[0].bullets] == [
        first_bullet.fact_id
    ]
    assert snapshot.fact_base.work_experiences[0].bullets[0].user_confirmed is True
    assert snapshot.snapshot_sha256 == sha256_json(snapshot.fact_base)
    original = snapshot_path.read_text(encoding="utf-8")
    with pytest.raises(ProtocolError, match="already exists"):
        build_fact_snapshot(candidates_path, confirmations_path, snapshot_path)
    assert snapshot_path.read_text(encoding="utf-8") == original


def test_snapshot_rejects_stale_ledger_hash(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.json"
    _write_candidates(candidates_path, FactCandidates())
    confirmations = ConfirmationRecords(ledger_sha256="0" * 64, entries=[])
    confirmations_path = tmp_path / "confirmations.json"
    confirmations_path.write_text(confirmations.model_dump_json(), encoding="utf-8")

    with pytest.raises(ProtocolError) as error:
        build_fact_snapshot(candidates_path, confirmations_path, tmp_path / "snapshot.json")

    assert error.value.code == "ledger_hash_mismatch"
    assert not (tmp_path / "snapshot.json").exists()