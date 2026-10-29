# Resume Tailor

A Python CLI and API for tailoring a resume to a job description. The workflow is orchestrated with LangGraph.

## Requirements

- Python 3.11 or newer

## Setup

From the repository root, create a virtual environment and install the project:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

## LLM configuration

`.env` has independent settings for the main resume-tailoring model (`MAIN_LLM_*`) and the judge/auditor model (`JUDGE_LLM_*`). Set each provider, model, base URL, and API key as needed. The CLI and API load `.env` at startup; `.env` is ignored by Git.

The provider adapters are not connected yet, so these values are available for the integration but are not used to generate or judge resumes yet.

## Documents and private data

Use `documents/` for general project documents. Put UTF-8 resumes and job descriptions
in the separate `private_data/` directory, which is ignored by Git. From the repository
root, create it with `mkdir -p -m 700 private_data`; the CLI defaults to:

- `private_data/resume.txt`
- `private_data/job_description.txt`

Existing files in `documents/` are not moved automatically and remain ignored by Git
because they may contain personal information. If needed, move your own files to
`private_data/` before running the CLI.

## Run

From the repository root, start the interactive CLI:

```bash
resume-tailor
```

It prompts for each document path, using the defaults above when you press Enter. Paths can also be supplied directly:

```bash
resume-tailor --resume private_data/resume.txt --job-description private_data/job_description.txt --output private_data/tailored_resume.txt
```

Without `--output`, the tailored resume is printed to the terminal.

You can alternatively run it as a module with `python -m resume_tailor`.

The LangGraph validates the inputs and invokes an async model callable supplied to `ResumeTailoringAgent`. A model provider is not configured in this starter, so tailoring reports an explicit configuration error until a provider is connected.

## API

The optional FastAPI endpoint can be started with:

```bash
uvicorn resume_tailor.api:app --reload
```

Health check: `http://127.0.0.1:8000/api/health`. Interactive API docs: `http://127.0.0.1:8000/docs`.

## Tests

```bash
pytest
ruff check .
```
