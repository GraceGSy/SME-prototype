## Constructed matching examples

These invented demonstrations calibrate abstraction, not topic labels or a
fixed taxonomy. They are not additional candidates or source evidence. Their
handles are valid only inside their own demonstration. For the actual request,
use only its supplied candidates and output schema. Each excerpt below is the
complete focus or candidate evidence for that demonstration; omitted paragraph
neighbors are null. Apply the same reasoning independently in either direction.
Examples do not waive the requirement to read every member of a real node.

### 1. Same reasoning role across different topics: select the role match

Focus: "The permit rule allows only temporary structures, meaning structures
removable without demolition. The shed has a poured foundation that must be
broken up to remove it. It therefore fails the rule, and we deny the permit."
Generated question metadata: "Does the poured foundation make the shed permanent?"

Candidate `demo-analysis`: "The protocol admits only reversible responses,
meaning the signal must return to baseline after the stimulus is removed.
The signal remained elevated after removal. The response therefore fails the
criterion and is excluded from the analysis."

Candidate `demo-topic`: "The owner submitted the shed permit application in
April. The inspector visited in May, and the office scheduled a hearing in June."

Expected output:
```json
{"target_id":"demo-analysis","basis":"Both interpret a governing eligibility condition, apply observed facts, and conclude exclusion: 'removable without demolition' versus 'return to baseline' defines the condition; 'must be broken up' versus 'remained elevated' defeats it. The permit and experimental protocol play corresponding governing roles. demo-topic only recounts procedural history. The specific question about the shed does not override the focus's reasoning role.","evidence":{"focus":["removable without demolition"],"target":["return to baseline"]}}
```

### 2. Same tool, different job: abstain

Focus: "The notebook tool groups quotations by source and lets readers pin two
quotations side by side. Its comparison panel preserves links to the originals."

Candidate `demo-evaluation`: "Participants using the notebook tool found relevant
quotations more quickly than participants using separate tabs. The timed tasks
suggest that its comparison panel reduces lookup effort."

Expected output:
```json
{"target_id":null,"basis":"The focus describes capabilities ('groups quotations', 'lets readers pin'); the candidate supplies measured evidence of benefit ('found relevant quotations more quickly'). Describing how a tool works and evaluating its effect are distinct roles despite the identical tool and panel.","evidence":{"focus":[],"target":[]}}
```

### 3. Hypothesis versus evidence: abstain without borrowing a neighbor

Focus paragraph under consideration: "We predict that alternating speakers will
help listeners remember more facts because the voice changes mark topic boundaries."
Focus next paragraph, context only: "In the experiment, listeners recalled more
facts with alternating speakers than with a single speaker."

Candidate `demo-result`, paragraph under consideration: "Teams receiving staggered
reminders missed fewer deadlines in the trial than teams receiving one reminder."

Expected output:
```json
{"target_id":null,"basis":"The focus proposes an untested prediction ('We predict'); the candidate reports an observed outcome ('missed fewer deadlines in the trial'). The focus's next paragraph provides results, but it is not the passage being matched. Both concern interventions, yet prediction and evidence play different roles.","evidence":{"focus":[],"target":[]}}
```

### 4. Corresponding causal explanation: select it over a shared setting

Focus: "Closing the inlet valve cuts off the pump's water supply. Without that
supply, the pump cannot deliver water to the upper tank, so the tank stops filling."

Candidate `demo-mechanism`: "By blocking the messenger's route, the guards prevent
the warning from reaching the outpost. Without the warning, the defenders cannot
prepare their response, leaving the outpost unready for the attack."

Candidate `demo-setting`: "The inlet valve is beside the pump, below the upper
tank. A narrow service platform gives workers access to all three components."

Expected output:
```json
{"target_id":"demo-mechanism","basis":"Both explain how blocking an input prevents a downstream process: 'cuts off the pump's water supply' corresponds to 'prevent the warning from reaching the outpost'; 'cannot deliver water' corresponds to 'cannot prepare their response'. Water and warning occupy the required-input role, pump and defenders the dependent-actor role. demo-setting describes an arrangement, not this causal dependency.","evidence":{"focus":["cuts off the pump's water supply"],"target":["the warning from reaching the outpost"]}}
```

### 5. One paper splits a role across accepted paragraphs: match

Focus, paper_key `paper-3`: "Readers pin two passages side by side so they can
compare the original wording without switching screens."

Candidate `demo-comparison`, accepted members in this order:
- paper_key `paper-1`: "The viewer places selected passages alongside one another for direct comparison."
- paper_key `paper-2`: "The interface places selected excerpts in two columns."
- paper_key `paper-2`: "Keeping both excerpts visible avoids switching screens while checking their wording."

Expected output:
```json
{"target_id":"demo-comparison","basis":"Each paper explains how an interface supports direct comparison. Paper 2 distributes operation and purpose across two accepted paragraphs; both contribute, without each having to restate the full role. The focus performs that role in one paragraph.","evidence":{"focus":["compare the original wording without switching screens"],"target":["alongside one another for direct comparison","selected excerpts in two columns","avoids switching screens while checking their wording"]}}
```

### 6. A broad group question cannot supply missing support: abstain

Focus, paper_key `paper-3`: "Readers pin two passages side by side for direct comparison."
Candidate `demo-unsupported`, generated question: "How does the interface support comparison?"
Accepted members:
- paper_key `paper-1`: "The viewer places selected passages alongside one another."
- paper_key `paper-2`: "Readers completed the task faster with the tool than without it."

Expected output:
```json
{"target_id":null,"basis":"The focus and paper 1 describe interface operation. Paper 2 reports an evaluation outcome, not the operation enabling comparison. The generated question cannot make the shared role source-supported. Being about the same tool or appearing beside its description would not justify admitting a result paragraph.","evidence":{"focus":[],"target":[]}}
```

For the actual request, choose the strongest supported correspondence or null.
Do not copy an example answer or force a passage into an example's role. State
the decisive role and relations at an abstraction supported by both texts, not
by names alone or the empty label "both discuss something". Return one final
decision: an abstention explanation must have target_id null; a selected handle
must have an explanation that supports that selection without retracting it.
