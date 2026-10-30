import argparse
import json
import sys
from pathlib import Path

from resume_tailor.contracts import ArtifactInfo, CliIssue, CliResult
from resume_tailor.exchange import (
    build_fact_snapshot,
    extract_source_text,
    validate_fact_candidates,
)
from resume_tailor.storage import ProtocolError, file_sha256
from resume_tailor.validation import check_resume_facts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-tailor")
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract-text", help="Extract and locally redact source text")
    extract.add_argument("path", type=Path, help="Explicit TXT, DOCX, or PDF source path")
    extract.add_argument("--out", type=Path)
    extract.add_argument("--no-redact", action="store_true")

    validate = commands.add_parser("validate-facts", help="Validate candidates and render a ledger")
    validate.add_argument("--source", type=Path, required=True)
    validate.add_argument("--candidates", type=Path, required=True)
    validate.add_argument("--ledger-out", type=Path)

    snapshot = commands.add_parser("build-snapshot", help="Build an immutable fact snapshot")
    snapshot.add_argument("--candidates", type=Path, required=True)
    snapshot.add_argument("--confirmations", type=Path, required=True)
    snapshot.add_argument("--identity", type=Path)
    snapshot.add_argument("--parent", type=Path)
    snapshot.add_argument("--out", type=Path, required=True)

    check = commands.add_parser("check-facts", help="Run deterministic payload checks")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--payload", type=Path, required=True)
    check.add_argument("--requirements", type=Path)
    check.add_argument("--review", type=Path)

    render = commands.add_parser("render", help="Render a validated resume candidate")
    render.add_argument("--snapshot", type=Path, required=True)
    render.add_argument("--payload", type=Path, required=True)
    render.add_argument("--company")
    render.add_argument("--role")
    render.add_argument("--out-dir", type=Path)
    render.add_argument("--job-id")
    render.add_argument("--requirements", type=Path)
    render.add_argument("--review", type=Path)
    render.add_argument("--template", default="default")
    render.add_argument("--format", choices=("docx", "markdown"))
    render.add_argument("--run-id")

    publish = commands.add_parser("publish", help="Publish an approved managed candidate")
    publish.add_argument("--candidate-dir", type=Path, required=True)
    publish.add_argument("--approval", type=Path, required=True)
    return parser


def _artifact(path: Path, role: str) -> ArtifactInfo:
    return ArtifactInfo(path=str(path), role=role, sha256=file_sha256(path))


def _emit(result: CliResult) -> None:
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "extract-text":
        source, outputs = extract_source_text(args.path, args.out, no_redact=args.no_redact)
        _emit(
            CliResult(
                command=args.command,
                status="ok",
                artifacts=[
                    _artifact(path, "source_text" if path == outputs[-1] else "privacy_sidecar")
                    for path in outputs
                ],
                data={
                    "source_sha256": source.source_sha256,
                    "source_path": str(outputs[-1]),
                    "redaction": source.redaction.model_dump(mode="json"),
                    "warnings": source.warnings,
                },
            )
        )
        return 0

    if args.command == "validate-facts":
        candidates, ledger_hash, ledger_path, unparsed_sections = validate_fact_candidates(
            args.source, args.candidates, args.ledger_out
        )
        _emit(
            CliResult(
                command=args.command,
                status="ok",
                artifacts=[_artifact(ledger_path, "confirmation_ledger")],
                data={
                    "candidate_version": candidates.version,
                    "ledger_sha256": ledger_hash,
                    "unparsed_sections": unparsed_sections,
                },
            )
        )
        return 0

    if args.command == "build-snapshot":
        snapshot = build_fact_snapshot(
            args.candidates,
            args.confirmations,
            args.out,
            identity_path=args.identity,
            parent_path=args.parent,
        )
        fact_items = [
            *snapshot.fact_base.education,
            *snapshot.fact_base.work_experiences,
            *snapshot.fact_base.projects,
            *snapshot.fact_base.verified_skills,
            *[
                bullet
                for experience in snapshot.fact_base.work_experiences
                for bullet in experience.bullets
            ],
            *[
                bullet
                for project in snapshot.fact_base.projects
                for bullet in project.bullets
            ],
        ]
        _emit(
            CliResult(
                command=args.command,
                status="ok",
                artifacts=[_artifact(args.out, "fact_base_snapshot")],
                data={
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_sha256": snapshot.snapshot_sha256,
                    "ledger_sha256": snapshot.ledger_sha256,
                    "confirmed_fact_count": sum(item.user_confirmed for item in fact_items),
                },
            )
        )
        return 0

    if args.command == "check-facts":
        report = check_resume_facts(
            args.snapshot,
            args.payload,
            requirements_path=args.requirements,
            review_path=args.review,
        )
        passed = all(check.passed for check in report.checks)
        _emit(
            CliResult(
                command=args.command,
                status="ok" if passed else "blocked",
                issues=[
                    CliIssue(
                        code=check.issue_code or check.check,
                        severity="error",
                        message=check.message,
                    )
                    for check in report.checks
                    if not check.passed
                ],
                skipped_checks=report.skipped_checks,
                data={"audit_report": report.model_dump(mode="json")},
            )
        )
        return 0 if passed else 3

    if args.command == "render":
        from resume_tailor.rendering import render_resume

        result, exit_code = render_resume(
            snapshot_path=args.snapshot,
            payload_path=args.payload,
            company_name=args.company,
            role_title=args.role,
            out_dir=args.out_dir,
            job_id=args.job_id,
            review_path=args.review,
            template_name=args.template,
            output_format=args.format,
            run_id=args.run_id,
            requirements_path=args.requirements,
        )
        _emit(result)
        return exit_code

    if args.command == "publish":
        from resume_tailor.publishing import publish_candidate

        result, exit_code = publish_candidate(args.candidate_dir, args.approval)
        _emit(result)
        return exit_code

    raise ProtocolError("Unknown command.", code="unknown_command")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "render":
        has_company = bool(args.company)
        has_role = bool(args.role)
        if has_company != has_role:
            parser.error("--company and --role must be used together")
        if has_company == (args.out_dir is not None):
            parser.error("choose either --company with --role, or --out-dir")
        if args.job_id and not has_company:
            parser.error("--job-id requires --company and --role")
    try:
        return _dispatch(args)
    except ProtocolError as error:
        if error.blocked:
            _emit(
                CliResult(
                    command=args.command,
                    status="blocked",
                    issues=[CliIssue(code=error.code, severity="error", message=str(error))],
                )
            )
            return 3
        print(f"resume-tailor: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(
            "resume-tailor: operation failed; check the explicit inputs and output paths.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print("resume-tailor: operation failed unexpectedly.", file=sys.stderr)
        return 1