Given each focus member's previous/under-consideration/next context, what
candidate's `paragraph_under_consideration` best maps to the role shared by all
focus centers? The supplied candidates are the complete eligible pool, not
necessarily the whole document. Neighbors explain context but cannot supply
the matched role. Return the best defensible candidate's `selection_id`, or
null. Explain the shared role and center evidence in `basis`.

{{context_json}}
