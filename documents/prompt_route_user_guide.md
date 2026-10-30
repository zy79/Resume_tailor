# Prompt-Route User Guide: Local Resume Tailoring Workflow

> [!IMPORTANT]
> **Who runs these commands?**
> As an end-user or job seeker, you **do not** need to run any of the terminal commands shown in this guide. Your coding assistant executes them for you automatically behind the scenes while conversing with you in natural language.
> For the quick 4-step user walkthrough, see the [Quick Start in README.md](../README.md#user-workflow-quick-start).
> This document serves as the detailed technical reference for how the assistant coordinates the local CLI, data contracts, and verification gates.

---

## 1. Overview & Architecture

The Prompt route enables end-to-end, privacy-conscious resume customization using your existing coding assistant (such as **Claude Code** or **OpenAI Codex**) combined with deterministic local verification tools.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        User & Host Coding Agent                        │
│             (Conducts dialogue, drafts text, executes steps)            │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ Invokes stateless commands via CLI
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    resume-tailor Stateless CLI                         │
│  - extract-text    - validate-facts  - build-snapshot                  │
│  - check-facts     - render          - publish                         │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Deterministic Gatekeepers                         │
│  • Local PII Redaction (.redaction.json sidecar)                       │
│  • Verbatim Substring Proofs & Markdown Confirmation Ledger            │
│  • Immutable Snapshot Binding (SHA-256)                                │
│  • Level 1 & 2 Fact Gates (Skill whitelist, numbers, entities)        │
│  • Sandboxed DOCX/Markdown Rendering & LibreOffice PDF Health Checks   │
│  • Exclusive Versioned Publishing (final/vN/ & manifest.json)          │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **No Project API Keys Required**: Model generation is performed by the host assistant under your existing assistant subscription. The local `resume-tailor` CLI does not read `.env`, import `python-dotenv`, or make external network calls.
2. **Local-First & Explicit Inputs**: Commands operate only on explicitly supplied file paths. They never scan user folders or repository files for personal materials.
3. **Exclusive File Creation**: Outputs are written using exclusive file flags (`os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW` with `0600` file permissions). Existing targets are never silently overwritten.
4. **Transparent Trust Boundary**: The host assistant operates over user-confirmed data and records confirmations. Code provides mathematical certainty over file integrity, verbatim quotation, and schema constraints, but human review remains the final approval authority.
5. **Data Flow & Privacy**: While files remain on your local disk under Git-ignored `private_data/`, interactions with host agents (like Claude Code or Codex) transit the host provider's model services and local conversation transcripts. This workflow is local-first, but not offline.

---

## 2. Installation & Setup

### Requirements

- **Python**: 3.11 or newer
- **LibreOffice** (`soffice`): Recommended for headless PDF conversion and automated visual health checks. If LibreOffice is absent, the pipeline gracefully outputs `.docx` or `.md` candidates with status `degraded` (exit code `4`).

### Installing the CLI

In your project repository:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the core CLI (model-free)
python -m pip install -e .

# Verify installation
resume-tailor --help
```

For development and running test suites:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```

---

## 3. Directory Structure & File Conventions

All personal inputs, intermediate candidates, snapshots, and final versions belong in `private_data/`, which is ignored by Git:

```text
Resume_tailor/
├── PROMPT.md                             # Root instructions for your host agent
├── private_data/                         # GIT-IGNORED: All personal and job materials
│   └── storage/
│       ├── fact_base/
│       │   ├── sources/{source_sha}.json # Extracted resume text (redacted)
│       │   ├── sources/{source_sha}.redaction.json # Local PII mappings (0600)
│       │   ├── identity.local.json       # User-inspected contact details (0600)
│       │   ├── ledgers/{ledger_sha}.md   # Code-rendered confirmation ledger
│       │   └── snapshots/{snap_id}.json  # Immutable confirmed fact snapshots
│       └── companies/
│           └── {company_slug}/
│               └── jobs/
│                   └── {job_id}/
│                       ├── runs/{run_id}/{artifact_id}/
│                       │   ├── candidate.json
│                       │   ├── payload.json
│                       │   ├── audit_report.json
│                       │   ├── generated.docx (or .md)
│                       │   └── generated.pdf
│                       └── final/
│                           └── v1/
│                               ├── resume.docx (or .md)
│                               ├── resume.pdf
│                               ├── approval.json
│                               └── manifest.json
└── documents/                            # Tracked in Git: Only public docs & synthetic samples
```

> [!WARNING]
> Never place real personal resumes, job descriptions, or generated output into `documents/` or commit them to Git.

---

## 4. End-to-End Workflow Walkthrough

Here is the step-by-step lifecycle from raw resume to published document.

### Step 1: Initialize the Session with `PROMPT.md`

Start a session with your host coding agent (e.g. Claude Code or Codex) and provide the contents of the root [`PROMPT.md`](file:///home/yu/Desktop/Python/Resume_tailor/PROMPT.md).

The agent will:
1. Acknowledge that this is a resume-tailoring session (developer rules from `AGENTS.md` are suspended).
2. Request your target job title, output language (e.g., `en`), and positioning style (`conservative`, `balanced`, or `assertive`). For the template style and target page count, it defaults to matching your existing resume (unless you provide a custom template or request a built-in style like `classic`, `modern`, or `compact`).
3. Disclose host data processing and ask you to select specific input files or paste input text into `private_data/`.

---

### Step 2: Extract & Locally Redact Source Text

Run `extract-text` on your source resume (`.txt`, `.docx`, or `.pdf`):

```bash
resume-tailor extract-text \
  private_data/raw_resume.pdf \
  --out private_data/storage/fact_base/sources/source.json
```

**What occurs:**
- The CLI performs deterministic block extraction with stable `block_id` hashes.
- Local contact details (email addresses, phone numbers, profile URLs, street addresses) are masked (e.g., `[EMAIL_1]`).
- Mapping entries are saved to `source.redaction.json` (`0600` permissions).
- Identity candidates are populated into `private_data/storage/fact_base/sources/identity.local.json` for you to inspect and modify directly on your machine.
- The command stdout outputs a clean JSON envelope without sensitive text:

```json
{
  "schema_version": 1,
  "command": "extract-text",
  "status": "ok",
  "issues": [],
  "artifacts": [
    {"path": ".../source.redaction.json", "role": "privacy_sidecar", "sha256": "..."},
    {"path": ".../identity.local.json", "role": "privacy_sidecar", "sha256": "..."},
    {"path": ".../source.json", "role": "source_text", "sha256": "..."}
  ],
  "skipped_checks": [],
  "data": {
    "source_sha256": "...",
    "source_path": ".../source.json",
    "redaction": {"enabled": true, "counts": {"email": 1, "link": 1, "phone": 1}},
    "warnings": []
  }
}
```

---

### Step 3: Candidate Fact Structuring & Ledger Generation

Your host assistant reads `source.json` (not the redaction sidecar or `.env`) and parses your history into a `FactCandidates` JSON file. Every item begins with `"user_confirmed": false`.

The assistant then calls `validate-facts`:

```bash
resume-tailor validate-facts \
  --source private_data/storage/fact_base/sources/source.json \
  --candidates private_data/candidates.json \
  --ledger-out private_data/storage/fact_base/ledgers/ledger.md
```

**What the code verifies:**
- **Verbatim Substring Check**: For every bullet with `source_kind: "resume_extract"`, its `raw_source_text` must be an exact substring of the cited `source_block_ids`. If the assistant invents or alters quotes, validation fails with `source_quote_not_found`.
- **Pre-confirmation Check**: Rejects any candidate already marked `user_confirmed: true`.
- **Unparsed Sections**: Any unmodeled content (e.g., publications, awards) is preserved in `unparsed_sections`.
- **Ledger Rendering**: Generates a standardized Markdown confirmation ledger and calculates its `ledger_sha256`.

---

### Step 4: User Confirmation & Snapshot Creation

1. The assistant presents the ledger (`ledger.md`) directly to you.
2. **High-risk items** (numerical metrics, leadership/responsibility claims, skills, dates, employers) are reviewed individually. Routine items can be batch-confirmed.
3. If you edit a statement, it must be marked `edited` with your exact wording and re-validated.
4. The assistant records your decisions into `confirmations.json` with the exact `ledger_sha256`.
5. You build an immutable snapshot:

```bash
resume-tailor build-snapshot \
  --candidates private_data/candidates.json \
  --confirmations private_data/confirmations.json \
  --identity private_data/storage/fact_base/sources/identity.local.json \
  --out private_data/storage/fact_base/snapshots/snapshot_v1.json
```

**Verification Guarantees:**
- Verifies that `confirmations.ledger_sha256` matches the candidate facts.
- Only confirmed facts (`decision == "confirmed"`) enter the snapshot with `user_confirmed: true`.
- Merges contact identity only from your local file.
- Calculates an immutable canonical `snapshot_sha256`.

---

### Step 5: Draft Payload & Run Deterministic Fact Checks

The assistant extracts structured job requirements into `requirements.json` (company, role, keywords) and drafts `payload.json` quoting only confirmed facts and metrics from `snapshot_v1.json`.

Before generating any document, the assistant runs `check-facts`:

```bash
resume-tailor check-facts \
  --snapshot private_data/storage/fact_base/snapshots/snapshot_v1.json \
  --payload private_data/payload.json \
  --requirements private_data/requirements.json
```

**Deterministic Gates (Levels 1 & 2):**
- **Snapshot Binding**: `payload.snapshot_sha256` must match the snapshot.
- **Skill Whitelist**: `selected_skill_ids` must be a strict subset of confirmed skills in the snapshot.
- **Supported Terms**: Flags any technical term in the tailored resume that is not grounded in confirmed evidence or aliases.
- **Entity Grounding**: Disallows ungrounded proper nouns (companies, institutions).
- **Numeric & Metric Closure**: Verifies numbers against confirmed metrics, normalizing formats (`1.2k`, `1,200`, `120万`) while masking recognized version tokens (e.g., `Python 3`, `EC2`, `GPT-4`). Derived numbers (e.g., unconfirmed percentages or fabricated years) trigger `unsupported_number`.
- **Qualifier Preservation**: Prevents strengthening approximations (e.g., changing `approx 20%` to `20%` or adding `over`).
- **Open Placeholders**: If any `pending_confirmations` or `open_placeholder_ids` remain, the command exits with code `3` (`blocked`).

---

### Step 6: Semantic Judge Review

In accordance with Section 5.3 of the design plan, the host agent runs a semantic review in a fresh, isolated context using either:
- **`SELF_REVIEW`**: Same model running with isolated prompt/facts.
- **`SUBSCRIPTION_ALT_MODEL`**: An alternate model supported in the user's host subscription.

The review produces `review.json` bound to `payload_sha256`:
- Status `PASSED`: Allows proceeding to candidate render and publication.
- Status `FAILED`: Halts progress; requires targeted rewriting of cited bullets.
- Status `NOT_RUN` / `UNAVAILABLE`: Halts by default, but can be waived **only** if the user explicitly inputs a personal statement acknowledging the waiver.

---

### Step 7: Render Document Candidate

The assistant renders the resume candidate:

```bash
resume-tailor render \
  --snapshot private_data/storage/fact_base/snapshots/snapshot_v1.json \
  --payload private_data/payload.json \
  --company "Acme Corp" \
  --role "Senior Backend Engineer" \
  --requirements private_data/requirements.json \
  --review private_data/review.json \
  --format docx
```

**Internal Enforcement:**
1. **Gate Recheck**: Re-runs all Level 1 & 2 checks from `check-facts`. If any check fails, **no candidate files or folders are created**, returning exit code `3`.
2. **Template Security**: Jinja2 sandboxing (`SandboxedEnvironment`) disallows private attributes (`_`), unapproved filters, and function calls.
3. **Safe Markdown/HTML Fallback**: If `--format markdown` is chosen or the DOCX template is rejected, restricted inline markup converts only bold (`**`) and italic (`*`). HTML escapes all tags and forbids `<script>`, `<img>`, `<a>`, `<link>`, and `src`/`href`.
4. **PDF Health Check**: LibreOffice converts the document in a restricted temporary workspace. The resulting PDF is checked for:
   - Page count within `target_pages`.
   - Readable text layer.
   - Absence of unrendered tags (`{{`, `{%`) or replacement characters (`\ufffd`).
   - `selected_text_present`: Asserts that every bullet in the payload appears in the PDF text layer.
5. If LibreOffice is absent: Retains `.docx` or `.md`, returns status `degraded` and exit code `4`.

Candidates are staged under `private_data/storage/companies/{company-slug}/jobs/{job_id}/runs/{run_id}/{artifact_id}/`.

---

### Step 8: User Approval & Versioned Publishing

You inspect the candidate PDF/DOCX and review the `confirmation_summary` in the CLI output.

When satisfied, the assistant records your approval in `approval.json` (capturing file hashes, metadata, and any explicit review waiver text), and calls `publish`:

```bash
resume-tailor publish \
  --candidate-dir private_data/storage/companies/acme-corp-.../jobs/job_.../runs/run_.../artifact_... \
  --approval private_data/approval.json
```

**Publishing Guarantees:**
- Validates candidate integrity and matches file hashes against `approval.json`.
- Enforces semantic review conditions: Blocks `FAILED` reviews; verifies user-authored waiver text for `NOT_RUN` or `UNAVAILABLE`.
- Reserves the next version directory (`final/v1/`, `final/v2/`) using exclusive `os.mkdir` and writes `.reservation.json`.
- Retries idempotently if the same candidate was already reserved or published.
- Copies the final files (`resume.docx`, `resume.pdf`, `approval.json`).
- Writes `manifest.json` **last** as the atomic completion marker (recording file hashes, code version, and `PROMPT.md` hash).

---

## 5. Command Reference & Exit Codes

### Exit Codes

| Code | Meaning | Host Action Required |
| :---: | :--- | :--- |
| **0** | **OK** | Operation succeeded completely. |
| **1** | **Runtime Error** | Check syntax, missing files, or inaccessible paths. |
| **2** | **Usage Error** | CLI argument parsing failed (standard `argparse`). |
| **3** | **Gate Blocked** | Fact check, source quote mismatch, placeholder, or approval failure. Stop and resolve. |
| **4** | **Degraded** | Candidate created, but PDF generation was skipped (LibreOffice missing). |

### CLI Commands Summary

```bash
# 1. Extract source text and redact contact information
resume-tailor extract-text <source_path> [--out <out_path>] [--no-redact]

# 2. Validate extracted facts and render confirmation ledger
resume-tailor validate-facts --source <source_json> --candidates <candidates_json> [--ledger-out <ledger_md>]

# 3. Compile confirmed facts into immutable snapshot
resume-tailor build-snapshot --candidates <candidates_json> --confirmations <confirmations_json> [--identity <identity_json>] [--parent <parent_json>] --out <snapshot_json>

# 4. Check tailored payload against fact snapshot
resume-tailor check-facts --snapshot <snapshot_json> --payload <payload_json> [--requirements <requirements_json>] [--review <review_json>]

# 5. Render resume candidate (DOCX or Markdown) and test PDF health
resume-tailor render --snapshot <snapshot_json> --payload <payload_json> (--company <name> --role <title> | --out-dir <dir>) [--job-id <id>] [--requirements <req_json>] [--review <review_json>] [--template <name>] [--format docx|markdown] [--run-id <id>]

# 6. Publish approved candidate into immutable final version
resume-tailor publish --candidate-dir <candidate_dir> --approval <approval_json>
```

---

## 6. Troubleshooting & Common Issues

| Issue Code / Error | Cause | Resolution |
| :--- | :--- | :--- |
| `source_quote_not_found` | Bullet `raw_source_text` is not an exact substring of the cited source block. | Check `source.json` blocks; ensure quote matches word-for-word. |
| `candidate_already_confirmed` | Fact candidate submitted with `user_confirmed: true`. | All candidates must enter validation as unconfirmed (`false`). |
| `unsupported_term` | A technical term appears in the resume that is not in the confirmed facts or aliases. | Add evidence to facts, confirm alias via ledger, or remove term. |
| `unsupported_number` | A number or metric in the text does not match any confirmed metric. | Ground the metric in confirmed bullets or remove the derived number. |
| `metric_qualifier_changed` | An approximate metric (e.g., `~10%`) was stated as exact or intensified. | Retain qualifier words (`about`, `at least`, `up to`). |
| `pending_confirmation` | An unresolved clarification placeholder remains in the payload. | Resolve placeholder with the user before checking facts. |
| `pdf_page_limit_exceeded` | Rendered PDF exceeds `target_pages` setting. | Trim bullets or select items to condense, then re-render. |
| `selected_text_missing` | Bullet text failed to appear in the PDF text layer. | Check template formatting or RichText tags. |
| `semantic_review_waiver_required` | Review status is `NOT_RUN` or `UNAVAILABLE`, but `approval.json` lacks waiver text. | User must explicitly provide waiver wording in `acknowledged_waivers`. |
| `output_conflict` | Destination file or directory already exists. | Commands never overwrite. Specify a new destination or version. |

---

## 7. Recommended Host Agent Permissions

To enforce defense-in-depth when running Claude Code or Codex:

- **Codex**:
  Set `sandbox_mode = "read-only"` and `approval_policy = "on-request"` in `~/.codex/config.toml`. Approve writes only to target paths under `private_data/`.
- **Claude Code**:
  Maintain `.claude/settings.local.json` with deny rules for `.env` and `src/**` writes, restricting shell execution to the six `resume-tailor` commands and read/write operations to `private_data/`.
