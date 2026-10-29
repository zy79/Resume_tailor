from pathlib import Path

from resume_tailor import cli
from resume_tailor.cli import _read_document


class FakeAgent:
    async def tailor_resume(self, *, resume_text: str, job_description: str) -> str:
        assert resume_text == "Synthetic resume"
        assert job_description == "Synthetic job description"
        return "Synthetic tailored resume"


def test_read_document_uses_default_path_when_prompt_is_blank(
    monkeypatch,
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "resume.txt"
    document_path.write_text("Resume contents", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "")

    document = _read_document("Resume", None, document_path)

    assert document == "Resume contents"


def test_cli_uses_private_data_defaults(monkeypatch, tmp_path: Path, capsys) -> None:
    private_data = tmp_path / "private_data"
    private_data.mkdir()
    (private_data / "resume.txt").write_text("Synthetic resume", encoding="utf-8")
    (private_data / "job_description.txt").write_text(
        "Synthetic job description", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.setattr(cli, "ResumeTailoringAgent", FakeAgent)

    assert cli.main([]) == 0
    assert capsys.readouterr().out == "Synthetic tailored resume\n"


def test_cli_does_not_fall_back_to_documents(monkeypatch, tmp_path: Path, capsys) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "resume.txt").write_text("Synthetic resume", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)

    assert cli.main([]) == 1
    assert "private_data/resume.txt" in capsys.readouterr().err


def test_cli_accepts_explicit_input_and_output_paths(monkeypatch, tmp_path: Path) -> None:
    resume = tmp_path / "input-resume.txt"
    job = tmp_path / "input-job.txt"
    output = tmp_path / "output" / "tailored.txt"
    resume.write_text("Synthetic resume", encoding="utf-8")
    job.write_text("Synthetic job description", encoding="utf-8")
    monkeypatch.setattr(cli, "load_dotenv", lambda: False)
    monkeypatch.setattr(cli, "ResumeTailoringAgent", FakeAgent)

    result = cli.main(
        ["--resume", str(resume), "--job-description", str(job), "--output", str(output)]
    )
    assert result == 0
    assert output.read_text(encoding="utf-8") == "Synthetic tailored resume"