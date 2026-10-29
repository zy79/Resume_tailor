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

## Documents

Put UTF-8 resume and job-description files in `documents/`. The CLI defaults to:

- `documents/resume.txt`
- `documents/job_description.txt`

The directory is ignored by Git to avoid committing personal documents; its README stays tracked.

## Run

From the repository root, start the interactive CLI:

```bash
resume-tailor
```

It prompts for each document path, using the defaults above when you press Enter. Paths can also be supplied directly:

```bash
resume-tailor --resume documents/resume.txt --job-description documents/job_description.txt --output documents/tailored_resume.txt
```

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
