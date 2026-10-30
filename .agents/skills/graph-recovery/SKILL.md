---
name: graph-recovery
description: "Use when changing LangGraph workflow state, checkpointing, interrupt/resume, idempotent side effects, SQLite persistence and migrations, version allocation, or artifact publishing and reconciliation."
---

# Graph Recovery and Persistence

## When to Use
- Change the LangGraph state, nodes, checkpointer, `interrupt()`/resume handling, or retry behavior.
- Change SQLite or Alembic setup, ORM models, version allocation, publishing, or startup reconciliation.

## Preconditions
- Read sections 3.2.2, 4.3, 7.1, 7.2, and 7.3 of `documents/resume_tailor_agent_design.md`. Persistence, checkpointing, and publishing are planned for Phase 2; inspect the current code and do not claim recovery exists until it is implemented and tested. The current `agent.py` state holds full resume and JD text and must not be connected to a persistent checkpointer as is.

## Workflow
1. Keep graph state a `TypedDict` of IDs, hashes, enums, and counters. Documents, payloads, prompts, and model responses are loaded by ID inside nodes. The checkpointer serialises the whole state in plaintext at every step.
2. Use a separate `checkpoints.sqlite3` for `AsyncSqliteSaver`. If it ever shares a file with the Alembic-managed schema, `env.py` must exclude `checkpoints` and `writes` with `include_object`; autogenerate otherwise proposes dropping them. Test that no migration drops them.
3. Resume replays the interrupted node from its start: do no non-idempotent side effects before `interrupt()`, key side effects by `run_id`/`artifact_id`, and never assume an external model call ran exactly once.
4. SQLite connection setup applies per connection, for the sync engine and for `aiosqlite` through `sync_engine`: `PRAGMA foreign_keys=ON` (it is off by default), WAL, a busy timeout, and `BEGIN IMMEDIATE` for write transactions. SQLite has no row locks and SQLAlchemy emits no `FOR UPDATE` there, so treat `UNIQUE(job_id, version_num)` as the last line of defense and retry or return the existing record on conflict.
5. Store timestamps as UTC through a `UtcDateTime` type: `DateTime(timezone=True)` returns naive values on SQLite. Declare `sqlalchemy[asyncio]` (it brings `greenlet`) when using the async engine.
6. Run states belong to the run (`PENDING` through `COMPLETED`, `FAILED`, or `CANCELLED`); approval and publish states belong to the artifact. A completed run is never reopened: refining a published version starts a new run with `parent_run_id`.
7. Publishing: allocate the version in a `BEGIN IMMEDIATE` transaction, reserve `final/vN/` with an exclusive `mkdir` plus a marker file, write temp files then `os.replace`, verify hashes, write `manifest.json` last, and only then mark `PUBLISHED`. Directory `rename` does not protect against overwriting (POSIX replaces an empty target). Reconcile `PUBLISHING` on startup per section 7.1 item 5 and never overwrite a mismatching directory.
8. Idempotency: the same key and request hash returns the original result; the same key with a different hash is a conflict. Keep question versions, idempotency keys, approvals, and audit events in their tables (section 4.3.5).
9. Tests to keep: process kill at every DB and file boundary, concurrent publish of one job, duplicate clarification and approval, a dangling-FK insert failing, a UTC round trip, an Alembic autogenerate that does not drop checkpoint tables, and a checkpoint leakage probe.

## Validation
- Run the relevant tests with `pytest`; use fake nodes and fake providers.
- Run `ruff check .` and `git diff --check`.
