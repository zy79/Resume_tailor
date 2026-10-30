# Resume Tailor

Resume Tailor is a Prompt-first local resume-tailoring workflow. Your chosen coding agent conducts
the conversation and drafts content; the Python CLI performs deterministic extraction, fact checks,
rendering, and publishing. The CLI itself makes no model calls and does not read `.env`.

## Requirements

- Python 3.11 or newer
- LibreOffice for PDF output (optional; without it, rendering returns a DOCX or Markdown candidate
	with status `degraded` and exit code `4`)

## Setup

For the model-free CLI, install the core package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For tests and optional API development, install the development extras instead:

```bash
python -m pip install -e ".[dev]"
```

The Prompt workflow does not require this project's API keys, `.env`, FastAPI, or a database. It is
not offline: the selected host may send resume and job-description content to its model service and
may retain the conversation in host-controlled session history. Review that service's privacy
controls before sharing any content.

## User Workflow (Quick Start)

You **do not** need to run terminal commands yourself. Your coding assistant (such as Claude Code, OpenAI Codex, or your IDE agent) executes the background verification and rendering commands automatically while conversing with you in natural language.

All you need to do is follow these 4 simple steps:

### 1. Place Your Resume and Job Description
Place your existing resume and target job description in the Git-ignored `private_data/` folder:
- **Resume**: `.pdf` with a text layer, `.docx`, or UTF-8 `.txt` (scanned/image-only PDFs are not supported; OCR is not performed).
- **Job Description**: paste the text in chat, or provide a `.pdf` with a text layer, `.docx`, or UTF-8 `.txt` file. URL fetching is not supported.

The local `extract-text` command supports these file formats for deterministic text extraction.

### 2. Start Your Coding Assistant
Open this repository in your preferred coding agent (e.g., Claude Code, Codex, or Cursor).

### 3. Send `PROMPT.md` to the Assistant
Provide the contents of [`PROMPT.md`](PROMPT.md) as your initial instruction to the assistant.

### 4. Chat and Confirm Step-by-Step
The assistant will guide you conversationally through each stage:
1. **Preferences**: It will ask for your target job title and preferred tone (`conservative`, `balanced`, or `assertive`). For **template style** and **target page count**, it defaults to matching your existing resume (or you can keep your original layout, provide a custom template, or choose a built-in style like [`classic`, `modern`, or `compact`](documents/templates/README.md)).
2. **Fact Confirmation**: The assistant extracts your facts and shows you a clean confirmation ledger in chat. You can confirm ordinary items in a batch by ledger ID; high-risk facts (metrics, leadership or ownership, skills, dates, and employers) are confirmed one at a time.
3. **Tailored Generation & Verification**: The assistant drafts tailored bullet points aligned with the job description and runs local checks to catch unsupported facts, numbers, and skills. These checks do not replace your review.
4. **Preview & Approval**: The assistant renders your resume candidate (DOCX and PDF). Once you review and approve it, the assistant publishes the finalized package to `private_data/storage/companies/{company}/jobs/{job_id}/final/v1/`.

---

## Under the Hood: The CLI Engine

Behind the chat interface, the assistant coordinates six stateless, non-interactive local commands:

```text
extract-text  validate-facts  build-snapshot  check-facts  render  publish
```

- **Exclusive creation**: Outputs never overwrite existing files.
- **Privacy preservation**: Contact details (email, phone, links, street addresses) are redacted to local sidecars (`.redaction.json`) before being processed by the agent.
- **Deterministic verification**: Code checks ensure all claims in the tailored resume map strictly to confirmed source evidence.
- **Standardized output**: The CLI outputs versioned JSON envelopes without echoing raw resume or JD text to terminal stdout/stderr.

For developers and advanced users who want to inspect the underlying file contracts, exit codes, and CLI parameters, see the [Prompt-Route Technical Reference Guide](documents/prompt_route_user_guide.md).

## Host Permissions And History

Treat these as starting points and verify them against the installed host version. They add
friction; they do not prove that the agent is safe or confine every host capability.

For Codex, keep sandboxing enabled and require approval for commands. A conservative starting point
in `~/.codex/config.toml` is:

```toml
sandbox_mode = "read-only"
approval_policy = "on-request"
web_search = "disabled"

[history]
persistence = "none"
```

The read-only mode prevents routine writes; approve only the specific operation and destination the
user requested. Do not switch to full-access mode for this workflow. The history setting stops
future Codex CLI transcript writes to local `history.jsonl`; it does not erase existing history or
control service-side retention. See [Codex history configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#history-persistence).

For Claude Code, start in the repository root and keep this in the git-ignored
`.claude/settings.local.json`. It denies secret reads, source/test/document edits, and built-in web
tools; it asks before shell commands and private-data access. Its sandbox fails closed if
unavailable, requires prompts for shell commands, blocks shell reads of `.env` and `private_data/`,
and blocks shell writes to `src/`, `tests/`, and `documents/`:

```json
{
	"permissions": {
		"defaultMode": "default",
		"deny": [
			"Read(./.env)",
			"Read(./.env.*)",
			"WebFetch",
			"WebSearch",
			"Edit(src/**)",
			"Edit(tests/**)",
			"Edit(documents/**)"
		],
		"ask": [
			"Bash",
			"Read(private_data/**)",
			"Edit(private_data/**)"
		]
	},
	"sandbox": {
		"enabled": true,
		"failIfUnavailable": true,
		"autoAllowBashIfSandboxed": false,
		"allowUnsandboxedCommands": false,
		"filesystem": {
			"denyRead": ["./.env", "./.env.*", "./private_data"],
			"denyWrite": ["./src", "./tests", "./documents"]
		}
	}
}
```

For shell network egress, put this in your user settings at `~/.claude/settings.json`, not in the
project file:

```json
{
	"sandbox": {
		"network": {
			"strictAllowlist": true
		}
	}
}
```

Strict mode denies shell connections outside the effective allowlist instead of prompting. Review
existing `allowedDomains` entries and `WebFetch(domain:...)` allow rules if you intend to block all
external shell egress; the default allowlist is empty.

Claude Code's `Edit(path)` rule also covers its built-in Write tool; `Write(path)` rules never match.
Check `/status`, `/permissions`, and `/sandbox` to verify the active settings. The shell sandbox
covers Bash commands and their child processes, not the host's own model-service requests or every
helper process; the WebFetch/WebSearch deny rules separately block those built-in tools. These
settings do not manage hosted session retention. See the [current permission
rules](https://code.claude.com/docs/en/permissions), [sandbox settings](https://code.claude.com/docs/en/settings-reference#sandbox),
and [session-data controls](https://code.claude.com/docs/en/sessions#delete-session-data) for your
installed version.

Local history is separate from service-side retention. In Claude Code CLI, `/clear` starts a fresh
context but preserves the previous session; `claude purge` removes local project transcripts and
related state. Review its scope before using it. Desktop, VS Code, and hosted session histories have
their own controls. Claude.ai web conversations are separate from Claude Code CLI transcripts;
deleting local files does not establish that any hosted history was deleted.

## Optional API Scaffold

The FastAPI and LangGraph scaffold remains an optional development path. Provider adapters and the
application API model workflow are not part of Phase 1 and are not used by the Prompt-first CLI.
Install the API extra before starting it:

```bash
python -m pip install -e ".[api]"
```

Then start it with:

```bash
uvicorn resume_tailor.api:app --reload
```

Health check: `http://127.0.0.1:8000/api/health`. Interactive API docs: `http://127.0.0.1:8000/docs`.

## Tests

```bash
pytest
ruff check .
```
