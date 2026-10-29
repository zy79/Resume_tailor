from pathlib import Path

from resume_tailor.cli import _read_document


def test_read_document_uses_default_path_when_prompt_is_blank(
    monkeypatch,
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "resume.txt"
    document_path.write_text("Resume contents", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "")

    document = _read_document("Resume", None, document_path)

    assert document == "Resume contents"