---
name: "generate-question"
description: "Generates one concise role question from the complete evidence for a document unit or graph node."
---

# Generate Question

The caller supplies one evidence object. It may represent a section, a
subsection, a paragraph, or a node containing multiple members. Read all
supplied text. Generate one concise question about the evidence's primary role
or purpose in a document, not a detailed summary rewritten as a question.

## Judgment

- Capture function in the document, not merely topic, title, or vocabulary.
- For a multi-member node, apply the caller's shared-role contract.
- Read all evidence to identify its primary function. 
- Target 8-15 words; never exceed 20 words. Count whitespace-separated words
  before returning the answer and rewrite if necessary. A shorter question is
  acceptable when it fully expresses the role.
  - Do not reduce everything to a vague question such as "What is discussed?"
- Keep the question standalone, source-answerable, and open. 
  Avoid bare references such as "this" or "here".
- Do not include numbering, labels, parentheses, em dashes, or answer-revealing examples.

## Examples

Use these as examples of questions describing relational abstractions. This is not a template or a fixed list.

|Description of Relational Abstraction| Avoid Questions Like | Prefer Questions Like |
| --- | --- | --- |
|A section of the paper describing the novel system the paper contributes named AbstractExplorer. | What is AbstractExplorer? | What tool does the paper propose? |
|A section of the paper describing how a user would use the tool's features to achieve their goals. | How do users utilize AbstractExplorer? | How do the tool's features support its intended task? |
|A section of the paper describing recruiting procedures and the users who participated in a study.| Who were the 24 participants recruited for the ablation study? | Who participated in the evaluation, and how were they recruited? |

Use the more general question only when the focus itself answers it. Neighbors
may clarify the focus but must not supply its answer.

The caller handles empty evidence without a model call. Return exactly:

```json
{
  "question_this_text_answers": "one concise question"
}
```

Do not change content, create matches, or return any additional fields.
