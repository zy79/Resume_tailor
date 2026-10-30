# Changelog

Notable project changes are recorded here, with the newest entries first.

## Unreleased

### Fixed

- Close review gaps in review-mode gates, source and metric checks, phone redaction, and private CLI output; make publishing resumable and same-candidate retries idempotent.
- Validate Jinja in DOCX headers and footers, restrict runtime filters and globals, and package `PROMPT.md` as a wheel resource.
- Limit README batch confirmation to ordinary facts and require individual confirmation for high-risk facts.

### Added

- Add automatic LibreOffice discovery for standard Windows and macOS installation directories, enabling headless PDF conversion without requiring manual PATH configuration.
- Add 3 popular ATS-friendly DOCX resume templates (`classic`, `modern`, `compact`) to `src/resume_tailor/templates_builtin/` and `documents/templates/`, with built-in template selection support in `render --template <name>`.
- Add comprehensive English user guide for the Phase 1 Prompt-first local workflow (`documents/prompt_route_user_guide.md`), detailing the end-to-end lifecycle, command reference, safety boundaries, and troubleshooting.
- Implement the Phase 1 Prompt-first workflow: a model-free six-command CLI, local contact redaction, deterministic fact gates, safe rendering, and approved versioned publishing.
- Add versioned `PROMPT.md` host workflow, privacy disclosure, command allowlist, stop points, and static contract tests.
- Add synthetic publishing and repository privacy guardrails; ignore local `.env.*` secrets while keeping `.env.example` trackable.
- Add `document-rendering`, `prompt-route-protocol`, and `graph-recovery` project skills for template/render safety, the stateless CLI protocol and `PROMPT.md`, and LangGraph/SQLite persistence and publishing.
- Initialize the Python package with a CLI, optional FastAPI API, LangGraph workflow scaffold, and tests.
- Add separate `MAIN_LLM_*` and `JUDGE_LLM_*` environment settings, a tracked `.env.example`, and dotenv loading. Local `.env` remains ignored.
- Add `documents/` guidance for public project files and `private_data/` for personal resume and job-description data.
- Add root `AGENTS.md` project instructions and the `.agents/skills/` directory for reusable project skills.

### Changed

- Document supported resume and job-description file formats in the README, including text-layer PDF requirements and the paste option for job descriptions.
- Update template and page-count guidance in `README.md`, `PROMPT.md`, and `documents/prompt_route_user_guide.md` so that the assistant defaults to preserving the user's existing resume layout and page count rather than restricting selection to the three built-in templates.
- Streamline the user workflow in `README.md` with a concise 4-step Quick Start showing how job seekers interact with their coding assistant without manually running CLI commands, and clarify the technical reference scope in `documents/prompt_route_user_guide.md`.
- Clarify Codex and Claude host permissions, sandbox limits, and local-versus-hosted history controls.
- Replace the interactive CLI and default personal-file paths with stateless JSON commands; make render recheck job requirements and leave no candidate when render-health checks fail.
- Update the project entry-point, data handling, dependency, and host-permission documentation for the Prompt-first Phase 1 workflow.
- Revise the design plan after review (v2.3): a six-command stateless CLI protocol with a JSON envelope, distinct exit codes, and a code-rendered confirmation ledger; payload/snapshot binding, run configuration, and complete clarification contracts; date precision that never invents months; stronger deterministic checks (unsupported terms, entity grounding, numeric normalization, derived numbers); one normative review-mode and approval-gate section; and a split between deterministic gates and semantic detection rates.
- Harden the design plan for SQLite and LangGraph (foreign-key pragma, UTC timestamps, `BEGIN IMMEDIATE`, separate checkpoint database, ID-only graph state), publishing without overwrite, sandboxed DOCX templates, a restricted inline-markup converter, OpenRouter `data_collection`, and Prompt-route redaction, host guardrails, and a `PROMPT.md` specification.
- Document the migration from the current scaffold in the design plan, fix the stale `documents/` ignore statement, correct phase placement, and make the plan's Python snippets pass the project Ruff configuration.
- Update the `provider-integration`, `privacy-and-jd-evals`, and `resume-evaluation` skills to match the revised plan.
- Update the design plan with headless CLI contracts, SQLite for single-user persistence phases, and Markdown/PDF rendering fallback behavior.
- Allow a subscription-supported alternate Judge model in the Prompt route; otherwise use same-model self-review without requiring an API key.
- Rework the design plan around a subscription-backed, API-key-free Prompt workflow; retain the TypeScript UI for full application tracking and cross-job interview summaries.
- Add modern Python conventions and initial provider, privacy/JD, and resume-evaluation skills.

- Plan pasted-text and guarded URL-based JD import with bounded extraction, preview, and user confirmation.
- Specify company- and job-specific artifact storage, and plan manual application tracking with dated interview records and source-linked question summaries.
- Track public project files in `documents/`; keep personal resume, job-description, and generated files in Git-ignored `private_data/`.
- Move the CLI's default resume and job-description paths to Git-ignored `private_data/`.
- Clarify local-first distribution and add OpenRouter and DeepSeek endpoint scenarios to the implementation plan.
- Revise the resume-tailoring plan for a CLI-first workflow, eventual TypeScript frontend, and production reliability and observability.
- Remove the generated TypeScript/Vite frontend and use the CLI as the primary interface.
- Remove local pytest, Ruff, and Python bytecode caches while preserving the virtual environment, secrets file, and project documents.
- Prohibit AI co-author attribution in commit messages through project instructions.

### Notes

- Main and judge model provider adapters are not connected yet; the environment settings are prepared for that integration.