from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from resume_tailor.contracts import (
    Approval,
    ArtifactInfo,
    AuditReport,
    CandidateFile,
    CandidateRecord,
    CliIssue,
    CliResult,
    Manifest,
    SemanticReview,
    TailoredResumePayload,
    canonical_json_bytes,
    sha256_json,
)
from resume_tailor.rendering import RENDERER_VERSION
from resume_tailor.storage import (
    ProtocolError,
    ensure_private_directory,
    file_sha256,
    read_json_value,
    read_model,
    write_atomic_exclusive,
    write_atomic_replace,
)

_VERSION_DIRECTORY = re.compile(r"^v([1-9][0-9]*)$")
_FINAL_NAMES = {
    "resume_docx": "resume.docx",
    "resume_markdown": "resume.md",
    "resume_pdf": "resume.pdf",
    "payload": "payload.json",
    "semantic_review": "semantic_review.json",
    "audit_report": "audit_report.json",
}
_RESUME_FILENAME_STEM = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d{8}-\d{6}$")
_RESUME_SUFFIXES = {
    "resume_docx": ".docx",
    "resume_markdown": ".md",
    "resume_pdf": ".pdf",
}


def _blocked(code: str, message: str, **data: Any) -> tuple[CliResult, int]:
    return (
        CliResult(
            command="publish",
            status="blocked",
            issues=[CliIssue(code=code, severity="error", message=message)],
            data=data,
        ),
        3,
    )


def _prompt_bytes() -> bytes:
    prompt_resource = resources.files("resume_tailor").joinpath("PROMPT.md")
    try:
        if prompt_resource.is_file():
            return prompt_resource.read_bytes()
        return (Path(__file__).resolve().parents[2] / "PROMPT.md").read_bytes()
    except OSError as error:
        raise ProtocolError("PROMPT.md is required for publishing.") from error


def _managed_candidate_path(value: str | Path) -> Path:
    supplied = Path(value).expanduser()
    if "\0" in str(supplied) or ".." in supplied.parts:
        raise ProtocolError("Candidate path is not allowed.", code="unsafe_path")
    private_root = Path("private_data").absolute()
    storage_path = private_root / "storage"
    if private_root.is_symlink() or storage_path.is_symlink():
        raise ProtocolError("Managed storage cannot be a symbolic link.", code="unsafe_path")
    supplied_absolute = supplied.absolute()
    if not supplied_absolute.is_relative_to(storage_path):
        raise ProtocolError("Only managed candidates can be published.", code="unsafe_path")
    current = storage_path
    for part in supplied_absolute.relative_to(storage_path).parts:
        current = current / part
        if current.is_symlink():
            raise ProtocolError("Candidate path contains a symbolic link.", code="unsafe_path")
    try:
        resolved_storage = storage_path.resolve(strict=True)
        resolved_candidate = supplied_absolute.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ProtocolError("Candidate directory is missing or inaccessible.") from error
    if not resolved_candidate.is_relative_to(resolved_storage):
        raise ProtocolError("Candidate path escapes managed storage.", code="unsafe_path")
    if not resolved_candidate.is_dir():
        raise ProtocolError("Candidate path is not a directory.")
    return resolved_candidate


def _candidate_source_files(
    candidate_dir: Path,
    candidate: CandidateRecord,
) -> tuple[dict[str, tuple[str, bytes]], dict[str, CandidateFile]]:
    files: dict[str, tuple[str, bytes]] = {}
    by_role: dict[str, CandidateFile] = {}
    seen_paths: set[str] = set()
    for entry in candidate.files:
        relative = Path(entry.path)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {
            ".",
            "..",
            "candidate.json",
            "manifest.json",
        }:
            raise ProtocolError("Candidate file path is invalid.", code="candidate_file_path")
        if entry.role in by_role or entry.path in seen_paths or entry.role not in _FINAL_NAMES:
            raise ProtocolError("Candidate file list is invalid.", code="candidate_file_list")
        source = candidate_dir / entry.path
        if source.is_symlink() or not source.is_file():
            raise ProtocolError(
                "A candidate file is missing or unsafe.", code="candidate_file_missing"
            )
        if file_sha256(source) != entry.sha256:
            raise ProtocolError(
                "A candidate file hash does not match its record.",
                code="candidate_hash_mismatch",
            )
        final_name = _FINAL_NAMES[entry.role]
        expected_suffix = _RESUME_SUFFIXES.get(entry.role)
        if (
            expected_suffix is not None
            and relative.suffix == expected_suffix
            and _RESUME_FILENAME_STEM.fullmatch(relative.stem)
        ):
            final_name = relative.name
        files[final_name] = (entry.role, source.read_bytes())
        by_role[entry.role] = entry
        seen_paths.add(entry.path)
    return files, by_role


def _candidate_gate(
    candidate_dir: Path,
    candidate: CandidateRecord,
    approval: Approval,
) -> tuple[dict[str, tuple[str, bytes]], dict[str, Any]] | tuple[CliResult, int]:
    if (
        candidate_dir.name != candidate.artifact_id
        or candidate_dir.parent.name != candidate.run_id
        or candidate_dir.parent.parent.name != "runs"
        or candidate_dir.parent.parent.parent.name != candidate.job_id
    ):
        return _blocked(
            "candidate_location_mismatch",
            "Candidate IDs do not match its managed path.",
        )

    files, by_role = _candidate_source_files(candidate_dir, candidate)
    if "resume_pdf" not in by_role or not (
        {"resume_docx", "resume_markdown"} & set(by_role)
    ):
        return _blocked(
            "pdf_artifact_required",
            "A publishable candidate needs a DOCX or Markdown file and a PDF.",
        )
    if "payload" not in by_role or "audit_report" not in by_role:
        return _blocked(
            "candidate_provenance_missing",
            "Candidate payload and audit report are required.",
        )

    payload_path = candidate_dir / by_role["payload"].path
    payload = read_model(payload_path, TailoredResumePayload)
    if sha256_json(payload) != candidate.payload_sha256:
        return _blocked(
            "payload_hash_mismatch",
            "Candidate payload does not match its recorded hash.",
        )

    audit_path = candidate_dir / by_role["audit_report"].path
    audit = read_model(audit_path, AuditReport)
    if (
        audit.payload_sha256 != candidate.payload_sha256
        or audit.snapshot_sha256 != candidate.snapshot_sha256
    ):
        return _blocked(
            "audit_binding_mismatch",
            "Audit report is bound to a different candidate.",
        )
    if any(not check.passed for check in audit.checks):
        return _blocked(
            "deterministic_gate_failed",
            "Candidate has a failed deterministic check.",
        )
    if audit.approval_conditions.get("render_health_passed") is not True:
        return _blocked(
            "render_health_incomplete",
            "PDF health checks must pass before publishing.",
        )

    if candidate.review_mode == "NONE" and candidate.review_status != "NOT_RUN":
        return _blocked(
            "semantic_review_invalid",
            "A candidate without a review mode cannot have a completed review status.",
        )
    if candidate.review_status == "FAILED":
        return _blocked("semantic_review_failed", "A failed semantic review cannot be published.")
    if candidate.review_status == "PASSED":
        review_entry = by_role.get("semantic_review")
        if review_entry is None:
            return _blocked("semantic_review_missing", "A passing review file is required.")
        review = read_model(candidate_dir / review_entry.path, SemanticReview)
        if (
            review.payload_sha256 != candidate.payload_sha256
            or review.mode != candidate.review_mode
            or review.status != "PASSED"
        ):
            return _blocked(
                "semantic_review_stale",
                "Semantic review does not match the candidate.",
            )

    expected_waiver = {
        "NOT_RUN": "semantic_review_not_run",
        "UNAVAILABLE": "semantic_review_unavailable",
    }.get(candidate.review_status)
    if expected_waiver is not None and not any(
        waiver.waiver == expected_waiver and waiver.user_words.strip()
        for waiver in approval.acknowledged_waivers
    ):
        return _blocked(
            "semantic_review_waiver_required",
            "The user must explicitly acknowledge the missing or unavailable review.",
        )
    if candidate.review_status not in {"PASSED", "NOT_RUN", "UNAVAILABLE"}:
        return _blocked("semantic_review_invalid", "Candidate review status is not publishable.")

    if approval.payload_sha256 != candidate.payload_sha256:
        return _blocked("approval_payload_mismatch", "Approval is bound to a different payload.")
    if approval.snapshot_sha256 != candidate.snapshot_sha256:
        return _blocked("approval_snapshot_mismatch", "Approval is bound to a different snapshot.")
    if (
        approval.company_name != candidate.company_name
        or approval.role_title != candidate.role_title
    ):
        return _blocked(
            "approval_job_mismatch",
            "Approval job metadata does not match the candidate.",
        )
    if (
        approval.review_mode != candidate.review_mode
        or approval.review_status != candidate.review_status
    ):
        return _blocked(
            "approval_review_mismatch",
            "Approval review summary does not match the candidate.",
        )
    if len(approval.candidate_files) != len(candidate.files):
        return _blocked(
            "approval_files_mismatch",
            "Approval file list does not match the candidate.",
        )
    expected_files = sorted((item.path, item.role, item.sha256) for item in candidate.files)
    approved_files = sorted(
        (item.path, item.role, item.sha256) for item in approval.candidate_files
    )
    if approved_files != expected_files:
        return _blocked(
            "approval_files_mismatch",
            "Approval file hashes do not match the candidate.",
        )

    prompt_sha = hashlib.sha256(_prompt_bytes()).hexdigest()
    files["approval.json"] = ("approval", canonical_json_bytes(approval) + b"\n")
    return files, {
        "audit_report": audit,
        "prompt_sha256": prompt_sha,
        "semantic_review_waived": expected_waiver is not None,
        "confirmation_summary": audit.approval_conditions.get("confirmation_summary", {}),
    }


def _final_file_records(files: dict[str, tuple[str, bytes]]) -> list[CandidateFile]:
    return [
        CandidateFile(
            path=filename,
            role=role,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        for filename, (role, content) in sorted(files.items())
    ]


def _read_reservation(target: Path) -> dict[str, Any] | None:
    marker = target / ".reservation.json"
    if marker.is_symlink():
        raise ProtocolError("Publish reservation marker is unsafe.", code="unsafe_path")
    if not marker.is_file():
        return None
    value = read_json_value(marker)
    if not isinstance(value, dict):
        raise ProtocolError("Publish reservation marker is invalid.")
    return value


def _wait_for_reservation_marker(target: Path) -> dict[str, Any] | None:
    for attempt in range(100):
        if not target.exists():
            return None
        try:
            marker = _read_reservation(target)
        except ProtocolError:
            if not target.exists():
                return None
            raise
        if marker is not None:
            return marker
        if attempt < 99:
            time.sleep(0.01)
    raise ProtocolError(
        "An existing final version has no reservation marker; retry publishing.",
        code="publish_in_progress",
    )


def _find_candidate_reservation(
    final_dir: Path,
    artifact_id: str,
    candidate_sha256: str,
) -> tuple[Path, int] | None:
    targets: list[tuple[int, Path]] = []
    for target in final_dir.iterdir():
        if target.is_symlink():
            raise ProtocolError(
                "Managed final directory contains a symbolic link.", code="unsafe_path"
            )
        match = _VERSION_DIRECTORY.fullmatch(target.name)
        if target.is_dir() and match is not None:
            targets.append((int(match.group(1)), target))

    matches: list[tuple[Path, int]] = []
    for version, target in sorted(targets):
        marker = _wait_for_reservation_marker(target)
        if marker is None:
            continue
        if marker.get("artifact_id") == artifact_id:
            if marker.get("candidate_sha256") != candidate_sha256:
                raise ProtocolError("Existing reservation belongs to changed candidate data.")
            matches.append((target, version))
    if not matches:
        return None

    for duplicate, _ in matches[1:]:
        marker_path = duplicate / ".reservation.json"
        try:
            children = list(duplicate.iterdir())
        except FileNotFoundError:
            continue
        if children not in ([], [marker_path]):
            raise ProtocolError(
                "Candidate has multiple non-empty final reservations.",
                code="publish_conflict",
            )
        try:
            marker_path.unlink(missing_ok=True)
            duplicate.rmdir()
        except FileNotFoundError as error:
            if duplicate.exists():
                raise ProtocolError(
                    "Could not reconcile a duplicate publish reservation.",
                    code="publish_conflict",
                ) from error
        except OSError as error:
            raise ProtocolError(
                "Could not reconcile a duplicate publish reservation.",
                code="publish_conflict",
            ) from error
    return matches[0]


def _reserve_version(
    final_dir: Path,
    artifact_id: str,
    candidate_sha256: str,
) -> tuple[Path, int]:
    while True:
        matching = _find_candidate_reservation(final_dir, artifact_id, candidate_sha256)
        if matching is not None:
            return matching
        versions = [
            int(match.group(1))
            for entry in final_dir.iterdir()
            if (match := _VERSION_DIRECTORY.fullmatch(entry.name)) is not None
        ]
        version = max(versions, default=0) + 1
        target = final_dir / f"v{version}"
        try:
            target.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            matching = _find_candidate_reservation(
                final_dir, artifact_id, candidate_sha256
            )
            if matching is not None:
                return matching
            continue
        except OSError as error:
            raise ProtocolError("Could not reserve a final version directory.") from error
        write_atomic_exclusive(
            target / ".reservation.json",
            canonical_json_bytes(
                {
                    "schema_version": 1,
                    "artifact_id": artifact_id,
                    "candidate_sha256": candidate_sha256,
                    "version": version,
                }
            )
            + b"\n",
        )
        matching = _find_candidate_reservation(final_dir, artifact_id, candidate_sha256)
        if matching is None:
            raise ProtocolError(
                "Publish reservation could not be verified.",
                code="publish_in_progress",
            )
        return matching


def _manifest_matches(
    target: Path,
    version: int,
    candidate: CandidateRecord,
    expected_files: list[CandidateFile],
) -> bool:
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return False
    manifest = read_model(manifest_path, Manifest)
    if (
        manifest.version != version
        or manifest.artifact_id != candidate.artifact_id
        or manifest.snapshot_sha256 != candidate.snapshot_sha256
        or manifest.ledger_sha256 != candidate.ledger_sha256
        or manifest.payload_sha256 != candidate.payload_sha256
        or manifest.review_mode != candidate.review_mode
        or manifest.review_status != candidate.review_status
        or manifest.render_path != candidate.render_path
        or sorted((item.path, item.role, item.sha256) for item in manifest.files)
        != sorted((item.path, item.role, item.sha256) for item in expected_files)
    ):
        return False
    return all(
        (target / item.path).is_file()
        and not (target / item.path).is_symlink()
        and file_sha256(target / item.path) == item.sha256
        for item in expected_files
    )


def _publish_result(
    target: Path,
    version: int,
    manifest_path: Path,
    files: list[CandidateFile],
    confirmation_summary: dict[str, Any],
) -> tuple[CliResult, int]:
    artifacts = [
        ArtifactInfo(path=str(target / item.path), role=item.role, sha256=item.sha256)
        for item in files
    ]
    artifacts.append(
        ArtifactInfo(
            path=str(manifest_path),
            role="manifest",
            sha256=file_sha256(manifest_path),
        )
    )
    return (
        CliResult(
            command="publish",
            status="ok",
            artifacts=artifacts,
            data={
                "version": version,
                "final_dir": str(target),
                "manifest_path": str(manifest_path),
                "confirmation_summary": confirmation_summary,
            },
        ),
        0,
    )


def publish_candidate(
    candidate_path: str | Path,
    approval_path: str | Path,
) -> tuple[CliResult, int]:
    candidate_dir = _managed_candidate_path(candidate_path)
    candidate = read_model(candidate_dir / "candidate.json", CandidateRecord)
    approval = read_model(approval_path, Approval)
    if not candidate_dir.parent.parent.parent.is_dir():
        raise ProtocolError("Managed job directory is missing.")

    gate_result = _candidate_gate(candidate_dir, candidate, approval)
    if isinstance(gate_result[0], CliResult):
        return gate_result  # type: ignore[return-value]
    files, metadata = gate_result
    approval_bytes = files.pop("approval.json")[1]
    files["approval.json"] = ("approval", approval_bytes)
    expected_files = _final_file_records(files)
    candidate_sha = file_sha256(candidate_dir / "candidate.json")
    job_dir = candidate_dir.parents[2]
    final_dir = ensure_private_directory(job_dir / "final")
    target, version = _reserve_version(final_dir, candidate.artifact_id, candidate_sha)

    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        if _manifest_matches(target, version, candidate, expected_files):
            return _publish_result(
                target,
                version,
                manifest_path,
                expected_files,
                metadata["confirmation_summary"],
            )
        raise ProtocolError("Existing published version does not match this candidate.")

    for filename, (_role, content) in files.items():
        destination = target / filename
        expected_hash = hashlib.sha256(content).hexdigest()
        if destination.exists():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or file_sha256(destination) != expected_hash
            ):
                raise ProtocolError(
                    "Reserved version contains conflicting files.",
                    code="publish_conflict",
                )
        else:
            write_atomic_replace(destination, content)

    for item in expected_files:
        destination = target / item.path
        if (
            destination.is_symlink()
            or not destination.is_file()
            or file_sha256(destination) != item.sha256
        ):
            raise ProtocolError(
                "Finalized publish files do not match their expected hashes.",
                code="publish_conflict",
            )

    manifest = Manifest(
        version=version,
        artifact_id=candidate.artifact_id,
        files=expected_files,
        snapshot_sha256=candidate.snapshot_sha256,
        ledger_sha256=candidate.ledger_sha256,
        payload_sha256=candidate.payload_sha256,
        job_requirements_sha256=candidate.job_requirements_sha256,
        review_mode=candidate.review_mode,
        review_status=candidate.review_status,
        semantic_review_waived=metadata["semantic_review_waived"],
        render_path=candidate.render_path,
        prompt_sha256=metadata["prompt_sha256"],
        renderer_version=RENDERER_VERSION,
        created_at=datetime.now(UTC),
    )
    try:
        write_atomic_exclusive(manifest_path, canonical_json_bytes(manifest) + b"\n")
    except ProtocolError as error:
        if error.code != "output_conflict" or not _manifest_matches(
            target, version, candidate, expected_files
        ):
            raise
    return _publish_result(
        target,
        version,
        manifest_path,
        expected_files,
        metadata["confirmation_summary"],
    )