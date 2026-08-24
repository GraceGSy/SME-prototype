# Approximate prompts (adjustments to language are untested)

## Original section-section mapping pre-questions that set up the conversation context
Can you tell me the top-level section titles of abstractexplorer.pdf? -- first skill

Can you tell me the top-level section titles of corpusstudio.pdf?

## Section-section mapping, with questions

### Original wording
Can you iterate through the section titles of AbstractExplorer and suggest the closest corresponding section of CorpusStudio, based on section title and content as found in abstractexplorer.pdf and corpusstudio.pdf?

Can you iterate through the section titles of CorpusStudio and suggest the closest corresponding section of AbstractExplorer, based on section title and content as found in corpusstudio.pdf and abstractexplorer.pdf?

### Revised wording
second skill: add questions to extracted sections

Can you iterate through the section titles of AbstractExplorer and suggest the closest corresponding section of CorpusStudio, based on section title and content as found in abstractexplorer.pdf and corpusstudio.pdf? If a section maps to multiple sections in the other paper, create separate entries, one for each of the multiple sections rather than naming all of them in a single correspondence relationship with the section in the other paper. Output it as a JSON with "abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", and "question_the_sections_both_answer" as the fields for each pair of corresponding sections named p1-p2-section-mapping-try2.json

---
Can you create a new skill called directional-section-mapping-with-questions that 

iterates through the section titles of the first paper (as captured in sections-with-questions.json for that paper) and suggests the closest corresponding section of the second paper (as captured in the sections-with-questions.json for that paper), primarily based on the question that the section answers section title and content as found in abstractexplorer.pdf and corpusstudio.pdf? If a section maps to multiple sections in the other paper, create separate entries, one for each of the multiple sections rather than naming all of them in a single correspondence relationship with the section in the other paper. Output it as a JSON with "abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", and "question_the_sections_both_answer" as the fields for each pair of corresponding sections

---

Can you iterate through the section titles of CorpusStudio and suggest the closest corresponding section of AbstractExplorer, based on section title and content as found in corpusstudio.pdf and abstractexplorer.pdf? If a section maps to multiple sections in the other paper, create separate entries, one for each of the multiple sections rather than naming all of them in a single correspondence relationship with the section in the other paper. Output it as a JSON with "abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", and "question_the_sections_both_answer" as the fields for each pair of corresponding sections named p2-p1-section-mapping-try2.json

Possibly necessary pre-amble for the next instruction: Do not use the previously composed script; do not use a script at all. 

Look at the section matches in p1-p2-section-mapping-try2.json and check whether the same section match is found in p2-p1-section-mapping-try2.json; output a JSON of just those bidirectional matches called p1-p2-common-section-structure.json. Include the following fields: "abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", "question_the_sections_both_answer". 

What section pairings in p1-p2-section-mapping-try2.json are not present in p1-p2-common-section-structure.json? Add them to a new JSON with the following fields:
"abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", "question_the_sections_both_answer"
Save as p1-p2-alignable-section-diffs.json.

What section pairings in p2-p1-section-mapping-try2.json are not present in p1-p2-common-section-structure.json? Add them to a new JSON with the following fields:
"abstractexplorer_section_name", "corpusstudio_section_name", "abstractexplorer_section_number", "corpusstudio_section_number", "basis", "question_the_sections_both_answer"
Save as p2-p1-alignable-section-diffs.json.

Iterate through all the pairings in p1-p2-alignable-section-diffs.json and p2-p1-alignable-section-diffs.json and sort them into two new JSON files: p1p2-non-alignable-section-diffs.json for pairings where there is a 'null' or similar empty value instead of a section name for one of the papers and p1p2-alignable-section-diffs.json for all the remaining pairings that name a section/subsection in both papers.

## Paragraph mapping within a section (Intros in this case) that are mapped to each other

### Extract paragraphs within each paper's introductions (which were mapped to each other) --- turn into a skill that takes as an argument a paper and a section title
Can you break the introduction of abstractexplorer.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as intro-p1-paragraphs.json]

Can you break the introduction of corpusstudio.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as intro-p2-paragraphs.json]

(could be combined with next step of question generation) --- add to skill above

### Describe each paragraph within each paper's introductions as the question it answers 
For each paragraph in the Introduction section of abstractexplorer.pdf as captured in intro-p1-paragraphs.json, can you tell me what question it answers, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as intro-p1-questions.json]

For each paragraph in the Introduction section of corpusstudio.pdf as captured in intro-p2-paragraphs.json, can you tell me what question it answers, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as intro-p2-questions.json]

### Generate paragraph-paragraph mappings
Can you iterate through the paragraphs in abstractexplorer.pdf as defined in intro-p1-paragraphs.json and described in the question_answered field of intro-p1-questions.json and suggest the closest corresponding paragraph in corpusstudio.pdf as defined in intro-p2-paragraphs.json and as described in the question_answered field of intro-p2-questions.json, and output as a JSON?
[saved as p1-p2-intro-paragraph-mapping.json]

(could be combined with next step)

### Generate questions per pair of mapped paragraphs
For each paragraph mapped to each other as described in p1-p2-intro-paragraph-mapping.json, look up the respective paragraphs by id in intro-p1-paragraphs.json and intro-p2-paragraphs.json and output a question that both paragraphs answer. Output a new JSON that has the abstractexplorer paragraph id, the corpusstudio paragraph id, and the question they both answer.
[saved as p1-p2-intro-paragraph-questions.json]

## Generalizing to next section...
In the second pair of sections in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping.json, can you break the section of abstractexplorer.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as p1-s2-paragraphs.json]

In the second pair of sections in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping.json, can you break the section of corpusstudio.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as p2-s2-paragraphs.json]

For each paragraph in p1-s2-paragraphs.json, can you tell me what question it answers within the context of abstractexplorer.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as p1-s2-questions.json]

For each paragraph in p2-s2-paragraphs.json, can you tell me what question it answers within the context of corpusstudio.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as p2-s2-questions.json]

Can you iterate through the paragraphs in abstractexplorer.pdf as defined in p1-s2-paragraphs.json and described in the question_answered field of p1-s2-questions.json and suggest the closest corresponding paragraph in corpusstudio.pdf as defined in p2-s2-paragraphs.json and as described in the question_answered field of p2-s2-questions.json, and output as a JSON?
[saved as p1-p2-s2-paragraph-mapping.json]

For each paragraph mapped to each other as described in p1-p2-s2-paragraph-mapping.json, look up the respective paragraphs by id in p1-s2-paragraphs.json and p2-s2-paragraphs.json and output a question that both paragraphs answer. Output a new JSON that has the abstractexplorer paragraph id, the corpusstudio paragraph id, and the question they both answer.
[saved as p1-p2-s2-paragraph-questions.json]

## Programmatic enhancement
Run iterate_section_mapping.py on p1-p2-section-mapping.json and output p1-p2-section-mapping-enumerated.json

## Generalizing to next section and collapsing questions after mapping paragraphs to each other

In the pair of sections (the only one with the "enumerate" value of 2) in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping-enumerated.json, can you break the section of abstractexplorer.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as p1-s3-paragraphs.json]

In the pair of sections (the only one with the "enumerate" value of 2) in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping-enumerated.json, can you break the section of corpusstudio.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format?
[saved as p2-s3-paragraphs.json]

For each paragraph in p1-s3-paragraphs.json, can you tell me what question it answers within the context of abstractexplorer.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as p1-s3-questions.json]

For each paragraph in p2-s3-paragraphs.json, can you tell me what question it answers within the context of corpusstudio.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field?
[saved as p2-s3-questions.json]

Can you iterate through the paragraphs in abstractexplorer.pdf as defined in p1-s3-paragraphs.json and described in the question_answered field of p1-s3-questions.json and suggest the closest corresponding paragraph in corpusstudio.pdf as defined in p2-s3-paragraphs.json and as described in the question_answered field of p2-s3-questions.json, as well as a question that both paragraphs answer? Output as a JSON.
[saved as p1-p2-s3-paragraph-mapping.json]

## Generalizing to next section, saving automatically rather than manually

In the pair of sections (the only one with the "enumerate" value of 3) in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping-enumerated.json, can you break the section of abstractexplorer.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format saved as p1-s4-paragraphs.json?

In the pair of sections (the only one with the "enumerate" value of 3) in abstractexplorer.pdf and corpusstudio.pdf, respectively, that are mapped to each other in p1-p2-section-mapping-enumerated.json, can you break the section of corpusstudio.pdf into paragraphs and output a list of each paragraph's content with a numerical identifier, in JSON format saved as p2-s4-paragraphs.json?

For each paragraph in p1-s4-paragraphs.json, can you tell me what question it answers within the context of abstractexplorer.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field, and save as p1-s4-questions.json?

For each paragraph in p2-s4-paragraphs.json, can you tell me what question it answers within the context of corpusstudio.pdf, and output all those questions with their respective paragraph id as a JSON with a paragraph id and question_answered field and save as p2-s4-questions.json?

Can you iterate through the paragraphs in abstractexplorer.pdf as defined in p1-s4-paragraphs.json and described in the question_answered field of p1-s4-questions.json and suggest the closest corresponding paragraph in corpusstudio.pdf as defined in p2-s4-paragraphs.json and as described in the question_answered field of p2-s4-questions.json? For each pair of corresponding paragraphs, include the question that both paragraphs answer. Output as a JSON and save as p1-p2-s4-paragraph-questions.json.

### Claude warning
Saved p1-p2-s4-paragraph-mapping.json — all 26 AbstractExplorer paragraphs mapped to their closest CorpusStudio counterpart, each with a shared question.

Worth flagging: this section has real structural asymmetry. AbstractExplorer devotes 6 detailed paragraphs to its implementation pipeline (22–26), while CorpusStudio's Implementation Details is just 2 paragraphs (27–28) — so those get reused repeatedly as the closest available anchor. Similarly, CorpusStudio's document/sentence-level mechanisms (section title clustering vs. spatial retrieval) don't map one-to-one onto AbstractExplorer's aspects/roles/structure-groups scheme, so some pairings (e.g., AE4↔CS18, AE15↔CS20) are functional analogies rather than tight content matches.

### Reverse base and target
Can you iterate through the paragraphs in corpusstudio.pdf as defined in p2-s4-paragraphs.json and described in the question_answered field of p2-s4-questions.json and suggest the closest corresponding paragraph in abstractexplorer.pdf as defined in p1-s4-paragraphs.json and as described in the question_answered field of p1-s4-questions.json? For each pair of corresponding paragraphs, include the question that both paragraphs answer. Output as a JSON and save as p2-p1-s4-paragraph-questions.json.

### Claude warning
Saved p2-p1-s4-paragraph-questions.json — all 28 CorpusStudio paragraphs mapped to their closest AbstractExplorer counterpart (independently derived, not just the inverse of the earlier AE→CS mapping), each with a shared question.

A few notable differences from the earlier direction: since CorpusStudio has more, finer-grained paragraphs in this section (28 vs. 26), several AbstractExplorer paragraphs now get reused as the closest anchor for multiple CorpusStudio paragraphs — e.g., AE16 (sentence bookmarking) anchors three CorpusStudio paragraphs (6, 23, 26) that separately cover bookmarking, annotation, and anti-plagiarism design, and AE1/AE3/AE6 each get reused once. This asymmetry mirrors the same underlying imbalance flagged in the forward mapping.

### Find bidirection, alignable, and non-alignable paragraph pairs
Look at the section matches in p1-p2-s4-paragraph-questions.json and check whether the same section match is found in p2-p1-s4-paragraph-questions.json; output a JSON of just those bidirectional matches called p1-p2-common-s4-structure.json. Include "question_the_paragraphs_both_answer" as a field too.

What section pairings in p1-p2-s4-paragraph-questions.json are not present in p1-p2-common-s4-structure.json? Add them to a new JSON and save as p1-p2-alignable-s4-diffs.json.

What section pairings in p2-p1-s4-paragraph-questions.json are not present in p1-p2-common-s4-structure.json? Add them to a new JSON and save as p2-p1-alignable-s4-diffs.json.

Iterate through all the pairings in p1-p2-alignable-s4-diffs.json and p2-p1-alignable-s4-diffs.json and sort them into two new JSON files: p1p2-non-alignable-s4-diffs.json for pairings where there is a 'null' or similar empty value instead of a section name for one of the papers and p1p2-alignable-s4-diffs.json for all the remaining pairings that name a section/subsection in both papers.

## Create a program that filters paragraph mappings by bidirectionality (p1->p2 and p2<-p1)
Q: how to scale up to N+1 paper? Match to existing pairings, as well as orphans
Q: Re-assignment? Not this time.
Q: Re-representation? Recompute the question with the new matched paragraph/section added

## Questions
1. Do we need to reverse the implicit base and target to confirm we're not missing mappings?
2. How many paragraphs/sections are unmapped when we don't?