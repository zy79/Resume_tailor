# ATS-Friendly Resume Templates

This directory provides popular, industry-tested, single-column **ATS-compliant (Applicant Tracking System)** `.docx` resume templates for the `resume-tailor` rendering pipeline.

All templates are engineered to comply with the docxtpl sandboxed Jinja specification, using `{{r variable }}` for RichText inline formatting, standard paragraph loops (`{%p for ... %}`), and single-column machine-readable hierarchies.

---

## 1. Available Templates

| Template ID | Name & Visual Style | Primary Font | Layout & Spacing | Best Suited For |
| :--- | :--- | :--- | :--- | :--- |
| `classic` | **Harvard / Traditional Chronological** | Times New Roman | Centered header, 1.0-inch margins, subtle black bottom-border section dividers | Corporate, Finance, Law, Operations, Academic |
| `modern` | **Clean Tech / Silicon Valley** | Arial | Left-aligned header, 0.75-inch margins, slate headers with accent borders | Software Engineering, Data Science, Product, Startups |
| `compact` | **Executive / High-Density Minimalist** | Calibri | Compact header, 0.65-inch margins, high data density for 1-page fit | Senior Engineers, Tech Leads, Multi-role Professionals |
| `default` | **Standard Minimalist** | Calibri | Standard single-column baseline | Clean baseline for any role |

---

## 2. Template Style Details

### `classic` (Harvard / Chronological Style)
- **Design Philosophy**: Based on the gold-standard resume guidelines from top university career centers (e.g., Harvard Mignone Center for Career Success).
- **Typography**: Times New Roman (18pt bold centered name, 10pt contact line, 11pt bold uppercase headings with thin bottom borders, 10pt body text).
- **Structure**:
  1. Centered Contact Header
  2. Professional Summary
  3. Technical Skills
  4. Professional Experience
  5. Projects
  6. Education

### `modern` (Clean Tech Style)
- **Design Philosophy**: Tailored for contemporary engineering and technology hiring pipelines (Google, Meta, tech startups).
- **Typography**: Arial sans-serif (20pt dark slate name, 10.5pt navy headings with royal-blue border accents, 9.5pt body text).
- **Structure**:
  1. Left-aligned Modern Header
  2. Summary Statement
  3. Technical Skills (prioritized near the top for quick recruiter scanning)
  4. Experience
  5. Projects
  6. Education

### `compact` (Executive High-Density Style)
- **Design Philosophy**: Built specifically for dense career histories where fitting extensive accomplishments onto a single page without truncation or overflow is essential.
- **Typography**: Calibri (16pt bold name, 10pt bold headings, 9pt body text, tight paragraph and list spacing).
- **Structure**:
  1. Streamlined Contact Header
  2. Executive Summary
  3. Core Competencies & Technical Skills
  4. Professional Experience
  5. Projects & Initiatives
  6. Education & Credentials

---

## 3. How to Use with the CLI

Pass the template name using the `--template` flag with `resume-tailor render`:

```bash
# Render with the Harvard classic style
resume-tailor render \
  --snapshot private_data/storage/fact_base/snapshots/snapshot.json \
  --payload private_data/payload.json \
  --company "Acme Corp" \
  --role "Software Engineer" \
  --template classic \
  --format docx

# Render with the modern tech style
resume-tailor render \
  --snapshot private_data/storage/fact_base/snapshots/snapshot.json \
  --payload private_data/payload.json \
  --company "Acme Corp" \
  --role "Software Engineer" \
  --template modern \
  --format docx

# Render with the compact executive style
resume-tailor render \
  --snapshot private_data/storage/fact_base/snapshots/snapshot.json \
  --payload private_data/payload.json \
  --company "Acme Corp" \
  --role "Software Engineer" \
  --template compact \
  --format docx
```

---

## 4. ATS Formatting Guarantees

Every template in this collection complies with the strict constraints required by automated applicant screening systems (Workday, Greenhouse, Lever, iCIMS):

1. **Strict Single-Column Layout**: No multi-column splits, sidebars, or floating text frames that scramble reading order.
2. **No Word Tables or Text Boxes**: Content flows naturally line-by-line in native Word paragraphs.
3. **Universally Available Safe Fonts**: Uses system fonts pre-installed on Windows, macOS, and Linux (Times New Roman, Arial, Calibri) to prevent font-substitution layout shifts.
4. **docxtpl Tag Security**: Every dynamic element is verified by AST inspection to disallow arbitrary code execution, private attribute access (`_`), and unregistered filters.
