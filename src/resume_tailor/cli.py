import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor.contracts import (
    ArtifactInfo,
    CliIssue,
    CliResult,
    DiagnosticArtifact,
    DiagnosticRecord,
)
from resume_tailor.exchange import (
    build_fact_snapshot,
    extract_source_text,
    validate_fact_candidates,
)
from resume_tailor.storage import (
    ProtocolError,
    file_sha256,
    prepare_diagnostic_output,
    profile_snapshot_path,
    write_json_exclusive,
)
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
    output = snapshot.add_mutually_exclusive_group(required=True)
    output.add_argument("--out", type=Path)
    output.add_argument("--profile-name")
    snapshot.add_argument("--profile-source", type=Path)

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

    publish = commands.add_parser("publish", help="Publish a validated managed candidate")
    publish.add_argument("--candidate-dir", type=Path, required=True)
    publish.add_argument(
        "--approval",
        type=Path,
        required=True,
        help="Candidate-bound integrity record with file hashes and review metadata",
    )

    for command in (extract, validate, snapshot, check, render, publish):
        command.add_argument(
            "--diagnostics-out",
            type=Path,
            help="Write a content-free step record under private_data/tmp/<run>/<step>.json",
        )
    return parser


def _artifact(path: Path, role: str) -> ArtifactInfo:
    return ArtifactInfo(path=str(path), role=role, sha256=file_sha256(path))


def _save_diagnostic(
    path: Path | None,
    *,
    command: str,
    status: str,
    exit_code: int,
    issue_codes: list[str] | None = None,
    artifacts: list[ArtifactInfo] | None = None,
    skipped_checks: list[str] | None = None,
) -> None:
    if path is None:
        return
    record = DiagnosticRecord(
        run_id=path.parent.name,
        step=path.stem,
        command=command,
        status=status,
        exit_code=exit_code,
        created_at=datetime.now(UTC),
        issue_codes=issue_codes or [],
        artifacts=[
            DiagnosticArtifact(role=artifact.role, sha256=artifact.sha256)
            for artifact in artifacts or []
        ],
        skipped_checks=skipped_checks or [],
    )
    try:
        write_json_exclusive(path, record)
    except ProtocolError:
        print("resume-tailor: diagnostics record could not be saved.", file=sys.stderr)


def _emit(
    result: CliResult,
    *,
    exit_code: int,
    diagnostics_out: Path | None,
) -> None:
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    _save_diagnostic(
        diagnostics_out,
        command=result.command,
        status=result.status,
        exit_code=exit_code,
        issue_codes=[issue.code for issue in result.issues],
        artifacts=result.artifacts,
        skipped_checks=[check.check for check in result.skipped_checks],
    )


def _dispatch(args: argparse.Namespace, diagnostics_out: Path | None = None) -> int:
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
            ),
            exit_code=0,
            diagnostics_out=diagnostics_out,
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
            ),
            exit_code=0,
            diagnostics_out=diagnostics_out,
        )
        return 0

    if args.command == "build-snapshot":
        snapshot = build_fact_snapshot(
            args.candidates,
            args.confirmations,
            args.out,
            identity_path=args.identity,
            parent_path=args.parent,
            profile_name=args.profile_name,
            profile_source_path=args.profile_source,
        )
        snapshot_path = (
            profile_snapshot_path(
                snapshot.profile_name,
                snapshot.fact_base.version,
                snapshot.resume_source_sha256,
            )
            if snapshot.profile_name is not None
            and snapshot.resume_source_sha256 is not None
            else args.out
        )
        if snapshot_path is None:
            raise ProtocolError("Snapshot output could not be determined.")
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
                artifacts=[_artifact(snapshot_path, "fact_base_snapshot")],
                data={
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_sha256": snapshot.snapshot_sha256,
                    "ledger_sha256": snapshot.ledger_sha256,
                    "confirmed_fact_count": sum(item.user_confirmed for item in fact_items),
                    "profile_name": snapshot.profile_name,
                    "resume_source_sha256": snapshot.resume_source_sha256,
                },
            ),
            exit_code=0,
            diagnostics_out=diagnostics_out,
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
            ),
            exit_code=0 if passed else 3,
            diagnostics_out=diagnostics_out,
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
        _emit(result, exit_code=exit_code, diagnostics_out=diagnostics_out)
        return exit_code

    if args.command == "publish":
        from resume_tailor.publishing import publish_candidate

        result, exit_code = publish_candidate(args.candidate_dir, args.approval)
        _emit(result, exit_code=exit_code, diagnostics_out=diagnostics_out)
        return exit_code

    raise ProtocolError("Unknown command.", code="unknown_command")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "build-snapshot":
        if args.profile_name is not None and args.profile_source is None:
            parser.error("--profile-name requires --profile-source")
        if args.profile_name is None and args.profile_source is not None:
            parser.error("--profile-source requires --profile-name")
    if args.command == "render":
        has_company = bool(args.company)
        has_role = bool(args.role)
        if has_company != has_role:
            parser.error("--company and --role must be used together")
        if has_company == (args.out_dir is not None):
            parser.error("choose either --company with --role, or --out-dir")
        if args.job_id and not has_company:
            parser.error("--job-id requires --company and --role")
    diagnostics_out = None
    try:
        if args.diagnostics_out is not None:
            diagnostics_out = prepare_diagnostic_output(args.diagnostics_out)
        return _dispatch(args, diagnostics_out)
    except ProtocolError as error:
        if error.blocked:
            _emit(
                CliResult(
                    command=args.command,
                    status="blocked",
                    issues=[CliIssue(code=error.code, severity="error", message=str(error))],
                ),
                exit_code=3,
                diagnostics_out=diagnostics_out,
            )
            return 3
        _save_diagnostic(
            diagnostics_out,
            command=args.command,
            status="error",
            exit_code=1,
            issue_codes=[error.code],
        )
        print(f"resume-tailor: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        _save_diagnostic(
            diagnostics_out,
            command=args.command,
            status="error",
            exit_code=1,
            issue_codes=["operation_failed"],
        )
        print(
            "resume-tailor: operation failed; check the explicit inputs and output paths.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        _save_diagnostic(
            diagnostics_out,
            command=args.command,
            status="error",
            exit_code=1,
            issue_codes=["unexpected_error"],
        )
        print("resume-tailor: operation failed unexpectedly.", file=sys.stderr)
        return 1