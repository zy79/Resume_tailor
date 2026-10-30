import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(
    r"(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}"
)
SYNTHETIC_EMAIL_DOMAINS = {"example.com", "example.net", "example.org", "example.test"}


def _git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )


def test_private_data_and_local_dotenv_files_are_ignored() -> None:
    ignored = [
        _git("check-ignore", "--no-index", "--quiet", path).returncode
        for path in (
            ".env",
            ".env.local",
            ".claude/settings.local.json",
            "private_data/resume.txt",
        )
    ]
    env_example = _git("check-ignore", "--no-index", "--quiet", ".env.example")
    public_docs = _git("check-ignore", "--no-index", "--quiet", "documents/README.md")
    tracked = _git("ls-files", "-z")
    tracked_paths = {
        value.decode("utf-8") for value in tracked.stdout.split(b"\0") if value
    }

    assert ignored == [0, 0, 0, 0]
    assert env_example.returncode == 1
    assert public_docs.returncode == 1
    assert ".env.example" in tracked_paths
    assert not any(
        path == ".env" or (path.startswith(".env.") and path != ".env.example")
        for path in tracked_paths
    )
    assert not any(path.startswith("private_data/") for path in tracked_paths)


def test_public_docs_and_tests_contain_only_synthetic_contact_patterns() -> None:
    files = [
        path
        for directory in (ROOT / "documents", ROOT / "tests")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py", ".txt", ".json", ".jsonl"}
    ]

    for path in files:
        content = path.read_text(encoding="utf-8")
        for address in EMAIL_PATTERN.findall(content):
            domain = address.rsplit("@", maxsplit=1)[1].casefold()
            assert domain in SYNTHETIC_EMAIL_DOMAINS, path.relative_to(ROOT)
        for phone in PHONE_PATTERN.findall(content):
            assert "555" in re.sub(r"\D", "", phone), path.relative_to(ROOT)