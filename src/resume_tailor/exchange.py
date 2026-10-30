from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel
from pypdf import PdfReader

from resume_tailor.contracts import (
    ConfirmationEntry,
    ConfirmationRecords,
    Contract,
    EvidenceBullet,
    FactBaseSnapshot,
    FactCandidates,
    Identity,
    RedactionSummary,
    SourceBlock,
    SourcePosition,
    SourceText,
    UserFactBase,
    VerifiedSkill,
    content_sha256,
    sha256_json,
)
from resume_tailor.storage import (
    ProtocolError,
    ensure_private_directory,
    json_bytes,
    profile_snapshot_path,
    read_model,
    resolve_input_path,
    write_exclusive,
    write_json_exclusive,
)

EXTRACTOR_VERSION = "1"

_EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\[\]{}]+", re.I)
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,5}"
    r"(?:street|st|road|rd|avenue|ave|boulevard|blvd|lane|ln|drive|dr|way)\b",
    re.I,
)
_PHONE = re.compile(r"(?<!\w)\+?[\d(][\d(). -]{7,}\d(?!\w)")
_YEAR_RANGE = re.compile(r"(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"


class IdentityFile(Contract):
    schema_version: Literal[1] = 1
    identity: Identity


def _normalize_whitespace(value: str) -> str:
    value = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", "-", value)
    return " ".join(value.split())


def _quote_matches_source_blocks(
    quote: str,
    source_block_ids: list[str],
    blocks_by_id: dict[str, str],
    source_block_order: dict[str, int],
) -> bool:
    selected = [
        (block_id, blocks_by_id[block_id])
        for block_id in source_block_ids
        if block_id in blocks_by_id
    ]
    if any(quote in _normalize_whitespace(text) for _, text in selected):
        return True
    if len(selected) != len(source_block_ids):
        return False

    block_indexes = [source_block_order[block_id] for block_id, _ in selected]
    if len(block_indexes) < 2 or any(
        current != previous + 1
        for previous, current in zip(block_indexes, block_indexes[1:], strict=False)
    ):
        return False

    combined_source = "\n".join(text for _, text in selected)
    return quote in _normalize_whitespace(combined_source)


def _extract_blocks(
    data: bytes, suffix: str
) -> tuple[list[tuple[str, SourcePosition]], list[str], str]:
    warnings: list[str] = []
    blocks: list[tuple[str, SourcePosition]] = []
    if suffix == ".txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ProtocolError("Text input must be valid UTF-8.") from error
        offset = 0
        for paragraph_index, paragraph in enumerate(text.splitlines()):
            start = offset
            offset += len(paragraph) + 1
            if paragraph.strip():
                blocks.append(
                    (
                        paragraph,
                        SourcePosition(
                            start_offset=start,
                            end_offset=start + len(paragraph),
                            paragraph=paragraph_index,
                        ),
                    )
                )
        if re.search(r"\t| {3,}", text):
            warnings.append("Possible multi-column or tabular text layout.")
    elif suffix == ".docx":
        try:
            document = Document(io.BytesIO(data))
            paragraph_index = 0
            for child in document.element.body.iterchildren():
                if isinstance(child, CT_P):
                    paragraph = Paragraph(child, document).text
                    if paragraph.strip():
                        blocks.append((paragraph, SourcePosition(paragraph=paragraph_index)))
                    paragraph_index += 1
                elif isinstance(child, CT_Tbl):
                    table = Table(child, document)
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                if paragraph.text.strip():
                                    blocks.append(
                                        (paragraph.text, SourcePosition(paragraph=paragraph_index))
                                    )
                                paragraph_index += 1
        except Exception as error:
            raise ProtocolError("Could not extract supported DOCX text.") from error
    elif suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    blocks.append((page_text, SourcePosition(page=page_number)))
        except Exception as error:
            raise ProtocolError("Could not extract supported PDF text.") from error
        if not blocks:
            raise ProtocolError("PDF has no extractable text layer.")
    else:
        raise ProtocolError("Supported input formats are TXT, DOCX, and PDF.")

    if not blocks:
        raise ProtocolError("No extractable text was found.")
    if any("\ufffd" in text for text, _ in blocks):
        warnings.append("Extracted text contains replacement characters.")
    return blocks, warnings, {".txt": "utf-8-text", ".docx": "python-docx", ".pdf": "pypdf"}[suffix]


def _redact_texts(
    blocks: list[tuple[str, SourcePosition]],
) -> tuple[list[tuple[str, SourcePosition]], list[dict[str, str]], dict[str, str], Counter[str]]:
    mappings: list[dict[str, str]] = []
    values_by_key: dict[tuple[str, str], str] = {}
    identity: dict[str, str] = {}
    counts: Counter[str] = Counter()
    patterns = (("email", _EMAIL), ("link", _URL), ("street_address", _ADDRESS), ("phone", _PHONE))

    redacted_blocks: list[tuple[str, SourcePosition]] = []
    for text, position in blocks:
        redacted = text
        for category, pattern in patterns:
            def replace(match: re.Match[str], category: str = category) -> str:
                value = match.group(0)
                if category == "phone" and _YEAR_RANGE.fullmatch(value.strip()):
                    return value
                if category == "link":
                    suffix = ""
                    while value and value[-1] in _TRAILING_URL_PUNCTUATION:
                        suffix = value[-1] + suffix
                        value = value[:-1]
                else:
                    suffix = ""
                counts[category] += 1
                key = (category, value)
                placeholder = values_by_key.get(key)
                if placeholder is None:
                    category_count = sum(item["type"] == category for item in mappings) + 1
                    placeholder = f"[{category.upper()}_{category_count}]"
                    values_by_key[key] = placeholder
                    mappings.append({"placeholder": placeholder, "value": value, "type": category})
                    if category == "email":
                        identity.setdefault("email", value)
                    elif category == "phone":
                        identity.setdefault("phone", value)
                    elif category == "link":
                        lowered = value.lower()
                        if "linkedin.com" in lowered:
                            identity.setdefault("linkedin_url", value)
                        elif "github.com" in lowered:
                            identity.setdefault("github_url", value)
                        else:
                            identity.setdefault("portfolio_url", value)
                return placeholder + suffix

            redacted = pattern.sub(replace, redacted)
        redacted_blocks.append((redacted, position))
    return redacted_blocks, mappings, identity, counts


def _block_id(source_sha256: str, index: int, position: SourcePosition) -> str:
    seed = f"{source_sha256}:{EXTRACTOR_VERSION}:{index}:{position.model_dump_json()}"
    return f"blk_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def extract_source_text(
    source_path: str | Path,
    out_path: str | Path | None = None,
    *,
    no_redact: bool = False,
) -> tuple[SourceText, list[Path]]:
    input_path = resolve_input_path(source_path)
    try:
        source_bytes = input_path.read_bytes()
    except OSError as error:
        raise ProtocolError("Could not read the explicitly selected source file.") from error
    suffix = input_path.suffix.lower()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    raw_blocks, warnings, extractor = _extract_blocks(source_bytes, suffix)
    if no_redact:
        output_blocks, mappings, identity, counts = raw_blocks, [], {}, Counter()
    else:
        output_blocks, mappings, identity, counts = _redact_texts(raw_blocks)

    blocks = [
        SourceBlock(
            block_id=_block_id(source_sha, index, position),
            text=text,
            position=position,
        )
        for index, (text, position) in enumerate(output_blocks)
    ]
    source = SourceText(
        source_sha256=source_sha,
        format=suffix[1:],
        extractor=extractor,
        extractor_version=EXTRACTOR_VERSION,
        blocks=blocks,
        warnings=warnings,
        redaction=RedactionSummary(enabled=not no_redact, counts=dict(counts)),
    )

    if out_path is None:
        output_dir = ensure_private_directory("private_data/storage/fact_base/sources")
        output_path = output_dir / f"{source_sha}.json"
    else:
        output_path = Path(out_path).expanduser()
        if not output_path.parent.is_dir():
            raise ProtocolError("The explicitly selected output directory does not exist.")

    outputs: list[tuple[Path, bytes]] = []
    if mappings:
        mapping_path = output_path.with_name(f"{source_sha}.redaction.json")
        outputs.append(
            (
                mapping_path,
                json_bytes(
                    {
                        "schema_version": 1,
                        "source_sha256": source_sha,
                        "mappings": mappings,
                    }
                ),
            )
        )
        identity_path = output_path.parent / "identity.local.json"
        if identity and not identity_path.exists():
            outputs.append(
                (
                    identity_path,
                    json_bytes(
                        {
                            "schema_version": 1,
                            "identity": Identity(**identity).model_dump(mode="json"),
                        }
                    ),
                )
            )
    outputs.append((output_path, json_bytes(source)))
    for path, _ in outputs:
        if path.exists():
            raise ProtocolError("Output target already exists.", code="output_conflict")
    created: list[Path] = []
    try:
        for path, content in outputs:
            write_exclusive(path, content)
            created.append(path)
    except ProtocolError:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return source, created


def _candidate_items(
    candidates: FactCandidates,
) -> list[tuple[str, str, BaseModel, str, str | None]]:
    items: list[tuple[str, str, BaseModel, str, str | None]] = []
    for education in candidates.education:
        items.append(("education", education.edu_id, education, "Education", None))
    for experience in candidates.work_experiences:
        items.append(("work_experience", experience.exp_id, experience, "Work experience", "high"))
        for bullet in experience.bullets:
            items.append(("evidence_bullet", bullet.fact_id, bullet, "Experience bullet", None))
    for project in candidates.projects:
        items.append(("project", project.project_id, project, "Project", None))
        for bullet in project.bullets:
            items.append(("evidence_bullet", bullet.fact_id, bullet, "Project bullet", None))
    for skill in candidates.verified_skills:
        items.append(("verified_skill", skill.skill_id, skill, "Skill", "high"))
    return items


def _escape_ledger_text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>])", r"\\\1", value.replace("\r", ""))


def _ledger_text(candidates: FactCandidates) -> str:
    lines = [
        "# Resume fact confirmation ledger",
        "",
        f"Candidate version: `{candidates.version}`",
        "",
        "One source-level confirmation covers all facts extracted from the user-provided resume.",
        "High-risk labels are informational; ask individually only about unclear or "
        "conflicting items.",
        "A clear user selection is final; do not request a second typed confirmation.",
        "",
    ]
    for object_type, object_id, item, label, risk in _candidate_items(candidates):
        item_hash = content_sha256(item)
        if isinstance(item, EvidenceBullet):
            detail = item.verified_statement
            lines.extend(
                [
                    f"- `{object_type}:{object_id}` ({label}; sha256 `{item_hash}`)"
                    + (" **HIGH RISK: metric/responsibility**" if item.verified_metrics else ""),
                    f"  - Raw source: {_escape_ledger_text(item.raw_source_text)}",
                    f"  - Normalized statement: {_escape_ledger_text(detail)}",
                ]
            )
            for metric in item.verified_metrics:
                lines.append(
                    "  - Metric: "
                    + _escape_ledger_text(
                        f"{metric.raw_statement} [{metric.metric_id}; {metric.qualifier}]"
                    )
                )
        elif isinstance(item, VerifiedSkill):
            lines.extend(
                [
                    f"- `{object_type}:{object_id}` ({label}; HIGH RISK; sha256 `{item_hash}`)",
                    f"  - Raw source: {_escape_ledger_text(item.raw_source_text)}",
                    f"  - Skill: {_escape_ledger_text(item.skill_name)}",
                ]
            )
        else:
            summary = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            lines.append(
                f"- `{object_type}:{object_id}` ({label}; sha256 `{item_hash}`)"
                + (" **HIGH RISK**" if risk else "")
                + f" — {_escape_ledger_text(summary)}"
            )
    if candidates.unparsed_sections:
        lines.extend(["", "## Unparsed sections", ""])
        for section in candidates.unparsed_sections:
            lines.append(
                f"- {_escape_ledger_text(section.title)}: "
                f"source blocks {', '.join(f'`{item}`' for item in section.source_block_ids)}"
            )
    lines.append("")
    return "\n".join(lines)


def validate_fact_candidates(
    source_path: str | Path,
    candidates_path: str | Path,
    ledger_out: str | Path | None = None,
) -> tuple[FactCandidates, str, Path, list[list[str]]]:
    source = read_model(source_path, SourceText)
    candidates = read_model(candidates_path, FactCandidates)
    blocks_by_id = {block.block_id: block.text for block in source.blocks}
    source_block_order = {
        block.block_id: index for index, block in enumerate(source.blocks)
    }
    seen: set[tuple[str, str]] = set()
    issues: list[str] = []
    referenced_source_block_ids: set[str] = set()
    for object_type, object_id, item, _, _ in _candidate_items(candidates):
        key = (object_type, object_id)
        if key in seen:
            issues.append("duplicate_fact_id")
        seen.add(key)
        if getattr(item, "user_confirmed", False):
            issues.append("candidate_already_confirmed")
        supplied_hash = getattr(item, "content_sha256", None)
        if supplied_hash and supplied_hash != content_sha256(item):
            issues.append("candidate_content_hash_mismatch")
        if isinstance(item, EvidenceBullet):
            if item.source_kind == "resume_extract":
                selected = [
                    blocks_by_id[value]
                    for value in item.source_block_ids
                    if value in blocks_by_id
                ]
                if not item.source_block_ids or len(selected) != len(item.source_block_ids):
                    issues.append("unknown_source_block")
                else:
                    referenced_source_block_ids.update(item.source_block_ids)
                quote = _normalize_whitespace(item.raw_source_text)
                if not quote:
                    issues.append("missing_source_quote")
                elif selected and not _quote_matches_source_blocks(
                    quote,
                    item.source_block_ids,
                    blocks_by_id,
                    source_block_order,
                ):
                    issues.append("source_quote_not_found")
            elif not item.raw_source_text.strip():
                issues.append("missing_user_source")
        elif isinstance(item, VerifiedSkill) and item.source_kind == "resume_extract":
            quote = _normalize_whitespace(item.raw_source_text)
            if not quote:
                issues.append("missing_source_quote")
            elif not any(quote in _normalize_whitespace(text) for text in blocks_by_id.values()):
                issues.append("source_quote_not_found")

    for section in candidates.unparsed_sections:
        if not section.source_block_ids or any(
            value not in blocks_by_id for value in section.source_block_ids
        ):
            issues.append("unknown_unparsed_source_block")
        else:
            referenced_source_block_ids.update(section.source_block_ids)

    if set(blocks_by_id) - referenced_source_block_ids:
        issues.append("source_blocks_unaccounted")

    if issues:
        raise ProtocolError(
            "Fact candidates failed source or confirmation validation.",
            code=sorted(set(issues))[0],
            blocked=True,
        )

    ledger = _ledger_text(candidates)
    ledger_sha = hashlib.sha256(ledger.encode("utf-8")).hexdigest()
    if ledger_out is None:
        ledger_dir = ensure_private_directory("private_data/storage/fact_base/ledgers")
        output_path = ledger_dir / f"{ledger_sha}.md"
    else:
        output_path = Path(ledger_out).expanduser()
        if not output_path.parent.is_dir():
            raise ProtocolError("The explicitly selected ledger directory does not exist.")
    write_exclusive(output_path, ledger.encode("utf-8"))
    return candidates, ledger_sha, output_path, [
        section.source_block_ids for section in candidates.unparsed_sections
    ]


def _confirmation_map(records: ConfirmationRecords) -> dict[tuple[str, str], ConfirmationEntry]:
    entries: dict[tuple[str, str], ConfirmationEntry] = {}
    for entry in records.entries:
        key = (entry.object_type, entry.object_id)
        if key in entries:
            raise ProtocolError(
                "Confirmation records contain duplicate item IDs.",
                code="confirmation_invalid",
                blocked=True,
            )
        entries[key] = entry
    return entries


def _parent_fact_base(path: str | Path | None) -> FactBaseSnapshot | None:
    if path is None:
        return None
    snapshot = read_model(path, FactBaseSnapshot)
    if sha256_json(snapshot.fact_base) != snapshot.snapshot_sha256:
        raise ProtocolError(
            "Parent snapshot hash does not match its contents.",
            code="snapshot_hash_mismatch",
            blocked=True,
        )
    return snapshot


def build_fact_snapshot(
    candidates_path: str | Path,
    confirmations_path: str | Path,
    out_path: str | Path | None,
    *,
    identity_path: str | Path | None = None,
    parent_path: str | Path | None = None,
    profile_name: str | None = None,
    profile_source_path: str | Path | None = None,
) -> FactBaseSnapshot:
    profile_mode = profile_name is not None or profile_source_path is not None
    if profile_mode and (
        profile_name is None or profile_source_path is None or out_path is not None
    ):
        raise ProtocolError(
            "Profile snapshots require a name and source, without --out.",
            code="profile_invalid",
        )
    if not profile_mode and out_path is None:
        raise ProtocolError("An explicit snapshot output path is required.")

    candidates = read_model(candidates_path, FactCandidates)
    confirmations = read_model(confirmations_path, ConfirmationRecords)
    profile_source = (
        read_model(profile_source_path, SourceText) if profile_source_path is not None else None
    )
    parent = _parent_fact_base(parent_path)
    if profile_name is not None and parent is not None and parent.profile_name != profile_name:
        raise ProtocolError(
            "Parent snapshot does not match the selected profile.",
            code="profile_mismatch",
            blocked=True,
        )
    for _, _, item, _, _ in _candidate_items(candidates):
        if getattr(item, "user_confirmed", False):
            raise ProtocolError(
                "Fact candidates must enter snapshot building unconfirmed.",
                code="candidate_already_confirmed",
                blocked=True,
            )
    ledger = _ledger_text(candidates)
    actual_ledger_hash = hashlib.sha256(ledger.encode("utf-8")).hexdigest()
    if actual_ledger_hash != confirmations.ledger_sha256:
        raise ProtocolError(
            "Confirmation ledger does not match the candidate facts.",
            code="ledger_hash_mismatch",
            blocked=True,
        )

    entries = _confirmation_map(confirmations)
    candidate_items = {
        (object_type, object_id): item
        for object_type, object_id, item, _, _ in _candidate_items(candidates)
    }
    if set(entries) - set(candidate_items):
        raise ProtocolError(
            "Confirmation records reference unknown facts.",
            code="unknown_confirmation",
            blocked=True,
        )
    for key, entry in entries.items():
        item = candidate_items[key]
        if entry.content_sha256 != content_sha256(item):
            raise ProtocolError(
                "A confirmed fact changed after ledger approval.",
                code="fact_hash_mismatch",
                blocked=True,
            )
        if entry.decision == "edited":
            raise ProtocolError(
                "Edited facts must be resubmitted for validation.",
                code="edited_fact_requires_revalidation",
                blocked=True,
            )
        if (
            entry.decision == "confirmed"
            and isinstance(item, EvidenceBullet)
            and item.source_kind == "user_confirmation"
            and not entry.user_words.strip()
        ):
            raise ProtocolError(
                "User-confirmed facts need the user's original words.",
                code="missing_user_source",
                blocked=True,
            )

    education = {item.edu_id: item for item in parent.fact_base.education} if parent else {}
    experiences = (
        {item.exp_id: item for item in parent.fact_base.work_experiences} if parent else {}
    )
    projects = {item.project_id: item for item in parent.fact_base.projects} if parent else {}
    skills = {item.skill_id: item for item in parent.fact_base.verified_skills} if parent else {}

    for item in candidates.education:
        entry = entries.get(("education", item.edu_id))
        if entry and entry.decision == "confirmed":
            education[item.edu_id] = item.model_copy(
                update={"user_confirmed": True, "content_sha256": content_sha256(item)}
            )
        elif entry and entry.decision == "rejected":
            education.pop(item.edu_id, None)
    for item in candidates.work_experiences:
        entry = entries.get(("work_experience", item.exp_id))
        if entry and entry.decision == "confirmed":
            bullets = []
            for bullet in item.bullets:
                bullet_entry = entries.get(("evidence_bullet", bullet.fact_id))
                if bullet_entry and bullet_entry.decision == "confirmed":
                    bullets.append(
                        bullet.model_copy(
                            update={
                                "user_confirmed": True,
                                "content_sha256": content_sha256(bullet),
                            }
                        )
                    )
            confirmed_experience = item.model_copy(
                update={"user_confirmed": True, "content_sha256": None, "bullets": bullets}
            )
            experiences[item.exp_id] = confirmed_experience.model_copy(
                update={"content_sha256": content_sha256(confirmed_experience)}
            )
        elif entry and entry.decision == "rejected":
            experiences.pop(item.exp_id, None)
    for item in candidates.projects:
        entry = entries.get(("project", item.project_id))
        if entry and entry.decision == "confirmed":
            bullets = []
            for bullet in item.bullets:
                bullet_entry = entries.get(("evidence_bullet", bullet.fact_id))
                if bullet_entry and bullet_entry.decision == "confirmed":
                    bullets.append(
                        bullet.model_copy(
                            update={
                                "user_confirmed": True,
                                "content_sha256": content_sha256(bullet),
                            }
                        )
                    )
            confirmed_project = item.model_copy(
                update={"user_confirmed": True, "content_sha256": None, "bullets": bullets}
            )
            projects[item.project_id] = confirmed_project.model_copy(
                update={"content_sha256": content_sha256(confirmed_project)}
            )
        elif entry and entry.decision == "rejected":
            projects.pop(item.project_id, None)
    for item in candidates.verified_skills:
        entry = entries.get(("verified_skill", item.skill_id))
        if entry and entry.decision == "confirmed":
            skills[item.skill_id] = item.model_copy(
                update={"user_confirmed": True, "content_sha256": content_sha256(item)}
            )
        elif entry and entry.decision == "rejected":
            skills.pop(item.skill_id, None)

    if identity_path is not None:
        identity_file = read_model(identity_path, IdentityFile)
        identity = identity_file.identity.model_copy(
            update={
                "user_confirmed": True,
                "content_sha256": content_sha256(identity_file.identity),
            }
        )
    elif parent:
        identity = parent.fact_base.identity
    else:
        identity = Identity(user_confirmed=True, content_sha256=content_sha256(Identity()))

    fact_base = UserFactBase(
        user_id=profile_name or candidates.user_id,
        version=(parent.fact_base.version + 1) if parent else candidates.version,
        identity=identity,
        education=list(education.values()),
        work_experiences=list(experiences.values()),
        projects=list(projects.values()),
        verified_skills=list(skills.values()),
        preferences=candidates.preferences,
    )
    snapshot = FactBaseSnapshot(
        snapshot_id=f"snap_{uuid4().hex}",
        snapshot_sha256=sha256_json(fact_base),
        parent_snapshot_sha256=parent.snapshot_sha256 if parent else None,
        ledger_sha256=confirmations.ledger_sha256,
        created_at=datetime.now(UTC),
        profile_name=profile_name,
        resume_source_sha256=profile_source.source_sha256 if profile_source else None,
        fact_base=fact_base,
    )
    output_path = (
        profile_snapshot_path(
            profile_name,
            snapshot.fact_base.version,
            snapshot.resume_source_sha256,
        )
        if profile_name is not None and snapshot.resume_source_sha256 is not None
        else Path(out_path) if out_path is not None else None
    )
    if output_path is None:
        raise ProtocolError("Snapshot output could not be determined.", code="invalid_input")
    write_json_exclusive(output_path, snapshot)
    return snapshot