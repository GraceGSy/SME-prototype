---
name: "generate-question"
description: "Generates one concise role question from the complete evidence for a document unit or graph node."
---

# Generate Question

The caller supplies one evidence object. It may represent a section, a
subsection, a paragraph, or a node containing multiple members. Read all
supplied text. Generate one concise question that the complete evidence answers.

## Judgment

- Capture function in the document, not merely topic, title, or vocabulary.
- For academic text, ask what job the evidence does in the paper's argument.
- For narrative text, ask what uncertainty about the case, characters,
  evidence, investigation, confrontation, or resolution it addresses.
- For a multi-member node, find one question honestly answered by every member.
- Cover all supplied evidence without listing or revealing its answers.
- Keep the question open, standalone, and preferably under 20 words.
- Do not include section numbers, parentheses, em dashes, or answer-revealing
  examples.

The caller handles empty evidence without a model call. Return exactly:

```json
{
  "question_this_text_answers": "one concise question"
}
```

Do not change content, create matches, or return any additional fields.
