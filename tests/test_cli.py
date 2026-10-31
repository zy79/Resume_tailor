import json
import stat
from pathlib import Path

import pytest

from resume_tailor import cli
from resume_tailor.contracts import (
    FactBaseSnapshot,
    FactCandidates,
    JobRequirements,
    TailoredResumePayload,
    UnparsedSection,
    UserFactBase,
    sha256_json,
)
from resume_tailor.exchange import extract_source_text


def test_extract_text_emits_json_without_source_text(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.txt"
    output = tmp_path / "source.json"
    source.write_text("Synthetic Engineer\nreader@example.test", encoding="utf-8")

    result = cli.main(["extract-text", str(source), "--out", str(output)])
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)

    assert result == 0
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "extract-text"
    assert envelope["status"] == "ok"
    assert "reader@example.test" not in captured.out
    assert "reader@example.test" not in captured.err
    assert output.exists()


def test_diagnostics_record_cli_step_without_document_text(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    probe = "Synthetic Resume Probe reader@example.test"
    source = tmp_path / "source.txt"
    output = tmp_path / "source.json"
    diagnostics = Path("private_data/tmp/run_123/extract-resume.json")
    source.write_text(probe, encoding="utf-8")

    result = cli.main(
        [
            "extract-text",
            str(source),
            "--out",
            str(output),
            "--diagnostics-out",
            str(diagnostics),
        ]
    )
    captured = capsys.readouterr()
    record_path = tmp_path / diagnostics
    record_text = record_path.read_text(encoding="utf-8")
    record = json.loads(record_text)

    assert result == 0
    assert record["run_id"] == "run_123"
    assert record["step"] == "extract-resume"
    assert record["command"] == "extract-text"
    assert record["status"] == "ok"
    assert record["exit_code"] == 0
    assert record["artifacts"][0]["role"] == "privacy_sidecar"
    assert probe not in record_text
    assert probe not in captured.out
    assert probe not in captured.err
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(record_path.parent.stat().st_mode) == 0o700


def test_diagnostics_record_failed_cli_step_without_document_text(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    probe = "Synthetic Resume Probe"
    diagnostics = Path("private_data/tmp/run_456/extract-resume.json")

    result = cli.main(
        [
            "extract-text",
            str(tmp_path / f"{probe}.txt"),
            "--diagnostics-out",
            str(diagnostics),
        ]
    )
    captured = capsys.readouterr()
    record_path = tmp_path / diagnostics
    record_text = record_path.read_text(encoding="utf-8")
    record = json.loads(record_text)

    assert result == 1
    assert record["run_id"] == "run_456"
    assert record["step"] == "extract-resume"
    assert record["status"] == "error"
    assert record["exit_code"] == 1
    assert record["issue_codes"] == ["invalid_input"]
    assert probe not in record_text
    assert probe not in captured.err


def test_diagnostics_path_is_restricted_before_command_runs(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "source.txt"
    output = tmp_path / "source.json"
    source.write_text("Synthetic input.", encoding="utf-8")

    result = cli.main(
        [
            "extract-text",
            str(source),
            "--out",
            str(output),
            "--diagnostics-out",
            str(tmp_path / "outside.json"),
        ]
    )
    captured = capsys.readouterr()

    assert result == 1
    assert "private_data/tmp" in captured.err
    assert not output.exists()


def test_gate_block_is_json_and_uses_exit_code_3(tmp_path: Path, capsys) -> None:
    fact_base = UserFactBase()
    snapshot = FactBaseSnapshot(
        snapshot_id="snap_synthetic",
        snapshot_sha256=sha256_json(fact_base),
        ledger_sha256="0" * 64,
        created_at="2026-01-01T00:00:00Z",
        fact_base=fact_base,
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    payload = TailoredResumePayload(
        snapshot_sha256=snapshot.snapshot_sha256,
        selected_skill_ids=[],
    )
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(payload.model_dump_json(), encoding="utf-8")

    result = cli.main(
        ["check-facts", "--snapshot", str(snapshot_path), "--payload", str(payload_path)]
    )
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)

    assert result == 3
    assert envelope["status"] == "blocked"
    assert envelope["issues"]
    assert captured.err == ""


def test_check_facts_exposes_canonical_requirements_hash(
    tmp_path: Path, capsys
) -> None:
    fact_base = UserFactBase()
    snapshot = FactBaseSnapshot(
        snapshot_id="snap_synthetic",
        snapshot_sha256=sha256_json(fact_base),
        ledger_sha256="0" * 64,
        created_at="2026-01-01T00:00:00Z",
        fact_base=fact_base,
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(snapshot.model_dump_json(), encoding="utf-8")
    payload = TailoredResumePayload(
        snapshot_sha256=snapshot.snapshot_sha256,
        selected_skill_ids=[],
    )
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(payload.model_dump_json(), encoding="utf-8")
    requirements = JobRequirements(
        jd_text_sha256="a" * 64,
        company_name="Synthetic Company",
        role_title="Synthetic Role",
    )
    requirements_path = tmp_path / "requirements.json"
    requirements_path.write_text(requirements.model_dump_json(), encoding="utf-8")

    result = cli.main(
        [
            "check-facts",
            "--snapshot",
            str(snapshot_path),
            "--payload",
            str(payload_path),
            "--requirements",
            str(requirements_path),
        ]
    )
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    audit_report = envelope["data"]["audit_report"]

    assert result == 3
    assert audit_report["expected_job_requirements_sha256"] == sha256_json(requirements)
    assert any(
        check["issue_code"] == "requirements_binding_mismatch" and not check["passed"]
        for check in audit_report["checks"]
    )
    assert "Synthetic Company" not in captured.out
    assert "Synthetic Company" not in captured.err
    assert captured.err == ""


def test_validate_facts_does_not_echo_unparsed_section_text(
    tmp_path: Path, capsys
) -> None:
    source_text = "Synthetic private section text that must not appear in command output."
    source_path = tmp_path / "source.txt"
    source_path.write_text(source_text, encoding="utf-8")
    source_json = tmp_path / "source.json"
    source, _ = extract_source_text(source_path, source_json)
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        FactCandidates(
            unparsed_sections=[
                UnparsedSection(
                    title=source_text,
                    source_block_ids=[source.blocks[0].block_id],
                )
            ]
        ).model_dump_json(),
        encoding="utf-8",
    )

    result = cli.main(
        [
            "validate-facts",
            "--source",
            str(source_json),
            "--candidates",
            str(candidates_path),
            "--ledger-out",
            str(tmp_path / "ledger.md"),
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert source_text not in captured.out
    assert source_text not in captured.err


def test_usage_error_keeps_argparse_exit_code_2(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["build-snapshot"])

    assert error.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_render_accepts_explicit_job_requirements_path() -> None:
    args = cli._build_parser().parse_args(
        [
            "render",
            "--snapshot",
            "snapshot.json",
            "--payload",
            "payload.json",
            "--out-dir",
            "candidate",
            "--requirements",
            "requirements.json",
        ]
    )

    assert args.requirements == Path("requirements.json")


def test_cli_module_does_not_import_dotenv_or_model_agent() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")

    assert "dotenv" not in source
    assert "resume_tailor.agent" not in source
    assert "input(" not in source


def test_extract_default_uses_managed_private_storage(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("Synthetic engineer.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["extract-text", str(source)]) == 0
    envelope = json.loads(capsys.readouterr().out)
    stored_path = Path(envelope["data"]["source_path"])

    assert stored_path.is_relative_to(tmp_path / "private_data/storage/fact_base/sources")
    assert stored_path.exists()