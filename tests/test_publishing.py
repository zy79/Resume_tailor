import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, local

import pytest

from resume_tailor import publishing as publishing_module
from resume_tailor.contracts import (
    AcknowledgedWaiver,
    Approval,
    AuditReport,
    CandidateFile,
    CandidateRecord,
    CheckResult,
    Manifest,
    SemanticReview,
    TailoredResumePayload,
    sha256_json,
)
from resume_tailor.publishing import publish_candidate
from resume_tailor.storage import ProtocolError


def _create_candidate(
    root: Path,
    *,
    review_status: str = "PASSED",
    waiver: AcknowledgedWaiver | None = None,
    approval_payload_sha256: str | None = None,
    filename_stem: str = "generated",
) -> tuple[Path, Path]:
    candidate_dir = (
        root
        / "private_data/storage/companies/synthetic-1234567890/jobs/job_synthetic/"
        "runs/run_synthetic/artifact_synthetic"
    )
    candidate_dir.mkdir(parents=True, mode=0o700)
    payload = TailoredResumePayload(snapshot_sha256="a" * 64, selected_skill_ids=[])
    payload_hash = sha256_json(payload)
    review_mode = "SELF_REVIEW" if review_status == "PASSED" else "NONE"
    files_content = {
        f"{filename_stem}.docx": ("resume_docx", b"synthetic-docx"),
        f"{filename_stem}.pdf": ("resume_pdf", b"synthetic-pdf"),
        "payload.json": ("payload", payload.model_dump_json().encode("utf-8")),
    }
    if review_status == "PASSED":
        review = SemanticReview(
            payload_sha256=payload_hash,
            mode="SELF_REVIEW",
            status="PASSED",
            context_isolated=True,
        )
        files_content["semantic_review.json"] = (
            "semantic_review",
            review.model_dump_json().encode("utf-8"),
        )
    audit = AuditReport(
        payload_sha256=payload_hash,
        snapshot_sha256="a" * 64,
        checks=[CheckResult(check="deterministic", passed=True, message="Synthetic pass.")],
        render_path="docx_libreoffice_pdf",
        approval_conditions={
            "deterministic_checks_passed": True,
            "render_health_passed": True,
            "confirmation_summary": {
                "snapshot_sha256": "a" * 64,
                "ledger_sha256": "b" * 64,
                "confirmed_item_count": 1,
                "new_or_modified_facts_in_payload": [],
            },
        },
    )
    files_content["audit_report.json"] = ("audit_report", audit.model_dump_json().encode("utf-8"))
    candidate_files = []
    for filename, (role, content) in files_content.items():
        (candidate_dir / filename).write_bytes(content)
        candidate_files.append(
            CandidateFile(path=filename, role=role, sha256=hashlib.sha256(content).hexdigest())
        )
    candidate = CandidateRecord(
        job_id="job_synthetic",
        run_id="run_synthetic",
        artifact_id="artifact_synthetic",
        company_name="Synthetic Systems",
        role_title="Engineer",
        payload_sha256=payload_hash,
        snapshot_sha256="a" * 64,
        ledger_sha256="b" * 64,
        files=candidate_files,
        review_mode=review_mode,
        review_status=review_status,
        render_path="docx_libreoffice_pdf",
        created_at=datetime.now(UTC),
    )
    (candidate_dir / "candidate.json").write_text(candidate.model_dump_json(), encoding="utf-8")
    approval = Approval(
        candidate_files=candidate_files,
        payload_sha256=approval_payload_sha256 or payload_hash,
        snapshot_sha256="a" * 64,
        company_name="Synthetic Systems",
        role_title="Engineer",
        review_mode=review_mode,
        review_status=review_status,
        acknowledged_waivers=[waiver] if waiver is not None else [],
        approved_at=datetime.now(UTC),
    )
    approval_path = root / "approval.json"
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")
    return candidate_dir, approval_path


def test_publish_reserves_version_and_retry_returns_same_version(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(tmp_path)

    result, exit_code = publish_candidate(candidate_dir, approval_path)
    retried, retry_code = publish_candidate(candidate_dir, approval_path)
    final_dir = Path(result.data["final_dir"])
    manifest_path = final_dir / "manifest.json"
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    assert exit_code == retry_code == 0
    assert result.status == retried.status == "ok"
    assert result.data["version"] == retried.data["version"] == 1
    assert manifest.version == 1
    assert (final_dir / "resume.docx").read_bytes() == b"synthetic-docx"
    assert (final_dir / "resume.pdf").read_bytes() == b"synthetic-pdf"


def test_publish_preserves_timestamped_resume_filename(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    filename_stem = "synthetic-systems-engineer-20260101-120000"
    candidate_dir, approval_path = _create_candidate(
        tmp_path, filename_stem=filename_stem
    )

    result, exit_code = publish_candidate(candidate_dir, approval_path)
    final_dir = Path(result.data["final_dir"])

    assert exit_code == 0
    assert (final_dir / f"{filename_stem}.docx").read_bytes() == b"synthetic-docx"
    assert (final_dir / f"{filename_stem}.pdf").read_bytes() == b"synthetic-pdf"
    assert not (final_dir / "resume.docx").exists()


def test_publish_recovers_after_atomic_file_finalization_fails(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(tmp_path)
    original_replace = os.replace
    fail_once = True

    def fail_first_resume_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal fail_once
        if Path(destination).name == "resume.docx" and fail_once:
            fail_once = False
            raise OSError("simulated interruption")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_first_resume_replace)

    with pytest.raises(ProtocolError, match="atomically finalize"):
        publish_candidate(candidate_dir, approval_path)

    final_version = candidate_dir.parent.parent.parent / "final" / "v1"
    assert not (final_version / "resume.docx").exists()
    assert not list(final_version.glob(".*.tmp"))

    monkeypatch.setattr(os, "replace", original_replace)
    result, exit_code = publish_candidate(candidate_dir, approval_path)

    assert exit_code == 0
    assert result.data["version"] == 1
    assert (final_version / "resume.docx").read_bytes() == b"synthetic-docx"


def test_concurrent_publish_of_same_candidate_uses_one_version(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(tmp_path)
    initial_reservation_barrier = Barrier(2)
    thread_state = local()
    original_find = publishing_module._find_candidate_reservation

    def synchronize_initial_reservation(
        final_dir: Path,
        artifact_id: str,
        candidate_sha256: str,
    ) -> tuple[Path, int] | None:
        reservation = original_find(final_dir, artifact_id, candidate_sha256)
        if not getattr(thread_state, "initial_reservation_checked", False):
            thread_state.initial_reservation_checked = True
            initial_reservation_barrier.wait(timeout=3)
        return reservation

    monkeypatch.setattr(
        publishing_module,
        "_find_candidate_reservation",
        synchronize_initial_reservation,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(publish_candidate, candidate_dir, approval_path)
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    assert all(exit_code == 0 and result.status == "ok" for result, exit_code in results)
    assert [result.data["version"] for result, _ in results] == [1, 1]
    final_dir = candidate_dir.parent.parent.parent / "final"
    assert [path.name for path in final_dir.iterdir() if path.is_dir()] == ["v1"]


def test_publish_requires_a_user_authored_review_waiver(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(tmp_path, review_status="NOT_RUN")

    result, exit_code = publish_candidate(candidate_dir, approval_path)

    assert exit_code == 3
    assert result.status == "blocked"
    assert result.issues[0].code == "semantic_review_waiver_required"
    assert not (candidate_dir.parent.parent.parent / "final").exists()


def test_publish_rejects_none_mode_marked_as_passed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(tmp_path, review_status="NOT_RUN")
    candidate_path = candidate_dir / "candidate.json"
    candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_data["review_status"] = "PASSED"
    candidate_path.write_text(json.dumps(candidate_data), encoding="utf-8")
    approval_data = json.loads(approval_path.read_text(encoding="utf-8"))
    approval_data["review_status"] = "PASSED"
    approval_path.write_text(json.dumps(approval_data), encoding="utf-8")

    result, exit_code = publish_candidate(candidate_dir, approval_path)

    assert exit_code == 3
    assert result.status == "blocked"
    assert result.issues[0].code == "semantic_review_invalid"
    assert not (candidate_dir.parent.parent.parent / "final").exists()


def test_publish_records_an_explicit_review_waiver(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    waiver = AcknowledgedWaiver(
        waiver="semantic_review_not_run",
        user_words="I approve without a semantic review.",
    )
    candidate_dir, approval_path = _create_candidate(
        tmp_path,
        review_status="NOT_RUN",
        waiver=waiver,
    )

    result, exit_code = publish_candidate(candidate_dir, approval_path)
    manifest_path = Path(result.data["manifest_path"])
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert manifest.semantic_review_waived is True


def test_publish_rejects_mismatched_approval_hash_without_writing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    candidate_dir, approval_path = _create_candidate(
        tmp_path,
        approval_payload_sha256="f" * 64,
    )

    result, exit_code = publish_candidate(candidate_dir, approval_path)

    assert exit_code == 3
    assert result.status == "blocked"
    assert result.issues[0].code == "approval_payload_mismatch"
    assert not (candidate_dir.parent.parent.parent / "final").exists()


def test_publish_rejects_candidates_outside_managed_storage(tmp_path: Path) -> None:
    external_candidate = tmp_path / "candidate"
    external_candidate.mkdir()

    with pytest.raises(ProtocolError, match="Only managed candidates"):
        publish_candidate(external_candidate, tmp_path / "approval.json")


def test_publish_rejects_a_symlinked_private_data_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    external_storage = tmp_path / "external-storage"
    external_storage.mkdir()
    (tmp_path / "private_data").symlink_to(external_storage, target_is_directory=True)
    candidate_dir = (
        tmp_path
        / "private_data/storage/companies/company/jobs/job/runs/run/artifact"
    )

    with pytest.raises(ProtocolError, match="Managed storage cannot be a symbolic link"):
        publish_candidate(candidate_dir, tmp_path / "approval.json")