---
name: document-rendering
description: "Use when changing DOCX templates, docxtpl rendering, the inline-markup converter, the Markdown/HTML fallback, LibreOffice PDF conversion, page-count or document health checks, or render-related tests."
---

# Document Rendering

## When to Use
- Add or change a DOCX template (built-in or custom), template validation, or the render context.
- Change the inline-markup converter, the Markdown fallback, or LibreOffice conversion and degradation.
- Change page-count, text-extraction, or other health checks on rendered output.

## Preconditions
- Read sections 1.3 and 6.1 of `documents/resume_tailor_agent_design.md`. Inspect the current code first: the renderer, the `render` command, and the built-in template are planned for Phase 1 and may not exist yet. Do not invent commands.
- The renderer fills identity, company, role, dates, education, and project names from the snapshot bound to the payload, never from model output or live tables.

## Workflow
1. Templates are Jinja templates and therefore a code-execution surface. Render every template, built-in ones included, through `DocxTemplate.render(context, jinja_env=SandboxedEnvironment(...))` with a plain-data context (no functions, objects, or modules). The default docxtpl environment is not sandboxed.
2. Use the docxtpl tag conventions: `{{r var }}` for `RichText`, `{%p ... %}` for paragraph loops, and `{%tr ... %}` for table rows. A plain `{{ var }}` renders a `RichText` value as empty text. Word can split a tag across runs, so load every template through docxtpl in tests.
3. Validate custom templates before use: only declared variables (`get_undeclared_template_variables()`), docxtpl tags, and allow-listed filters; reject underscore attribute access and unknown tags; keep the result in the template's validation report.
4. Use the project's own inline converter, which supports only `**bold**` and `*italic*`, for both chains: `RichText` for DOCX, and for the Markdown/HTML chain escape all text first and emit only `<strong>`/`<em>`. Unmatched or unsupported markers (including literal asterisks) stay as text. Do not run model text through a general Markdown renderer, which interprets raw HTML, links, and images.
5. The Markdown/HTML chain must not contain `<img>`, `<a>`, `<link>`, `<script>`, `<style>`, or any external `src`/`href`. Run LibreOffice with its own work directory and profile and without external resource loading.
6. Keep these probes in tests: an SSTI probe template must fail without producing output; a template that uses `{{ }}` for `RichText` must be caught by the empty-bullet check; bullets containing `![x](http://...)`, `<script>`, and `[x](javascript:...)` must appear as literal text.
7. LibreOffice is optional. If `soffice` is missing, keep the `.docx` or `.md` candidate, return the degraded state (exit code 4), skip PDF-dependent checks, and never describe it as PDF success. Never install software or call `sudo`.
8. Health checks run only on an actual PDF: page count (the LibreOffice PDF is the reference; Word may paginate the DOCX differently, so say so), text layer, unrendered tags, presence of every selected bullet's text, and detectable missing glyphs. They cannot prove the absence of overlap or clipping, so a human preview stays required.
9. Character budgets are measured per template, font, and `output_language`. Without a measured value, skip the estimate and say so. Do not auto-shrink fonts or spacing.

## Validation
- Run the relevant tests with `pytest`; use synthetic data, and fakes for LibreOffice when it is not installed.
- Run `ruff check .` and `git diff --check`.
- State which checks ran, which were skipped (for example, no LibreOffice), and what still needs human visual review.
