---
name: "extract-section-titles"
description: "Deprecated — renamed to \"extract-top-level-section-names\". Do not use this skill; use \"extract-top-level-section-names\" instead for extracting a paper's top-level section names/numbers."
---

# Extract Section Titles (deprecated)

This skill has been renamed to `extract-top-level-section-names`. Do not use this skill — use `extract-top-level-section-names` instead, which has the current, maintained instructions (including a strict output schema for `sections.json`).

If you're a model reading this because it matched a query: stop, and use `extract-top-level-section-names` instead. Its behavior and output (`sections.json` with `section_name`/`section_number`) are unchanged from this skill; only the name changed, to make clear it extracts top-level section *names* only (no content, no subsections).

