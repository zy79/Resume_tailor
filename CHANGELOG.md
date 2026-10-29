# Changelog

Notable project changes are recorded here, with the newest entries first.

## Unreleased

### Added

- Initialize the Python package with a CLI, optional FastAPI API, LangGraph workflow scaffold, and tests.
- Add separate `MAIN_LLM_*` and `JUDGE_LLM_*` environment settings, a tracked `.env.example`, and dotenv loading. Local `.env` remains ignored.
- Add `documents/` guidance for public project files and `private_data/` for personal resume and job-description data.
- Add root `AGENTS.md` project instructions and the `.agents/skills/` directory for reusable project skills.

### Changed

- Track public project files in `documents/`; keep personal resume, job-description, and generated files in Git-ignored `private_data/`.
- Move the CLI's default resume and job-description paths to Git-ignored `private_data/`.
- Clarify local-first distribution and add OpenRouter and DeepSeek endpoint scenarios to the implementation plan.
- Revise the resume-tailoring plan for a CLI-first workflow, eventual TypeScript frontend, and production reliability and observability.
- Remove the generated TypeScript/Vite frontend and use the CLI as the primary interface.
- Remove local pytest, Ruff, and Python bytecode caches while preserving the virtual environment, secrets file, and project documents.
- Prohibit AI co-author attribution in commit messages through project instructions.

### Notes

- Main and judge model provider adapters are not connected yet; the environment settings are prepared for that integration.