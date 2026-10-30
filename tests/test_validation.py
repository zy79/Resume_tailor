from pathlib import Path

from resume_tailor.contracts import (
    EvidenceBullet,
    FactBaseSnapshot,
    FactReference,
    Identity,
    JobKeyword,
    JobRequirements,
    RewrittenBullet,
    TailoredExperienceSection,
    TailoredResumePayload,
    UserFactBase,
    VerifiedMetric,
    WorkExperienceFact,
    content_sha256,
    sha256_json,
)
from resume_tailor.validation import check_resume_facts


def _write_json(path: Path, model: object) -> None:
    path.write_text(model.model_dump_json(), encoding="utf-8")


def _snapshot(
    path: Path,
    statement: str = "Built a reliable service.",
    metrics: list[VerifiedMetric] | None = None,
) -> FactBaseSnapshot:
    bullet = EvidenceBullet(
        fact_id="fact_service",
        raw_source_text=statement,
        source_kind="resume_extract",
        source_block_ids=["blk_source"],
        verified_statement=statement,
        verified_metrics=metrics or [],
        user_confirmed=True,
    )
    bullet = bullet.model_copy(update={"content_sha256": content_sha256(bullet)})
    experience = WorkExperienceFact(
        exp_id="exp_service",
        company_name="Synthetic Systems",
        role_title="Engineer",
        start_date="2020",
        end_date="2022",
        bullets=[bullet],
        user_confirmed=True,
    )
    experience = experience.model_copy(
        update={"content_sha256": content_sha256(experience)}
    )
    identity = Identity(user_confirmed=True)
    identity = identity.model_copy(update={"content_sha256": content_sha256(identity)})
    fact_base = UserFactBase(identity=identity, work_experiences=[experience])
    snapshot = FactBaseSnapshot(
        snapshot_id="snap_synthetic",
        snapshot_sha256=sha256_json(fact_base),
        ledger_sha256="0" * 64,
        created_at="2026-01-01T00:00:00Z",
        fact_base=fact_base,
    )
    _write_json(path, snapshot)
    return snapshot


def _payload(path: Path, snapshot: FactBaseSnapshot, rewritten: str) -> TailoredResumePayload:
    payload = TailoredResumePayload(
        snapshot_sha256=snapshot.snapshot_sha256,
        selected_skill_ids=[],
        experiences=[
            TailoredExperienceSection(
                exp_id="exp_service",
                selected_bullets=[
                    RewrittenBullet(
                        bullet_id="bullet_service",
                        rewritten_text=rewritten,
                        source_fact_ids=["fact_service"],
                        applied_style="balanced",
                    )
                ],
            )
        ],
    )
    _write_json(path, payload)
    return payload


def test_supported_payload_passes_deterministic_checks(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    _payload(tmp_path / "payload.json", snapshot, "Built a reliable service.")

    report = check_resume_facts(tmp_path / "snapshot.json", tmp_path / "payload.json")

    assert all(check.passed for check in report.checks)
    assert report.approval_conditions["deterministic_checks_passed"] is True


def test_payload_must_bind_to_snapshot(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    payload = _payload(tmp_path / "payload.json", snapshot, "Built a reliable service.")
    payload.snapshot_sha256 = "f" * 64
    _write_json(tmp_path / "payload.json", payload)

    report = check_resume_facts(tmp_path / "snapshot.json", tmp_path / "payload.json")

    assert any(
        check.issue_code == "snapshot_binding_mismatch" and not check.passed
        for check in report.checks
    )


def test_unsupported_jd_term_is_blocked(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    payload = _payload(tmp_path / "payload.json", snapshot, "Built Kubernetes services.")
    requirements = JobRequirements(
        jd_text_sha256="0" * 64,
        company_name="Synthetic Systems",
        role_title="Engineer",
        keywords=[JobKeyword(term="Kubernetes", category="skill", must_have=True)],
    )
    payload.job_requirements_sha256 = sha256_json(requirements)
    _write_json(tmp_path / "payload.json", payload)
    _write_json(tmp_path / "requirements.json", requirements)

    report = check_resume_facts(
        tmp_path / "snapshot.json",
        tmp_path / "payload.json",
        requirements_path=tmp_path / "requirements.json",
    )

    assert any(
        check.issue_code == "unsupported_term" and not check.passed
        for check in report.checks
    )


def test_uncovered_must_have_does_not_block_candidate(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    payload = _payload(tmp_path / "payload.json", snapshot, "Built a reliable service.")
    requirements = JobRequirements(
        jd_text_sha256="0" * 64,
        company_name="Synthetic Systems",
        role_title="Engineer",
        keywords=[JobKeyword(term="Kubernetes", category="skill", must_have=True)],
    )
    payload.job_requirements_sha256 = sha256_json(requirements)
    _write_json(tmp_path / "payload.json", payload)
    _write_json(tmp_path / "requirements.json", requirements)

    report = check_resume_facts(
        tmp_path / "snapshot.json",
        tmp_path / "payload.json",
        requirements_path=tmp_path / "requirements.json",
    )

    assert all(check.passed for check in report.checks)
    assert report.approval_conditions["deterministic_checks_passed"] is True


def test_unsupported_derived_number_is_blocked(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    _payload(tmp_path / "payload.json", snapshot, "Reduced latency by 50%.")

    report = check_resume_facts(tmp_path / "snapshot.json", tmp_path / "payload.json")

    assert any(
        check.issue_code == "unsupported_number" and not check.passed
        for check in report.checks
    )


def test_technical_version_number_is_not_mistaken_for_a_metric(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json", "Used Python in a service.")
    _payload(tmp_path / "payload.json", snapshot, "Used Python 3 in a service.")

    report = check_resume_facts(tmp_path / "snapshot.json", tmp_path / "payload.json")

    assert not any(
        check.issue_code == "unsupported_number" and not check.passed
        for check in report.checks
    )


def test_approximate_metric_qualifier_is_checked_without_metric_id(tmp_path: Path) -> None:
    metric = VerifiedMetric(
        metric_id="metric_latency",
        raw_statement="Approximately 20% lower latency.",
        metric_value="20",
        unit="%",
        qualifier="approx",
        subject="latency",
        change_direction="decrease",
        metric_type="percentage",
    )
    snapshot = _snapshot(
        tmp_path / "snapshot.json",
        statement="Approximately 20% lower latency.",
        metrics=[metric],
    )
    payload_path = tmp_path / "payload.json"
    _payload(payload_path, snapshot, "Reduced latency by 20%.")

    report = check_resume_facts(tmp_path / "snapshot.json", payload_path)

    assert any(
        check.issue_code == "metric_qualifier_changed" and not check.passed
        for check in report.checks
    )

    _payload(payload_path, snapshot, "Reduced latency by approximately 20%.")
    report = check_resume_facts(tmp_path / "snapshot.json", payload_path)

    assert all(
        check.passed
        for check in report.checks
        if check.check == "metric_qualifier"
    )


def test_summary_requires_confirmed_fact_references(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot.json")
    payload = TailoredResumePayload(
        snapshot_sha256=snapshot.snapshot_sha256,
        selected_skill_ids=[],
        summary_statement="Built a reliable service.",
        summary_sources=[FactReference(source_type="bullet", source_id="fact_missing")],
    )
    _write_json(tmp_path / "payload.json", payload)

    report = check_resume_facts(tmp_path / "snapshot.json", tmp_path / "payload.json")

    assert any(
        check.issue_code == "invalid_summary_source" and not check.passed
        for check in report.checks
    )