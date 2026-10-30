from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PartialDate = Annotated[str, StringConstraints(pattern=r"^\d{4}(-\d{2})?$")]
PartialEndDate = Annotated[str, StringConstraints(pattern=r"^(\d{4}(-\d{2})?|Present)$")]
YearString = Annotated[str, StringConstraints(pattern=r"^\d{4}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CliIssue(Contract):
    code: str
    severity: Literal["error", "warning", "info"]
    path: str | None = None
    message: str


class ArtifactInfo(Contract):
    path: str
    role: str
    sha256: Sha256


class SkippedCheck(Contract):
    check: str
    reason: str


class CliResult(Contract):
    schema_version: Literal[1] = 1
    command: str
    status: Literal["ok", "blocked", "degraded", "error"]
    issues: list[CliIssue] = Field(default_factory=list)
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    skipped_checks: list[SkippedCheck] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class SourcePosition(Contract):
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=0)


class SourceBlock(Contract):
    block_id: str
    text: str
    position: SourcePosition = Field(default_factory=SourcePosition)


class RedactionSummary(Contract):
    enabled: bool
    counts: dict[str, int] = Field(default_factory=dict)


class SourceText(Contract):
    schema_version: Literal[1] = 1
    source_sha256: Sha256
    format: Literal["txt", "docx", "pdf"]
    extractor: str
    extractor_version: str
    blocks: list[SourceBlock]
    warnings: list[str] = Field(default_factory=list)
    redaction: RedactionSummary


class ConfirmableFact(Contract):
    user_confirmed: bool = False
    content_sha256: Sha256 | None = None


class Identity(ConfirmableFact):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class MetricData(Contract):
    raw_statement: str
    metric_value: str
    value_high: str | None = None
    baseline_value: str | None = None
    unit: str
    qualifier: Literal["exact", "approx", "at_least", "at_most", "range"] = "exact"
    subject: str
    change_direction: Literal["increase", "decrease", "unchanged", "unknown"]
    metric_type: Literal[
        "percentage", "scale", "latency", "currency", "count", "duration", "other"
    ]


class VerifiedMetric(MetricData):
    metric_id: str


class EvidenceBullet(ConfirmableFact):
    fact_id: str = Field(pattern=r"^fact_[A-Za-z0-9_-]+$")
    raw_source_text: str
    source_kind: Literal["resume_extract", "user_confirmation"]
    source_block_ids: list[str] = Field(default_factory=list)
    verified_statement: str
    verified_metrics: list[VerifiedMetric] = Field(default_factory=list)
    tech_tags: list[str] = Field(default_factory=list)


class WorkExperienceFact(ConfirmableFact):
    exp_id: str
    company_name: str
    role_title: str
    location: str | None = None
    start_date: PartialDate
    end_date: PartialEndDate
    bullets: list[EvidenceBullet]


class ProjectFact(ConfirmableFact):
    project_id: str
    project_name: str
    role_title: str
    start_date: PartialDate | None = None
    end_date: PartialEndDate | None = None
    description: str = ""
    bullets: list[EvidenceBullet]


class EducationFact(ConfirmableFact):
    edu_id: str
    institution: str
    degree: str
    field_of_study: str
    start_year: YearString | None = None
    end_year: YearString | None = None
    end_status: Literal["completed", "expected", "in_progress"] = "completed"
    gpa_or_honors: str | None = None


class JobPreferences(Contract):
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)


class VerifiedSkill(ConfirmableFact):
    skill_id: str = Field(pattern=r"^skill_[A-Za-z0-9_-]+$")
    skill_name: str
    aliases: list[str] = Field(default_factory=list)
    source_kind: Literal["resume_extract", "user_confirmation"]
    raw_source_text: str


class UnparsedSection(Contract):
    title: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=120,
            pattern=r"^[^\r\n]+$",
        ),
    ]
    source_block_ids: list[str]


class FactCandidates(Contract):
    schema_version: Literal[1] = 1
    user_id: str = "local"
    version: int = Field(default=1, ge=1)
    education: list[EducationFact] = Field(default_factory=list)
    work_experiences: list[WorkExperienceFact] = Field(default_factory=list)
    projects: list[ProjectFact] = Field(default_factory=list)
    verified_skills: list[VerifiedSkill] = Field(default_factory=list)
    preferences: JobPreferences = Field(default_factory=JobPreferences)
    unparsed_sections: list[UnparsedSection] = Field(default_factory=list)


class ConfirmationEntry(Contract):
    object_type: Literal[
        "education", "work_experience", "evidence_bullet", "project", "verified_skill"
    ]
    object_id: str
    content_sha256: Sha256
    decision: Literal["confirmed", "rejected", "edited"]
    user_words: str = ""


class ConfirmationRecords(Contract):
    schema_version: Literal[1] = 1
    ledger_sha256: Sha256
    entries: list[ConfirmationEntry]


class UserFactBase(Contract):
    schema_version: Literal[1] = 1
    user_id: str = "local"
    version: int = Field(default=1, ge=1)
    identity: Identity = Field(default_factory=Identity)
    education: list[EducationFact] = Field(default_factory=list)
    work_experiences: list[WorkExperienceFact] = Field(default_factory=list)
    projects: list[ProjectFact] = Field(default_factory=list)
    verified_skills: list[VerifiedSkill] = Field(default_factory=list)
    preferences: JobPreferences = Field(default_factory=JobPreferences)


class FactBaseSnapshot(Contract):
    schema_version: Literal[1] = 1
    snapshot_id: str
    snapshot_sha256: Sha256
    parent_snapshot_sha256: Sha256 | None = None
    ledger_sha256: Sha256
    created_at: AwareDatetime
    fact_base: UserFactBase


class JobKeyword(Contract):
    term: str
    category: Literal["skill", "responsibility", "qualification"]
    must_have: bool = False


class JobRequirements(Contract):
    schema_version: Literal[1] = 1
    jd_text_sha256: Sha256
    company_name: str
    role_title: str
    keywords: list[JobKeyword] = Field(default_factory=list)


class FactReference(Contract):
    source_type: Literal["bullet", "skill", "education", "experience", "project"]
    source_id: str


class TailoringRunConfig(Contract):
    positioning_style: Literal["conservative", "balanced", "assertive"] = "balanced"
    output_language: str = "en"
    target_pages: int | None = Field(default=None, ge=1)
    render_format: Literal["DOCX", "MARKDOWN"] = "DOCX"
    template_id: str | None = None


class ConfirmationOption(Contract):
    option_id: str
    label: str
    effect_action: Literal[
        "provide_metric",
        "keep_qualitative",
        "revert_raw",
        "custom_edit",
        "confirm_responsibility",
        "reduce_responsibility",
        "confirm_skill",
        "select_items_to_trim",
    ]
    recommended: bool = False


class ConfirmationPlaceholder(Contract):
    placeholder_id: str
    target_kind: Literal["bullet", "summary", "skills", "layout"]
    target_bullet_ids: list[str] = Field(default_factory=list)
    uncertainty_type: Literal[
        "missing_metric", "ambiguous_responsibility", "skill_homology", "budget_overflow"
    ]
    question_for_user: str
    context_reason: str
    suggested_options: list[ConfirmationOption] = Field(default_factory=list)
    allow_free_input: bool = True


class RewrittenBullet(Contract):
    bullet_id: str
    rewritten_text: str
    source_fact_ids: list[str] = Field(min_length=1)
    matched_jd_keywords: list[str] = Field(default_factory=list)
    applied_style: Literal["conservative", "balanced", "assertive"]
    used_metric_ids: list[str] = Field(default_factory=list)
    open_placeholder_ids: list[str] = Field(default_factory=list)


class TailoredExperienceSection(Contract):
    exp_id: str
    selected_bullets: list[RewrittenBullet]


class TailoredProjectSection(Contract):
    project_id: str
    selected_bullets: list[RewrittenBullet]


class TailoredResumePayload(Contract):
    schema_version: Literal[1] = 1
    snapshot_sha256: Sha256
    job_requirements_sha256: Sha256 | None = None
    run_config: TailoringRunConfig = Field(default_factory=TailoringRunConfig)
    summary_statement: str | None = None
    summary_sources: list[FactReference] = Field(default_factory=list)
    summary_metric_ids: list[str] = Field(default_factory=list)
    selected_skill_ids: list[str]
    experiences: list[TailoredExperienceSection] = Field(default_factory=list)
    projects: list[TailoredProjectSection] = Field(default_factory=list)
    selected_education_ids: list[str] = Field(default_factory=list)
    pending_confirmations: list[ConfirmationPlaceholder] = Field(default_factory=list)


ReviewMode = Literal["SELF_REVIEW", "SUBSCRIPTION_ALT_MODEL", "API_JUDGE", "NONE"]
ReviewStatus = Literal["NOT_RUN", "PASSED", "FAILED", "UNAVAILABLE"]


class ReviewFinding(Contract):
    target_id: str
    category: str
    fact_id: str
    suggested_action: str


class SemanticReview(Contract):
    schema_version: Literal[1] = 1
    payload_sha256: Sha256
    mode: ReviewMode
    status: ReviewStatus
    judge_independence: Literal[
        "DIFFERENT_PROVIDER", "SAME_PROVIDER_DIFFERENT_MODEL", "SAME_MODEL"
    ] | None = None
    context_isolated: bool = False
    reviewer_label: str | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_status(self) -> Self:
        if self.mode == "NONE" and self.status != "NOT_RUN":
            raise ValueError("A review with mode NONE must have status NOT_RUN.")
        return self


class CheckResult(Contract):
    check: str
    passed: bool
    issue_code: str | None = None
    target_id: str | None = None
    message: str


class AuditReport(Contract):
    schema_version: Literal[1] = 1
    payload_sha256: Sha256
    snapshot_sha256: Sha256
    checks: list[CheckResult] = Field(default_factory=list)
    skipped_checks: list[SkippedCheck] = Field(default_factory=list)
    render_path: str | None = None
    approval_conditions: dict[str, Any] = Field(default_factory=dict)


class CandidateFile(Contract):
    path: str
    role: str
    sha256: Sha256


class CandidateRecord(Contract):
    schema_version: Literal[1] = 1
    job_id: str
    run_id: str
    artifact_id: str
    company_name: str | None = None
    role_title: str | None = None
    payload_sha256: Sha256
    snapshot_sha256: Sha256
    ledger_sha256: Sha256
    job_requirements_sha256: Sha256 | None = None
    files: list[CandidateFile]
    review_mode: ReviewMode
    review_status: ReviewStatus
    render_path: str
    created_at: AwareDatetime


class AcknowledgedWaiver(Contract):
    waiver: Literal["semantic_review_not_run", "semantic_review_unavailable"]
    user_words: str = Field(min_length=1)


class Approval(Contract):
    schema_version: Literal[1] = 1
    candidate_files: list[CandidateFile]
    payload_sha256: Sha256
    snapshot_sha256: Sha256
    company_name: str | None = None
    role_title: str | None = None
    review_mode: ReviewMode
    review_status: ReviewStatus
    acknowledged_waivers: list[AcknowledgedWaiver] = Field(default_factory=list)
    approved_at: AwareDatetime


class Manifest(Contract):
    schema_version: Literal[1] = 1
    version: int = Field(ge=1)
    artifact_id: str
    files: list[CandidateFile]
    snapshot_sha256: Sha256
    ledger_sha256: Sha256
    payload_sha256: Sha256
    job_requirements_sha256: Sha256 | None = None
    review_mode: ReviewMode
    review_status: ReviewStatus
    semantic_review_waived: bool = False
    render_path: str
    prompt_sha256: Sha256
    renderer_version: str
    created_at: AwareDatetime


def canonical_json_bytes(value: BaseModel | Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: BaseModel | Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def content_sha256(value: BaseModel) -> str:
    payload = value.model_dump(mode="json")
    payload = _strip_confirmation_metadata(payload)
    return sha256_json(payload)


def _strip_confirmation_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_confirmation_metadata(item)
            for key, item in value.items()
            if key not in {"content_sha256", "user_confirmed"}
        }
    if isinstance(value, list):
        return [_strip_confirmation_metadata(item) for item in value]
    return value