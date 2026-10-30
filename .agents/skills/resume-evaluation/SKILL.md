---
name: resume-evaluation
description: "Use when changing resume-generation prompts, fact validation, semantic auditing, review modes or approval gates, or synthetic resume-quality regression tests and evaluation criteria."
---

# Resume Evaluation

## When to Use
- Change resume tailoring prompts, structured output contracts, source validation, metric, skill, or entity checks, or a Judge/Auditor.
- Add or update synthetic regression cases for factual consistency or job-description alignment.
- Change review modes, review statuses, or approval conditions.

## Workflow
1. Inspect the current code and tests before relying on the roadmap. If payload schemas, deterministic validators, a Judge/Auditor, or an eval command are not implemented, treat them as work to build, not existing guarantees.
2. Use synthetic fact bases and job descriptions only. Include supported facts, missing or unconfirmed facts, metric traps, unsupported skills, unsupported entities, and incorrect source references where relevant.
3. Test deterministic rules separately from semantic model judgments (sections 5.1-5.2 versus 5.3 of the design plan). Deterministic classes: the payload is bound to the snapshot hash; source IDs resolve to confirmed facts (confirmation re-checked against content hashes); selected skill IDs are a subset of the snapshot; unsupported terms (JD keywords and taxonomy minus verified skills and aliases) and unsupported entities are caught; numbers are normalized and match declared metrics including unit and qualifier; derived numbers stay blocked until the user confirms them; tokens such as S3 or GPT-4 do not cause false positives; unresolved placeholders block approval.
4. Gate claims: the deterministic injected-fault suite is a 100% CI gate for the defined fault classes only. The semantic judge is reported as a detection rate per review mode against a recorded baseline; never claim 100% interception for it and never merge modes.
5. Use the vocabulary of section 5.5 exactly: modes `SELF_REVIEW`, `SUBSCRIPTION_ALT_MODEL`, `API_JUDGE` (with `judge_independence`), and `NONE`; statuses `NOT_RUN`, `PASSED`, `FAILED`, and `UNAVAILABLE`. A review result applies only to its `payload_sha256`, and a stale result counts as `NOT_RUN`. Missing or unavailable review blocks approval unless the user explicitly waives it and the waiver is recorded. Deterministic failures can never be waived.
6. The `balanced` style uses STAR only for elements present in confirmed facts. Keep a case where a fact has only an action and the output must not gain a situation or result.
7. Keep model-generated suggestions distinct from historical user facts. If a Judge is absent or unavailable, report that honestly; do not count it as a pass or silently reuse the main model.
8. Report evaluation sample counts, denominators, skipped cases, and model usage. Treat results as evidence about the tested synthetic set, not a guarantee of zero hallucinations.
9. Use injected fake models for normal CI. Online evaluations require explicit user authorization and a cost budget. Keep datasets under `tests/evals/` and do not invent an eval CLI command before one exists.

## Validation
- Run the relevant tests with `pytest`.
- Run `ruff check .` and `git diff --check`.
