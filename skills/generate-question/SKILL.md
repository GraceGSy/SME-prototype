---
name: "generate-question"
description: "Generates one concise role question from the complete evidence for a document unit or graph node."
---

# Generate Question

The caller supplies one evidence object. It may represent a section, a
subsection, a paragraph, or a node containing multiple members. Read all
supplied text. Generate one concise question about the evidence's primary role
or purpose, not a detailed summary rewritten as a question.

## Judgment

- Capture function in the document, not merely topic, title, or vocabulary.
- For academic text, ask what job the evidence does in the paper's argument.
- For narrative text, ask what uncertainty about the case, characters,
  evidence, investigation, confrontation, or resolution it addresses.
- For a multi-member node, find one shared-purpose question honestly answered
  by every member. Do not join different purposes into a list to make them fit.
- Read all evidence to identify its primary function. The question need not
  enumerate every fact, feature, qualification, or secondary purpose.
- Target 8-15 words; never exceed 20 words. Count whitespace-separated words
  before returning the answer and rewrite if necessary. A shorter question is
  acceptable when it fully expresses the role.
- Replace names of papers, tools, people, datasets, and venues with functional
  descriptions such as "the proposed tool", "the evaluation", or "the witness".
  Omit incidental counts, dates, implementation details, and feature lists.
- Preserve the relation that makes the role meaningful: motivation, proposed
  approach, mechanism, procedure, evidence, and limitation are not interchangeable.
  Do not reduce everything to a vague question such as "What is discussed?"
- Keep the question standalone, source-answerable, and open. Do not assert that
  a tool succeeded, a claim was proved, or a suspect was guilty unless warranted.
- Do not include section numbers, parentheses, em dashes, or answer-revealing
  examples.

## Examples

Use these as illustrations of abstraction, not a fixed taxonomy or templates
to force onto unrelated evidence.

| Avoid | Prefer |
| --- | --- |
| What is AbstractExplorer? | What tool does the paper propose? |
| How does AbstractExplorer combine highlighting, ordering, and alignment? | How do the tool's features support its intended task? |
| Who were the 24 participants recruited for the ablation study? | Who participated in the evaluation, and how were they recruited? |
| How could AbstractExplorer extend beyond CHI abstracts? | What limits the tool's generalizability? |
| What did Holmes learn from the muddy boots? | How does the physical evidence constrain the explanation of events? |

Use the more general question only when the focus itself answers it. Neighbors
may clarify the focus but must not supply its answer. For groups, check each
member against the same question; do not manufacture a shared role merely to
increase the number of matches.

The caller handles empty evidence without a model call. Return exactly:

```json
{
  "question_this_text_answers": "one concise question"
}
```

Do not change content, create matches, or return any additional fields.
