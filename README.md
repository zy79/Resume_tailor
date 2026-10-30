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

### 1. Use Your Private Workspace
Before the first file-content read, the assistant briefly discloses that the host may process
document content and retain the conversation. In this current single-user local workflow, it then
uses this repository's Git-ignored `private_data/` as your workspace automatically. A resume-
tailoring request is enough to read the task-relevant files there; you do not need to select the
folder or approve each read. The assistant checks `private_data/profiles/` first. If no profile
exists, it looks in the same folder for one clearly named resume and one JD. If a profile exists,
it supplies your resume facts, and the assistant still looks in that folder for the current JD
because profiles do not contain job descriptions. If multiple profiles or candidate files exist,
the assistant asks which one to use, not whether it may read your files. Exact paths or pasted text
are alternatives.

If multi-user support is added later, all personal data for each user must live under that user's
own `private_data/users/<stable-user-id>/` folder. The assistant must use only the active user's
folder and must not access another user's files.

For folder discovery, place the resume and target job description in `private_data/`:
- **Resume**: `.pdf` with a text layer, `.docx`, or UTF-8 `.txt` (scanned/image-only PDFs are not supported; OCR is not performed).
- **Job Description**: paste the text in chat, or provide a `.pdf` with a text layer, `.docx`, or UTF-8 `.txt` file. URL fetching is not supported.

The local `extract-text` command supports these file formats for deterministic text extraction.
PDF and TXT are content sources, not layout templates. If you want to preserve the original layout,
provide the original resume as DOCX and use it (or a validated custom DOCX template derived from
it) for rendering. A PDF or TXT candidate must be re-laid out; converting a PDF to DOCX does not
restore its original formatting.
The assistant inspects only immediate filenames in your workspace for discovery. Give the files
clear names; it uses unique resume/JD matches, asks you to choose if either type has multiple
candidates, and does not enter subfolders. When a profile supplies the resume, only a JD file is
needed.

Because `private_data/` is Git-ignored, some host glob/search tools omit it. A zero-match result
from a tool that honors `.gitignore` is inconclusive. If no verified native names-only listing is
available, Linux hosts with GNU `find` use the fixed, read-only exact-depth queries in `PROMPT.md`;
they include ignored entries without opening contents or entering child folders. On other hosts,
use a verified native listing or ask for the exact path only when no safe listing is available.
Candidate names follow the fixed normalization and label rules in `PROMPT.md`; multiple matches
are listed in sorted order and require your choice rather than silently selecting the first.

If you choose to save a profile, the parsed fact snapshot is stored as an immutable version under
`private_data/profiles/<username>/`. The snapshot contains structured facts and source excerpts;
the original resume file and job descriptions are not copied into the profile. A new or changed
resume requires one source-level approval, not item-by-item confirmation. Reusing an unchanged
profile does not ask you to confirm its facts again. Treat the profile as sensitive personal data:
reading it sends its contents to the host model service under the same disclosure as reading a
resume.

### 2. Start Your Coding Assistant
Open this repository in your preferred coding agent (e.g., Claude Code, Codex, or Cursor).

### 3. Send `PROMPT.md` to the Assistant
Provide the contents of [`PROMPT.md`](PROMPT.md) as your initial instruction to the assistant.

### 4. Chat and Review
The assistant will guide you conversationally through each stage:
1. **Input Analysis & Preferences**: After the brief data-flow notice, the assistant uses your current-user workspace without asking you to approve each read. It reads only relevant files, asks which profile or file to use if there are multiple candidates, extracts the company and job title from the JD, and automatically selects the output language from the source content. It uses their shared language, the JD's language if they differ, or the only identifiable source language; it falls back to English only when neither language is clear. It does not ask you to restate clear details or choose optional style preferences; `balanced` is the default. It asks only when a necessary detail is missing or ambiguous. The assistant can preserve the original layout only when the source resume is DOCX and is used as the render-template source (or as the basis for a validated custom template). PDF/TXT inputs require re-layout; if you explicitly require the original layout, provide the original DOCX. A PDF-to-DOCX conversion does not restore formatting. Otherwise, the assistant uses a suitable built-in or custom template and discloses that it is reconstructing the layout; source page count is a target when known, not a guarantee.
2. **Profile & Fact Confirmation**: The assistant checks for a saved profile before asking for a resume. For a first or changed resume, it presents a concise summary and asks for one source-level choice to use the parsed facts. High-risk facts stated in your resume are not re-confirmed one by one; a clear selection is final and does not require typing `confirm` afterward. The assistant still blocks unsupported or ambiguously parsed claims.
3. **Tailored Generation & Verification**: The assistant drafts from confirmed facts and runs local checks for unsupported claims and other invalid output. It does not require the resume to cover every JD requirement. Before drafting, it lists all unsupported or partially supported requirements once, in priority order, and recommends which are worth supplementing with real evidence versus skipping. If useful, it asks one optional batch question for evidence on any chosen rows; it does not ask about requirements one by one, and unanswered gaps are omitted.
4. **Completion & Publishing**: The assistant writes the candidate under `private_data/` without per-write approval, leaves the original resume and JD unchanged, and reports the paths it created. It renders DOCX and PDF when available, then publishes automatically after the deterministic, render-health, and required review gates pass. No separate publish approval or pre-publish preview is required; the assistant reports the final paths so you can review the files.

For troubleshooting, each CLI and host-agent step saves a content-free record under
`private_data/tmp/<run-id>/`. Records contain statuses, error codes, artifact hashes, and counts,
not resume/JD text or model responses.

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

Treat these as starting points and verify them against the installed host version. They are
defense-in-depth, not a security boundary. The assistant should not ask for per-file read permission
within the active user's workspace. Host-level prompts may still apply; configure read access only
for the current user's root. The workflow does not ask for per-write or publish approval, but this
does not bypass host sandbox prompts. Keep host restrictions; never disable sandboxing or grant
broad workspace writes just to avoid a host-level prompt. In future multi-user mode, never grant
access to the shared parent `private_data/` tree.

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
`.claude/settings.local.json`. It denies secret and sidecar reads, source/test/document edits, and
built-in web tools; it allows private-data reads in the current single-user workspace and asks
before shell commands and writes. Its sandbox fails closed if unavailable, requires prompts for
shell commands, blocks shell reads of `.env`, and blocks shell writes to `src/`, `tests/`, and
`documents/`:

```json
{
	"permissions": {
		"defaultMode": "default",
		"deny": [
			"Read(./.env)",
			"Read(./.env.*)",
			"Read(private_data/**/*.redaction.json)",
			"Read(private_data/**/identity.local.json)",
			"WebFetch",
			"WebSearch",
			"Edit(src/**)",
			"Edit(tests/**)",
			"Edit(documents/**)"
		],
		"allow": [
			"Read(private_data/**)"
		],
		"ask": [
			"Bash",
			"Edit(private_data/**)"
		]
	},
	"sandbox": {
		"enabled": true,
		"failIfUnavailable": true,
		"autoAllowBashIfSandboxed": false,
		"allowUnsandboxedCommands": false,
		"filesystem": {
			"denyRead": ["./.env", "./.env.*"],
			"denyWrite": ["./src", "./tests", "./documents"]
		}
	}
}
```

For same-user input or profile discovery, use a host-native exact-depth file-listing tool and
confirm that it includes Git-ignored `private_data/`; an empty result from a glob/search that
honors `.gitignore` does not prove that the directory is empty. If no such tool is available, Linux
hosts with GNU `find` may use only the fixed, read-only queries in `PROMPT.md` for the default
`private_data/` paths. Do not enable arbitrary shell discovery or pass user-supplied paths to those
queries. The
`Read(private_data/**)` example is for this repository's current single-user layout only. If
multi-user support is added, allow reads only under
`private_data/users/<current-user-id>/**`; do not grant the shared parent. Never access another
user's directory. Keep writes ask-gated and approve only requested writes under the active user's
workspace. Do not enable recursive or repository-wide searches; if neither a verified native query
nor the approved Linux fallback is available, ask for exact paths as a clarification, not as a
read-permission confirmation.

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

## Commit-Message Hook

Enable the repository-managed hook once in each clone:

```bash
git config --local core.hooksPath .githooks
```

The hook rejects commit messages with a `Co-authored-by` trailer identifying Copilot.

## Tests

```bash
pytest
ruff check .
```
