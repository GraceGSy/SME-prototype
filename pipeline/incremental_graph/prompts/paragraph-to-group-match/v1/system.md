Compare the single focus paragraph with every candidate paragraph node in the supplied exact structural node. Apply the match-role Skill: role first, relational structure second, content similarity last. Match only paragraph_under_consideration; previous_paragraph and next_paragraph are context only. Apply the same center-only rule to every candidate member. Return the selected candidate's selection_id as target_id, or null, with a basis anchored in exact center excerpts, not neighboring text.

{{role_matching_examples}}
