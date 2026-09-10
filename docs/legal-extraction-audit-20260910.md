# Legal extraction sanity audit

Date: 2026-09-10. Reviewed all ten prepared legal documents against their local
opinion/dissent PDFs, including the newly corrected Porter opinion as a control.
No additional extraction or graph calls were made for this audit.

## Findings

Three additional extractions have confirmed ordinary-paragraph boundary errors.
Do not use the dissent corpus for a graph run until these are corrected.

| Document | Stored paragraphs | Longest unit (words) | Sanity-check result |
| --- | ---: | ---: | --- |
| Banuelos-Jimenez opinion | 15 | 304 | No new issue found |
| Core Optical opinion | 50 | 297 | No new ordinary-paragraph issue found; block quotations and numeric lower-level headings explain indentation flags |
| Lamb opinion | 41 | 304 | No new ordinary-paragraph issue found; block quotations explain indentation flags |
| Porter opinion | 38 | 321 | Re-extracted and verified before this audit |
| Westmoreland opinion | 29 | 437 | No new ordinary-paragraph issue found; the long unit contains an enumerated legal test |
| Banuelos-Jimenez dissent | 8 | 1,329 | Widespread merged paragraphs; rerun needed |
| Core Optical dissent | 1 | 172 | Genuinely one authored paragraph continuing onto the next PDF page |
| Lamb dissent | 24 | 243 | No new issue found |
| Porter dissent | 66 | 280 | Two body-paragraph boundaries and one within-footnote paragraph boundary are merged |
| Westmoreland dissent | 25 | 1,697 | Widespread merged paragraphs; rerun needed |

The opinion corpus now contains 173 paragraph units, not the pre-correction 149.
The dissent count of 124 is still an underestimate of the source paragraph units.
The opinion set can proceed to an offline cost preflight; no paid run is started
or authorized by this report.

## Confirmed examples

- **Banuelos-Jimenez dissent, printed page 9 (split-PDF page 2):** the paragraphs
  beginning "In United States v. Mitchell", "United States v. Fuller-Ragland",
  and "Indeed, the elements" are visibly separate indented paragraphs but occur
  inside the same extracted paragraph. The audit flags 26 contained paragraph
  starts across this dissent, with representative merges visually confirmed.
- **Westmoreland dissent, printed page 14 (split-PDF page 2):** separate paragraphs
  beginning "Tyree admits", "Westmoreland also says", and "Westmoreland filed"
  occur inside one extracted paragraph. There are 43 contained-start flags across
  this dissent; representative body merges are visually confirmed.
- **Porter dissent, printed pages 27, 31, and 32 (split-PDF pages 8, 12, and 13):**
  "First, we must make" and "Instead, the critical question" begin separate body
  paragraphs in the PDF but are appended to preceding paragraphs in the JSON.
  Footnote 5 has a second paragraph beginning "I tend to agree with Judge Motz"
  that is flattened into the first footnote paragraph. A moderate maximum length
  therefore does not prove extraction fidelity.

## Coverage and limitations

The read-only `helpers/audit_legal_extractions.py` helper reads all ten PDFs with
pdfplumber, compares indented line starts with canonical paragraph starts,
checks raw-text line prefixes, flags repeated extracted paragraphs, records
printed heading candidates, and checks endings independently against both raw
text and the final PDF line. Its detailed report is generated under ignored
`output/legal-extraction-audit-20260910.json`.

All ten final raw/PDF passages are present. The duplicate-paragraph check found
no candidates. The remaining raw-line prefix differences were inline footnote
reference numbers, not missing body prose; the surrounding text is present.
Headings and substantive footnotes were inspected. This found no unexplained
body-text omission, new section-heading error, or truncated ending in this pass.

Indentation alone is not a paragraph oracle. Core Optical uses a different margin
and indent, and its block quotes produce many indented continuation lines. Lamb
has block quotations, and Westmoreland's opinion has an enumerated test. The
automated counts include these review candidates; they must not be reported as
counts of actual extraction errors. Quotations/lists remain embedded in the
surrounding extracted paragraph under the existing representation; no new
segmentation convention was introduced.

Visual review covered the complete relevant pages for the confirmed errors and
representative false positives, not a character-by-character transcription audit
of every page. "No new issue found" means this sanity check passed, not proof
that every character, citation, footnote attachment, or boundary is perfect.

## Source files

All paths below are relative to `C:/HBS/Glassman Lab Research/legal corpus/`.

- `Banuelos-Jimenez v. Garland/23a0097p-06_opinion_Griffin.pdf`
- `Banuelos-Jimenez v. Garland/23a0097p-06_dissent_Gilman.pdf`
- `Core Optical Technologies, LLC v. Nokia Corporation/23-1001_opinion_Taranto.pdf`
- `Core Optical Technologies, LLC v. Nokia Corporation/23-1001_dissent_Mayer.pdf`
- `Lamb v. Kendrick/22a0232p-06_opinion_Donald.pdf`
- `Lamb v. Kendrick/22a0232p-06_dissent_Nalbandian.pdf`
- `Porter v. Board of Trustees of North Carolina State University/221712_opinion_Thacker.pdf`
- `Porter v. Board of Trustees of North Carolina State University/221712_dissent_Richardson.pdf`
- `Westmoreland v. Butler County/22a0053p-06_opinion_Gibbons.pdf`
- `Westmoreland v. Butler County/22a0053p-06_dissent_Bush.pdf`

## Prior Porter repair

The preceding authorized Porter-opinion rerun used the unchanged native
extraction Skill on newly prepared indentation-preserving PDF text. It recorded
one successful response, approximately $0.1593 in token cost excluding tool fees.
An earlier request was rejected for unsupported schema constraints before a
generation response was returned. The extraction-only API schema fix retains
the canonical local validation rules. The saved HCI matching-policy hash still
matches the current matcher, prompts, Skills, and dependencies. All 93 Python
tests passed after the repair; no matching algorithm was changed.
