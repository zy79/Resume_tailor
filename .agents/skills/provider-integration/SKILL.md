---
name: provider-integration
description: "Use when integrating or changing MAIN_LLM or JUDGE_LLM providers, OpenRouter or DeepSeek endpoints, structured responses, provider configuration, retries, or provider tests."
---

# Provider Integration

## When to Use
- Add or modify a model provider or adapter.
- Change `MAIN_LLM_*` or `JUDGE_LLM_*` configuration, request parameters, or structured-output handling.
- Debug provider failures, retry behavior, or role isolation.

## Preconditions
- Inspect the current implementation first. The LangGraph agent currently accepts an injected async callable; environment variables alone do not mean a provider is implemented.
- Read `AGENTS.md`, `.env.example`, and sections 2.1, 2.1.1, 5.5 and 7.2 of `documents/resume_tailor_agent_design.md` before changing configuration.
- Providers belong to the application API route only (planned Phase 3). The Prompt route never calls a provider or reads `.env`; keep provider and `python-dotenv` imports out of the Prompt-route CLI command modules.

## Workflow
1. Keep generator and judge provider, model, base URL, and credentials independently configurable. Never silently fall back from judge to main. Using the same service or model is allowed only when explicitly configured, and then record `judge_independence` as `SAME_PROVIDER_DIFFERENT_MODEL` or `SAME_MODEL` instead of implying independence.
2. Keep vendor-specific request handling in provider adapters. Graph nodes depend on injected async callables or the `ModelProvider` protocol, not vendor SDKs.
3. Follow the planned interface: `generate_structured` returns `StructuredResult[T]` (the parsed model plus `ModelCallMeta`: role, provider, model, upstream or `None` when unknown, finish reason, token counts, attempt, request id) and raises typed `ProviderError` subclasses (config, unavailable, refusal, truncated, schema) that map to the retry classes in section 7.2. Never return success-shaped defaults.
4. Validate provider responses at the boundary with the relevant Pydantic schema. Model capabilities differ: only send parameters supported by the selected adapter, and report unsupported formats, refusals, empty responses, truncation, and malformed output explicitly. DeepSeek `json_object` mode does not guarantee a schema.
5. OpenRouter requests send `provider.data_collection = "deny"` by default (the service default is `allow`), add `zdr` only when the user requires zero retention, use `require_parameters` for structured output, and honour the user's `only` and `allow_fallbacks`. Never relax these automatically when no upstream is available; fail with an explicit error and record the actual upstream, or "unknown".
6. Make transport and model calls replaceable with deterministic fakes. Test endpoint and parameter selection (including routing parameters), role isolation, schema errors, timeouts, retries counted in usage, and the absence of silent fallback without making live requests.
7. Declare runtime dependencies in `pyproject.toml` (the plan puts provider dependencies in an optional `api` group once the dependency split exists); update `.env.example` when configuration variables change. Never include credentials in fixtures, logs, or error text.

## Validation
- Run the relevant tests with `pytest`; use fakes by default.
- Run `ruff check .` and `git diff --check`.
- Run online provider tests only with explicit user authorization and a stated cost limit.
