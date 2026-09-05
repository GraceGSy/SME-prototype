# One-shot corpus preparation

`python -m helpers.prepare_content_corpus MANIFEST OUTPUT [--whole-section]`
creates a content-only or whole-story derivative from valid canonical inputs.
Keep the source corpus unchanged. This helper is not imported by either runtime
pipeline, and does not accept or repair alternate document schemas.
