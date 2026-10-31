from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypeAlias

from resume_tailor.contracts import (
    AuditReport,
    CheckResult,
    EvidenceBullet,
    FactBaseSnapshot,
    FactReference,
    JobRequirements,
    SemanticReview,
    TailoredResumePayload,
    VerifiedMetric,
    VerifiedSkill,
    content_sha256,
    sha256_json,
)
from resume_tailor.storage import read_model

SnapshotFact: TypeAlias = object

TECHNICAL_TERMS = (
    "AWS",
    "Azure",
    "C#",
    "C++",
    "Docker",
    "EC2",
    "GCP",
    "Go",
    "GPT-4",
    "Java",
    "JavaScript",
    "Kafka",
    "K8s",
    "Kubernetes",
    "PostgreSQL",
    "Python",
    "React",
    "Redis",
    "Rust",
    "S3",
    "SQL",
    "Terraform",
    "TypeScript",
)

_NUMBER_PATTERN = re.compile(
    r"(?<![\w])(?P<currency>[$€£¥])?\s*"
    r"(?P<value>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<scale>thousand|million|billion|[kmb]|万|亿)?\s*"
    r"(?P<unit>%|percent(?:age)?|times?|x|years?|months?|days?|hours?|minutes?|"
    r"seconds?|users?|requests?|customers?|employees?|people|jobs?|items?)?"
    r"(?!\w)",
    re.IGNORECASE,
)
_ENTITY_PATTERN = re.compile(
    r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,})){1,3}\b"
)
_ENTITY_LEADS = {
    "a",
    "an",
    "as",
    "built",
    "created",
    "delivered",
    "designed",
    "developed",
    "enhanced",
    "established",
    "improved",
    "implemented",
    "increased",
    "led",
    "managed",
    "optimized",
    "reduced",
    "the",
}
_APPROX_WORDS = re.compile(
    r"\b(about|approximately|around|roughly|approx\.?|~)\b|约|大约|左右",
    re.I,
)
_AT_LEAST_WORDS = re.compile(r"\b(at least|more than|over|or more)\b|>=|\+|至少|以上", re.I)
_AT_MOST_WORDS = re.compile(r"\b(at most|no more than|up to|under|less than)\b|<=|至多|以内", re.I)
_VERSIONED_TECH_TERMS = {"java", "javascript", "python", "react", "sql", "typescript"}


def _append_check(
    checks: list[CheckResult],
    name: str,
    passed: bool,
    message: str,
    *,
    issue_code: str | None = None,
    target_id: str | None = None,
) -> None:
    checks.append(
        CheckResult(
            check=name,
            passed=passed,
            issue_code=None if passed else issue_code or name,
            target_id=target_id,
            message=message,
        )
    )


def _fact_is_confirmed(item: object) -> bool:
    return bool(getattr(item, "user_confirmed", False)) and getattr(
        item, "content_sha256", None
    ) == content_sha256(item)  # type: ignore[arg-type]


def _clean_text(item: object) -> list[str]:
    values: list[str] = []
    for field in (
        "raw_source_text",
        "verified_statement",
        "skill_name",
        "company_name",
        "role_title",
        "location",
        "institution",
        "degree",
        "field_of_study",
        "project_name",
        "start_date",
        "end_date",
        "start_year",
        "end_year",
    ):
        value = getattr(item, field, None)
        if isinstance(value, str) and value:
            values.append(value)
    values.extend(value for value in getattr(item, "aliases", []) if isinstance(value, str))
    values.extend(value for value in getattr(item, "tech_tags", []) if isinstance(value, str))
    for metric in getattr(item, "verified_metrics", []):
        values.extend(
            value
            for value in (
                metric.raw_statement,
                metric.metric_value,
                metric.value_high,
                metric.baseline_value,
                metric.unit,
                metric.subject,
            )
            if value
        )
    return values


def _metrics(item: object) -> dict[str, VerifiedMetric]:
    return {metric.metric_id: metric for metric in getattr(item, "verified_metrics", [])}


def _number_signature(match: re.Match[str]) -> tuple[str, str, str]:
    try:
        value = Decimal(match.group("value").replace(",", ""))
    except InvalidOperation:
        return match.group("value"), match.group("currency") or "", match.group("unit") or ""
    scale = (match.group("scale") or "").casefold()
    multipliers = {
        "k": Decimal(1000),
        "thousand": Decimal(1000),
        "m": Decimal(1_000_000),
        "million": Decimal(1_000_000),
        "b": Decimal(1_000_000_000),
        "billion": Decimal(1_000_000_000),
        "万": Decimal(10_000),
        "亿": Decimal(100_000_000),
    }
    value *= multipliers.get(scale, Decimal(1))
    unit = (match.group("unit") or "").casefold()
    if unit == "percentage":
        unit = "%"
    elif unit in {"time", "times", "x"}:
        unit = "x"
    elif unit.endswith("s"):
        unit = unit[:-1]
    return format(value.normalize(), "f"), (match.group("currency") or ""), unit


def _mask_technology(text: str, terms: set[str]) -> str:
    result = text
    for term in sorted(terms, key=len, reverse=True):
        version = r"(?:\s+v?\d+(?:\.\d+)*)?" if term.casefold() in _VERSIONED_TECH_TERMS else ""
        pattern = re.compile(rf"(?<!\w){re.escape(term)}{version}(?!\w)", re.IGNORECASE)
        result = pattern.sub(" ", result)
    return result


def _numeric_signatures(texts: list[str], technology_terms: set[str]) -> set[tuple[str, str, str]]:
    return {
        _number_signature(match)
        for text in texts
        for match in _NUMBER_PATTERN.finditer(_mask_technology(text, technology_terms))
    }


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term.strip())
    if not escaped:
        return False
    left = r"(?<!\w)" if term[0].isalnum() else ""
    right = r"(?!\w)" if term[-1].isalnum() else ""
    flags = 0 if term.casefold() == "go" else re.IGNORECASE
    return re.search(f"{left}{escaped}{right}", text, flags) is not None


def _unsupported_terms(text: str, terms: set[str], support_text: list[str]) -> list[str]:
    supported = "\n".join(support_text)
    return sorted(
        term
        for term in terms
        if _contains_term(text, term) and not _contains_term(supported, term)
    )


def _entity_phrases(text: str) -> set[str]:
    phrases: set[str] = set()
    for match in _ENTITY_PATTERN.finditer(text):
        phrase = match.group(0)
        if phrase.split()[0].casefold() in _ENTITY_LEADS:
            continue
        phrases.add(phrase.casefold())
    return phrases


def _qualifier_is_preserved(metric: VerifiedMetric, text: str) -> bool:
    if metric.qualifier == "exact":
        return True
    if metric.qualifier == "approx":
        return bool(_APPROX_WORDS.search(text))
    if metric.qualifier == "at_least":
        return bool(_AT_LEAST_WORDS.search(text))
    if metric.qualifier == "at_most":
        return bool(_AT_MOST_WORDS.search(text))
    if metric.qualifier == "range":
        return bool(metric.value_high and metric.value_high in text)
    return False


def _verified_metrics_for(items: list[object]) -> dict[str, VerifiedMetric]:
    metrics: dict[str, VerifiedMetric] = {}
    for item in items:
        metrics.update(_metrics(item))
    return metrics


def _supported_text(items: list[object]) -> list[str]:
    return [text for item in items for text in _clean_text(item)]


def _make_snapshot_indexes(snapshot: FactBaseSnapshot) -> tuple[
    dict[str, EvidenceBullet],
    dict[str, str],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, VerifiedSkill],
]:
    bullets: dict[str, EvidenceBullet] = {}
    bullet_parents: dict[str, str] = {}
    experiences = {item.exp_id: item for item in snapshot.fact_base.work_experiences}
    projects = {item.project_id: item for item in snapshot.fact_base.projects}
    education = {item.edu_id: item for item in snapshot.fact_base.education}
    skills = {item.skill_id: item for item in snapshot.fact_base.verified_skills}
    for experience in snapshot.fact_base.work_experiences:
        for bullet in experience.bullets:
            bullets[bullet.fact_id] = bullet
            bullet_parents[bullet.fact_id] = experience.exp_id
    for project in snapshot.fact_base.projects:
        for bullet in project.bullets:
            bullets[bullet.fact_id] = bullet
            bullet_parents[bullet.fact_id] = project.project_id
    return bullets, bullet_parents, experiences, projects, education, skills


def _resolve_skill_sources(
    skill_ids: list[str],
    skills: dict[str, VerifiedSkill],
    selected_skill_ids: set[str],
) -> tuple[list[VerifiedSkill], bool]:
    resolved = [
        skills[skill_id]
        for skill_id in skill_ids
        if skill_id in skills and skill_id in selected_skill_ids
    ]
    valid = (
        len(resolved) == len(skill_ids)
        and len(skill_ids) == len(set(skill_ids))
        and all(_fact_is_confirmed(skill) for skill in resolved)
    )
    return resolved, valid


def _resolve_reference(
    reference: FactReference,
    indexes: tuple[
        dict[str, EvidenceBullet],
        dict[str, str],
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, VerifiedSkill],
    ],
) -> object | None:
    bullets, _, experiences, projects, education, skills = indexes
    lookup = {
        "bullet": bullets,
        "skill": skills,
        "experience": experiences,
        "project": projects,
        "education": education,
    }
    return lookup[reference.source_type].get(reference.source_id)


def _confirmed_snapshot_checks(snapshot: FactBaseSnapshot) -> list[tuple[str, bool]]:
    items: list[object] = [snapshot.fact_base.identity]
    items.extend(snapshot.fact_base.education)
    items.extend(snapshot.fact_base.work_experiences)
    items.extend(snapshot.fact_base.projects)
    items.extend(snapshot.fact_base.verified_skills)
    for experience in snapshot.fact_base.work_experiences:
        items.extend(experience.bullets)
    for project in snapshot.fact_base.projects:
        items.extend(project.bullets)
    checks = []
    for item in items:
        item_id = getattr(item, "fact_id", getattr(item, "exp_id", "snapshot_fact"))
        checks.append((str(item_id), _fact_is_confirmed(item)))
    return checks


def _validate_segment(
    text: str,
    source_items: list[object],
    metric_ids: list[str],
    *,
    target_id: str,
    term_set: set[str],
    entity_allowlist: set[str],
    checks: list[CheckResult],
) -> None:
    support_text = _supported_text(source_items)
    metric_index = _verified_metrics_for(source_items)
    invalid_metric_ids = sorted(set(metric_ids) - set(metric_index))
    _append_check(
        checks,
        "metric_source_binding",
        not invalid_metric_ids,
        "Declared metrics must belong to cited confirmed facts.",
        issue_code="unsupported_metric_id",
        target_id=target_id if invalid_metric_ids else None,
    )

    supported_terms = set(term_set)
    selected_skill_terms: set[str] = set()
    for item in source_items:
        if isinstance(item, VerifiedSkill):
            selected_skill_terms.update([item.skill_name, *item.aliases])
    all_support = support_text + list(selected_skill_terms)
    missing_terms = _unsupported_terms(text, supported_terms, all_support)
    _append_check(
        checks,
        "supported_terms",
        not missing_terms,
        "Every recognized job or technical term must be supported by confirmed evidence.",
        issue_code="unsupported_term",
        target_id=target_id if missing_terms else None,
    )

    evidence_entities = set().union(*(_entity_phrases(value) for value in support_text))
    missing_entities = sorted(
        phrase
        for phrase in _entity_phrases(text)
        if phrase not in evidence_entities and phrase not in entity_allowlist
    )
    _append_check(
        checks,
        "entity_grounding",
        not missing_entities,
        "Recognized named entities must appear in cited facts or confirmed job metadata.",
        issue_code="unsupported_entity",
        target_id=target_id if missing_entities else None,
    )

    technology_terms = set(TECHNICAL_TERMS)
    technology_terms.update(
        value
        for item in source_items
        for value in (
            getattr(item, "tech_tags", [])
            + getattr(item, "aliases", [])
            + ([item.skill_name] if getattr(item, "skill_name", None) else [])
        )
    )
    source_numbers = _numeric_signatures(support_text, technology_terms)
    output_numbers = _numeric_signatures([text], technology_terms)
    unsupported_numbers = sorted(output_numbers - source_numbers)
    _append_check(
        checks,
        "numeric_grounding",
        not unsupported_numbers,
        "Numbers in rewritten text must be present in cited evidence or verified metrics.",
        issue_code="unsupported_number",
        target_id=target_id if unsupported_numbers else None,
    )

    output_numbers_for_qualifiers = _numeric_signatures([text], technology_terms)
    inferred_metric_ids = {
        metric_id
        for metric_id, metric in metric_index.items()
        if output_numbers_for_qualifiers
        & _numeric_signatures(
            [
                metric.raw_statement,
                metric.metric_value,
                f"{metric.metric_value} {metric.unit}",
                metric.value_high or "",
                f"{metric.value_high} {metric.unit}" if metric.value_high else "",
            ],
            technology_terms,
        )
    }
    qualifier_failures = [
        metric_id
        for metric_id in set(metric_ids) | inferred_metric_ids
        if metric_id in metric_index and not _qualifier_is_preserved(metric_index[metric_id], text)
    ]
    _append_check(
        checks,
        "metric_qualifier",
        not qualifier_failures,
        "Metric qualifiers must not be strengthened or omitted.",
        issue_code="metric_qualifier_changed",
        target_id=target_id if qualifier_failures else None,
    )


def check_resume_facts(
    snapshot_path: str | Path,
    payload_path: str | Path,
    *,
    requirements_path: str | Path | None = None,
    review_path: str | Path | None = None,
) -> AuditReport:
    snapshot = read_model(snapshot_path, FactBaseSnapshot)
    payload = read_model(payload_path, TailoredResumePayload)
    requirements = (
        read_model(requirements_path, JobRequirements) if requirements_path is not None else None
    )
    review = read_model(review_path, SemanticReview) if review_path is not None else None
    checks: list[CheckResult] = []

    snapshot_hash_valid = sha256_json(snapshot.fact_base) == snapshot.snapshot_sha256
    _append_check(
        checks,
        "snapshot_hash",
        snapshot_hash_valid,
        "Snapshot hash must match its immutable fact base.",
        issue_code="snapshot_hash_mismatch",
    )
    payload_binding_valid = payload.snapshot_sha256 == snapshot.snapshot_sha256
    _append_check(
        checks,
        "payload_snapshot_binding",
        payload_binding_valid,
        "Payload must be bound to the supplied snapshot hash.",
        issue_code="snapshot_binding_mismatch",
    )

    confirmation_results = _confirmed_snapshot_checks(snapshot)
    unconfirmed_count = sum(not confirmed for _, confirmed in confirmation_results)
    _append_check(
        checks,
        "confirmed_snapshot_facts",
        unconfirmed_count == 0,
        "Only facts with matching confirmation hashes may be used.",
        issue_code="unconfirmed_fact",
    )

    indexes = _make_snapshot_indexes(snapshot)
    bullets, bullet_parents, experiences, projects, education, skills = indexes
    duplicate_skill_ids = len(payload.selected_skill_ids) != len(set(payload.selected_skill_ids))
    unknown_skills = sorted(set(payload.selected_skill_ids) - set(skills))
    selected_skill_ids = set(payload.selected_skill_ids)
    _append_check(
        checks,
        "selected_skill_ids",
        not duplicate_skill_ids and not unknown_skills,
        "Selected skill IDs must be unique members of the confirmed snapshot.",
        issue_code="unsupported_skill_id",
    )

    selected_education = set(payload.selected_education_ids)
    _append_check(
        checks,
        "selected_education_ids",
        len(selected_education) == len(payload.selected_education_ids)
        and selected_education <= set(education),
        "Selected education IDs must be unique members of the confirmed snapshot.",
        issue_code="unsupported_education_id",
    )

    if payload.pending_confirmations:
        _append_check(
            checks,
            "pending_confirmations",
            False,
            "Unresolved confirmation placeholders block approval.",
            issue_code="pending_confirmation",
        )
    for section in [
        *(bullet for experience in payload.experiences for bullet in experience.selected_bullets),
        *(bullet for project in payload.projects for bullet in project.selected_bullets),
    ]:
        if section.open_placeholder_ids:
            _append_check(
                checks,
                "open_placeholders",
                False,
                "A rewritten item with an open placeholder cannot pass validation.",
                issue_code="open_placeholder",
                target_id=section.bullet_id,
            )

    jd_terms = {item.term for item in requirements.keywords} if requirements else set()
    term_set = set(TECHNICAL_TERMS) | jd_terms
    entity_allowlist: set[str] = set()
    expected_requirements_hash: str | None = None
    if requirements is not None:
        entity_allowlist.update(
            value.casefold()
            for value in (requirements.company_name, requirements.role_title)
            if value
        )
        expected_requirements_hash = sha256_json(requirements)
        requirements_hash_valid = payload.job_requirements_sha256 == expected_requirements_hash
        _append_check(
            checks,
            "job_requirements_binding",
            requirements_hash_valid,
            "Payload must be bound to the supplied job-requirements hash.",
            issue_code="requirements_binding_mismatch",
        )

    seen_experience_ids: set[str] = set()
    seen_project_ids: set[str] = set()
    seen_bullet_ids: set[str] = set()
    for section in payload.experiences:
        experience = experiences.get(section.exp_id)
        unique_id = section.exp_id not in seen_experience_ids
        seen_experience_ids.add(section.exp_id)
        _append_check(
            checks,
            "experience_source_binding",
            experience is not None and unique_id,
            "Each selected experience must resolve once in the confirmed snapshot.",
            issue_code="unsupported_experience_id",
            target_id=section.exp_id if experience is None or not unique_id else None,
        )
        for rewritten in section.selected_bullets:
            unique_bullet = rewritten.bullet_id not in seen_bullet_ids
            seen_bullet_ids.add(rewritten.bullet_id)
            source_items = [
                bullets[item_id]
                for item_id in rewritten.source_fact_ids
                if item_id in bullets and bullet_parents.get(item_id) == section.exp_id
            ]
            references_valid = (
                unique_bullet
                and len(source_items) == len(rewritten.source_fact_ids)
                and bool(rewritten.source_fact_ids)
                and all(_fact_is_confirmed(item) for item in source_items)
            )
            skill_items, skill_references_valid = _resolve_skill_sources(
                rewritten.source_skill_ids,
                skills,
                selected_skill_ids,
            )
            _append_check(
                checks,
                "bullet_source_binding",
                references_valid,
                "Each rewritten bullet must cite confirmed evidence from its own section.",
                issue_code="invalid_bullet_source",
                target_id=rewritten.bullet_id if not references_valid else None,
            )
            _append_check(
                checks,
                "bullet_skill_source_binding",
                skill_references_valid,
                "Supporting skill IDs must reference selected, confirmed skills.",
                issue_code="invalid_bullet_skill_source",
                target_id=rewritten.bullet_id if not skill_references_valid else None,
            )
            _validate_segment(
                rewritten.rewritten_text,
                [*source_items, *skill_items],
                rewritten.used_metric_ids,
                target_id=rewritten.bullet_id,
                term_set=term_set,
                entity_allowlist=entity_allowlist,
                checks=checks,
            )

    for section in payload.projects:
        project = projects.get(section.project_id)
        unique_id = section.project_id not in seen_project_ids
        seen_project_ids.add(section.project_id)
        _append_check(
            checks,
            "project_source_binding",
            project is not None and unique_id,
            "Each selected project must resolve once in the confirmed snapshot.",
            issue_code="unsupported_project_id",
            target_id=section.project_id if project is None or not unique_id else None,
        )
        for rewritten in section.selected_bullets:
            unique_bullet = rewritten.bullet_id not in seen_bullet_ids
            seen_bullet_ids.add(rewritten.bullet_id)
            source_items = [
                bullets[item_id]
                for item_id in rewritten.source_fact_ids
                if item_id in bullets and bullet_parents.get(item_id) == section.project_id
            ]
            references_valid = (
                unique_bullet
                and len(source_items) == len(rewritten.source_fact_ids)
                and bool(rewritten.source_fact_ids)
                and all(_fact_is_confirmed(item) for item in source_items)
            )
            skill_items, skill_references_valid = _resolve_skill_sources(
                rewritten.source_skill_ids,
                skills,
                selected_skill_ids,
            )
            _append_check(
                checks,
                "bullet_source_binding",
                references_valid,
                "Each rewritten bullet must cite confirmed evidence from its own section.",
                issue_code="invalid_bullet_source",
                target_id=rewritten.bullet_id if not references_valid else None,
            )
            _append_check(
                checks,
                "bullet_skill_source_binding",
                skill_references_valid,
                "Supporting skill IDs must reference selected, confirmed skills.",
                issue_code="invalid_bullet_skill_source",
                target_id=rewritten.bullet_id if not skill_references_valid else None,
            )
            _validate_segment(
                rewritten.rewritten_text,
                [*source_items, *skill_items],
                rewritten.used_metric_ids,
                target_id=rewritten.bullet_id,
                term_set=term_set,
                entity_allowlist=entity_allowlist,
                checks=checks,
            )

    summary_items: list[object] = []
    invalid_summary_refs: list[str] = []
    for reference in payload.summary_sources:
        item = _resolve_reference(reference, indexes)
        if item is None or not _fact_is_confirmed(item):
            invalid_summary_refs.append(reference.source_id)
        else:
            summary_items.append(item)
    if payload.summary_statement and not payload.summary_sources:
        invalid_summary_refs.append("missing_summary_source")
    _append_check(
        checks,
        "summary_source_binding",
        not invalid_summary_refs,
        "A summary must cite confirmed snapshot facts.",
        issue_code="invalid_summary_source",
    )
    if payload.summary_statement:
        _validate_segment(
            payload.summary_statement,
            summary_items,
            payload.summary_metric_ids,
            target_id="summary",
            term_set=term_set,
            entity_allowlist=entity_allowlist,
            checks=checks,
        )

    selected_skill_items = [
        skills[value] for value in payload.selected_skill_ids if value in skills
    ]
    for skill in selected_skill_items:
        if not _fact_is_confirmed(skill):
            _append_check(
                checks,
                "selected_skill_confirmation",
                False,
                "Selected skills must have matching confirmation hashes.",
                issue_code="unconfirmed_skill",
                target_id=skill.skill_id,
            )

    if requirements is None:
        skipped = [
            {
                "check": "job_requirement_terms",
                "reason": "No JobRequirements file was supplied.",
            }
        ]
    else:
        skipped = []

    review_mode = "NONE"
    review_status = "NOT_RUN"
    review_is_current = False
    if review is not None:
        review_mode = review.mode
        review_is_current = review.payload_sha256 == sha256_json(payload)
        if review_is_current:
            review_status = review.status
        else:
            skipped.append(
                {
                    "check": "semantic_review",
                    "reason": "The review hash does not match this payload; review is NOT_RUN.",
                }
            )
    else:
        skipped.append(
            {"check": "semantic_review", "reason": "No semantic review file was supplied."}
        )

    deterministic_passed = all(check.passed for check in checks)
    review_passed = review_is_current and review_mode != "NONE" and review_status == "PASSED"
    approval_conditions = {
        "deterministic_checks_passed": deterministic_passed,
        "semantic_review_mode": review_mode,
        "semantic_review_status": review_status,
        "semantic_review_current": review_is_current,
        "semantic_review_waived": False,
        "requires_explicit_user_waiver": review_status in {"NOT_RUN", "UNAVAILABLE"},
        "can_approve": deterministic_passed
        and (review_passed or review_status in {"NOT_RUN", "UNAVAILABLE"}),
        "can_publish": deterministic_passed and review_passed,
        "confirmed_fact_count": sum(confirmed for _, confirmed in confirmation_results),
        "snapshot_sha256": snapshot.snapshot_sha256,
        "ledger_sha256": snapshot.ledger_sha256,
    }
    return AuditReport(
        payload_sha256=sha256_json(payload),
        snapshot_sha256=snapshot.snapshot_sha256,
        expected_job_requirements_sha256=expected_requirements_hash,
        checks=checks,
        skipped_checks=skipped,
        approval_conditions=approval_conditions,
    )