import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from resume_tailor.agent import AgentNotConfigured, ResumeTailoringAgent

DEFAULT_RESUME_PATH = Path("documents/resume.txt")
DEFAULT_JOB_DESCRIPTION_PATH = Path("documents/job_description.txt")


def _read_document(
    label: str,
    supplied_path: Path | None,
    default_path: Path,
) -> str:
    path = supplied_path
    if path is None:
        entered_path = input(f"{label} file [{default_path}]: ").strip()
        path = Path(entered_path).expanduser() if entered_path else default_path
    else:
        path = path.expanduser()

    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Could not read {label.lower()} file '{path}': {error}") from error

    if not document.strip():
        raise ValueError(f"{label} file '{path}' is empty.")
    return document


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-tailor")
    parser.add_argument("--resume", type=Path, help="Path to a resume text file")
    parser.add_argument(
        "--job-description",
        type=Path,
        help="Path to a job-description text file",
    )
    parser.add_argument("--output", type=Path, help="Optional path for the tailored resume")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_parser().parse_args(argv)
    try:
        resume_text = _read_document("Resume", args.resume, DEFAULT_RESUME_PATH)
        job_description = _read_document(
            "Job description",
            args.job_description,
            DEFAULT_JOB_DESCRIPTION_PATH,
        )
        tailored_resume = asyncio.run(
            ResumeTailoringAgent().tailor_resume(
                resume_text=resume_text,
                job_description=job_description,
            )
        )
        if args.output is None:
            print(tailored_resume)
        else:
            output_path = args.output.expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(tailored_resume, encoding="utf-8")
            print(f"Tailored resume saved to {output_path}")
    except (AgentNotConfigured, OSError, ValueError) as error:
        print(f"resume-tailor: {error}", file=sys.stderr)
        return 1
    return 0