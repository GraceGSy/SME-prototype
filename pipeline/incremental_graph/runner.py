"""Execute the configured incremental mapping stages in paper insertion order."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..document import ROLE_FIELD
from ..files import write_json
from ..providers.jev import JevRequestTooLarge
from .close_calls import close_options, write_close_call_report
from .configuration import validate_pipeline_config
from .evidence import Evidence
from .export import export_revision
from .graph import RoleGraph
from .journal import RevisionJournal
from .judgments import CachedJudgments, JudgmentProvider, inherited_structural_match
from .match_rules import (
    adjacent_core_anchors,
    adjacent_paragraph_fan_in,
    reciprocal_matches,
    recovery_admission,
)
from .models import (
    Granularity,
    InsertionState,
    JudgmentRequest,
    JudgmentResult,
    MatchBatch,
    MatchDecision,
    MatchDirection,
    Paper,
    Phase,
    PipelineConfig,
    StageConfig,
)
from .singleton_report import write_singleton_report

PAIRWISE_FROM_PAPER = 3


class PipelineError(RuntimeError):
    """Raised when stage configuration violates the pipeline's data dependencies."""


class IncrementalGraphRunner:
    """Run one immutable revision of the incremental node graph."""

    def __init__(
        self,
        config: PipelineConfig,
        judge: JudgmentProvider,
        revision_dir: Path,
        *,
        max_granularity: Granularity = "section",
        force_paper_index: int | None = None,
        force_stage_id: str | None = None,
    ):
        validate_pipeline_config(config)
        self.config = config
        self.judge = judge
        self.jev_judge = judge if isinstance(judge, CachedJudgments) and judge.jev else None
        self.revision_dir = revision_dir
        self.revision_dir.mkdir(parents=True, exist_ok=False)
        self.max_granularity = max_granularity
        self.force_paper_index = force_paper_index
        self.force_stage_id = force_stage_id
        self.journal = RevisionJournal(revision_dir)
        self.role_graph = RoleGraph(self.journal)
        self.papers: list[Paper] = []
        self.insertions_by_paper: dict[str, InsertionState] = {}
        self.evidence = Evidence(self.role_graph)
        self.shared_root_id: str | None = None
        self.handlers: dict[str, Callable[[StageConfig, InsertionState], Any]] = {
            "ingest_paper": self._ingest_paper,
            "generate_section_role_statements": self._generate_section_role_statements,
            "match_sections": self._match_sections,
            "reconcile_sections": self._reconcile_sections,
            "generate_section_group_role_statements": self._generate_section_group_role_statements,
            "rerepresent_section_singletons": self._rerepresent_section_singletons,
            "regenerate_rerepresented_section_role_statements": (
                self._regenerate_rerepresented_section_role_statements
            ),
            "generate_paragraph_role_statements": self._generate_paragraph_role_statements,
            "match_paragraphs": self._match_paragraphs,
            "reconcile_paragraphs": self._reconcile_paragraphs,
            "generate_paragraph_group_role_statements": self._generate_paragraph_group_role_statements,
            "rerepresent_paragraph_singletons": self._rerepresent_paragraph_singletons,
            "regenerate_rerepresented_paragraph_role_statements": self._regenerate_rerepresented_paragraph_role_statements,
        }

    def run(self, papers: list[Paper], *, sections_only: bool = False) -> dict[str, Any]:
        if sections_only and self.max_granularity == "paragraph":
            raise ValueError("A paragraph-only corpus has no section matching phase")
        for paper_index, paper in enumerate(papers, start=1):
            self._register_paper(paper)
            insertion = InsertionState(paper=paper, paper_index=paper_index)
            self.insertions_by_paper[paper.paper_id] = insertion
            self._run_phase("structural", insertion)
            if sections_only:
                continue  # Recursive reparenting also makes paragraph decisions.
            self._recurse_reparented_sections(insertion)
            self._run_phase("paragraph", insertion)
        self.journal.finalize()
        if sections_only:
            if self.config.close_call_margin:
                write_close_call_report(
                    self.journal.events, self.role_graph, self.revision_dir / "reports"
                )
            checkpoint = {
                "completed_phase": "structural",
                "paper_order": list(self.role_graph.paper_order),
                "section_groups": {gid: data for gid, data in self.role_graph.nodes("section")},
            }
            write_json(self.revision_dir / "section-checkpoint.json", checkpoint)
            return {"completed_phase": "structural", "revision_dir": str(self.revision_dir)}
        export_revision(self.revision_dir / "dataset", self.role_graph, self.papers)
        # The singleton report creates reports/; the close-call report joins it there.
        write_singleton_report(
            self.journal.events, self.revision_dir / "reports", fan_in=self.config.fan_in
        )
        if self.config.close_call_margin:
            write_close_call_report(
                self.journal.events, self.role_graph, self.revision_dir / "reports"
            )
        summary = {
            "schema_version": 1,
            "pipeline_id": self.config.pipeline_id,
            "max_granularity": self.max_granularity,
            "paper_count": len(self.papers),
            "paper_order": [paper.paper_id for paper in self.papers],
            "graph_hash": self.role_graph.graph_hash(),
            "event_count": len(self.journal.events),
            "attempt_count": self.journal.attempt_count,
            "dataset_dir": str((self.revision_dir / "dataset").resolve()),
        }
        write_json(self.revision_dir / "summary.json", summary)
        return summary

    def _run_phase(self, phase: Phase, insertion: InsertionState) -> None:
        for stage in (stage for stage in self.config.stages if stage.phase == phase):
            skip_structural_stage = (
                self.max_granularity == "paragraph"
                and phase != "paragraph"
                and stage.handler != "ingest_paper"
            )
            if skip_structural_stage:
                continue
            if self.jev_judge and stage.handler in {
                "generate_section_group_role_statements",
                "generate_paragraph_group_role_statements",
            }:
                continue  # Generate role statements once after singleton recovery.
            handler = self.handlers.get(stage.handler)
            if handler is None:
                raise PipelineError(f"Unknown stage handler {stage.handler!r} for stage {stage.id}")
            result = handler(stage, insertion)
            insertion.stage_results[stage.id] = result
            self.journal.stage(insertion.paper_index, stage.id, result)

    def _fan_in(self, level: str) -> bool:
        return self.config.fan_in

    def _register_paper(self, paper: Paper) -> None:
        self.papers.append(paper)
        self.evidence.register(paper)

    def _ingest_paper(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        self.role_graph.add_paper(
            insertion.paper.paper_id, insertion.paper.title, insertion.paper_index
        )
        result = {
            "paper_id": insertion.paper.paper_id,
            "sections": len(insertion.paper.sections),
            "paragraphs": sum(len(section.paragraphs) for section in insertion.paper.sections),
        }
        if self.max_granularity == "paragraph":
            result["shared_root_id"] = self._assign_shared_root(insertion)
        return result

    def _assign_shared_root(self, insertion: InsertionState) -> str:
        """Place each single-section document in one deterministic corpus root."""

        if len(insertion.paper.sections) != 1:
            raise PipelineError("paragraph granularity requires one section per document")
        section = insertion.paper.sections[0]
        if self.shared_root_id is None:
            self.shared_root_id = self.role_graph.create_group(
                level="section",
                parent_id=None,
                member_id=section.id,
                paper_id=insertion.paper.paper_id,
                paper_index=insertion.paper_index,
                ordinal=section.ordinal,
                unit_kind=section.kind,
                family_id=section.family_id,
            )
        else:
            self.role_graph.add_member(
                self.shared_root_id,
                section.id,
                insertion.paper.paper_id,
                insertion.paper_index,
                section.ordinal,
                unit_kind=section.kind,
                family_id=section.family_id,
            )
        insertion.section_assignments[section.id] = self.shared_root_id
        return self.shared_root_id

    def _generate_section_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        self._require_prompt(stage)
        results = []
        for section in insertion.paper.sections:
            if section.role_statement:
                results.append(
                    {
                        "section_id": section.id,
                        "role_statement": section.role_statement,
                        "source": "input",
                    }
                )
                continue
            context = {
                "paper": {"paper_id": insertion.paper.paper_id, "title": insertion.paper.title},
                "section": self.evidence.section_context(insertion.paper.paper_id, section.id),
            }
            role_statement, attempt_id = self._role_statement(stage, insertion, section.id, context)
            section.role_statement = role_statement
            results.append(
                {
                    "section_id": section.id,
                    "role_statement": role_statement,
                    "source": "model",
                    "attempt_id": attempt_id,
                }
            )
        return results

    def _match_sections(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        existing = self.role_graph.group_ids("section")
        unit_ids = [section.id for section in insertion.paper.sections]
        insertion.section_matches = self._match_units(
            stage, insertion, "section", None, unit_ids, existing
        )
        return self._match_batch_dump(insertion.section_matches)

    def _reconcile_sections(self, stage: StageConfig, insertion: InsertionState) -> dict[str, str]:
        if insertion.section_matches is None:
            raise PipelineError("reconcile_sections requires match_sections to run first")
        insertion.section_assignments = self._reconcile(
            insertion,
            level="section",
            parent_id=None,
            batch=insertion.section_matches,
        )
        return insertion.section_assignments

    def _generate_section_group_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._generate_group_role_statements(stage, insertion, "section")

    def _rerepresent_section_singletons(
        self, stage: StageConfig, insertion: InsertionState
    ) -> dict[str, Any]:
        return self._rerepresent_singletons(stage, insertion, "section")

    def _rerepresent_paragraph_singletons(
        self, stage: StageConfig, insertion: InsertionState
    ) -> dict[str, Any]:
        return self._rerepresent_singletons(stage, insertion, "paragraph")

    def _rerepresent_singletons(
        self, stage: StageConfig, insertion: InsertionState, level: str
    ) -> dict[str, Any]:
        """Apply reciprocal top-1 decisions from one frozen per-insertion snapshot."""
        nodes = dict(self.role_graph.nodes(level))
        fan_in = self._fan_in(level)
        singletons = [node_id for node_id, data in nodes.items() if len(data["members"]) == 1]
        established = [node_id for node_id, data in nodes.items() if len(data["members"]) > 1]
        eligible = {
            source_id: [
                target_id
                for target_id in established
                if recovery_admission(nodes[source_id], nodes[target_id], fan_in=fan_in) is not None
            ]
            for source_id in singletons
        }
        batch = MatchBatch(existing_group_ids=established, new_unit_ids=singletons)

        def recovery_unit(node_id, selectable=False):
            unit = self.evidence.node_match_context(node_id, selectable=selectable)
            if level == "paragraph" and len(unit["members"]) == 1:
                return {
                    **unit["members"][0],
                    **({"selection_id": node_id} if selectable else {}),
                }
            return unit

        if self._uses_pairwise(insertion):
            # Admission requires a shared parent, so each parent scope is independent.
            for parent_id in sorted({nodes[s].get("parent_id") for s in singletons}, key=str):
                part = self._pairwise_batch(
                    stage,
                    insertion,
                    scope={
                        **self.evidence.scope_context(level, parent_id),
                        "match_mode": "rerepresentation",
                    },
                    directions=("singleton_to_group", "group_to_singleton"),
                    sources=[s for s in singletons if nodes[s].get("parent_id") == parent_id],
                    targets=[g for g in established if nodes[g].get("parent_id") == parent_id],
                    eligible=eligible,
                    reverse_eligible=lambda s, g: recovery_admission(nodes[s], nodes[g]) == "core",
                    source_context=recovery_unit,
                    target_context=recovery_unit,
                )
                batch.forward.update(part.forward)
                batch.reverse.update(part.reverse)
        # Before pairwise matching, each direction chooses among all its options at once.
        directional = (
            ()
            if self._uses_pairwise(insertion)
            else (
                ("singleton_to_group", singletons, batch.forward),
                ("group_to_singleton", established, batch.reverse),
            )
        )
        for direction, sources, decisions in directional:
            for source_id in sources:
                allowed = (
                    eligible[source_id]
                    if direction == "singleton_to_group"
                    else [
                        singleton_id
                        for singleton_id in singletons
                        if source_id in eligible[singleton_id]
                        and recovery_admission(nodes[singleton_id], nodes[source_id]) == "core"
                    ]
                )
                if not allowed:
                    continue
                decisions[source_id] = self._match(
                    stage,
                    insertion,
                    direction=direction,
                    source_id=source_id,
                    allowed_ids=allowed,
                    context={
                        "scope": {
                            **self.evidence.scope_context(level, nodes[source_id].get("parent_id")),
                            "match_mode": "rerepresentation",
                        },
                        "focus": recovery_unit(source_id),
                        "candidates": [
                            recovery_unit(node_id, selectable=True) for node_id in allowed
                        ],
                    },
                )
        merged = []
        for source_id, target_id in reciprocal_matches(batch).items():
            member = nodes[source_id]["members"][0]
            owner = self.insertions_by_paper[member["paper_id"]]
            assignments = (
                owner.section_assignments if level == "section" else owner.paragraph_assignments
            )
            if assignments.get(member["unit_id"]) != source_id:
                raise PipelineError(f"Assignment for {source_id} is stale")
            forward = batch.forward[source_id]
            reverse = batch.reverse[target_id]
            self.role_graph.merge_singleton(
                source_id,
                target_id,
                paper_index=insertion.paper_index,
                attempt_id=forward.attempt_id,
                reverse_attempt_id=reverse.attempt_id,
            )
            assignments[member["unit_id"]] = target_id
            merged.append(
                {
                    "source_group_id": source_id,
                    "target_group_id": target_id,
                    "paper_id": member["paper_id"],
                    "unit_id": member["unit_id"],
                    "attempt_id": forward.attempt_id,
                    "reverse_attempt_id": reverse.attempt_id,
                }
            )
        if fan_in:
            accepted_cores = {m["source_group_id"] for m in merged}
            for source_id, decision in batch.forward.items():
                target_id = decision.target_id
                if source_id in accepted_cores or target_id is None:
                    continue
                anchors = adjacent_core_anchors(
                    nodes[source_id]["members"], self.role_graph.members(target_id)
                )
                if not anchors:
                    continue
                member = nodes[source_id]["members"][0]
                anchor = anchors[(member["paper_id"], member["unit_id"])]
                self.role_graph.merge_paragraph_group(
                    source_id, target_id, paper_index=insertion.paper_index
                )
                owner = self.insertions_by_paper[member["paper_id"]]
                (owner.section_assignments if level == "section" else owner.paragraph_assignments)[
                    member["unit_id"]
                ] = target_id
                self.journal.event(
                    f"{level}_fan_in_added",
                    paper_index=insertion.paper_index,
                    inserted_paper_id=insertion.paper.paper_id,
                    paper_id=member["paper_id"],
                    node_id=target_id,
                    parent_id=nodes[source_id].get("parent_id"),
                    unit_id=member["unit_id"],
                    reciprocal_unit_id=anchor["unit_id"],
                    direction="singleton_to_group",
                    source_group_id=source_id,
                    attempt_id=decision.attempt_id,
                )
                merged.append(
                    {
                        "source_group_id": source_id,
                        "target_group_id": target_id,
                        "paper_id": member["paper_id"],
                        "unit_id": member["unit_id"],
                        "attempt_id": decision.attempt_id,
                        "membership_role": "fan_in",
                    }
                )
        return {
            "singleton_ids": singletons,
            "established_group_ids": established,
            "candidates_by_singleton": eligible,
            "forward": {key: value.model_dump(mode="json") for key, value in batch.forward.items()},
            "reverse": {key: value.model_dump(mode="json") for key, value in batch.reverse.items()},
            "merged": merged,
            "changed_group_ids": sorted({item["target_group_id"] for item in merged}),
        }

    def _regenerate_rerepresented_section_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._regenerate_rerepresented_role_statements(stage, insertion, "section")

    def _regenerate_rerepresented_paragraph_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._regenerate_rerepresented_role_statements(stage, insertion, "paragraph")

    def _regenerate_rerepresented_role_statements(
        self, stage: StageConfig, insertion: InsertionState, level: str
    ) -> list[dict[str, str]]:
        result = insertion.stage_results.get(f"{level}_rerepresentation")
        if result is None:
            raise PipelineError(f"{stage.id} requires {level}_rerepresentation")
        return self._generate_group_role_statements(
            stage,
            insertion,
            level,
            group_ids=None if self.jev_judge else result["changed_group_ids"],
        )

    def _generate_paragraph_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        self._require_prompt(stage)
        results = []
        for section in insertion.paper.sections:
            for index, paragraph in enumerate(section.paragraphs):
                if paragraph.role_statement:
                    results.append(
                        {
                            "paragraph_id": paragraph.id,
                            "role_statement": paragraph.role_statement,
                            "source": "input",
                        }
                    )
                    continue
                context = {
                    "paper": self.evidence.paper_context(insertion.paper),
                    "previous_paragraph": self.evidence.paragraph_evidence(
                        section.paragraphs[index - 1] if index else None
                    ),
                    "paragraph": self.evidence.paragraph_context(
                        insertion.paper.paper_id, paragraph.id
                    ),
                    "next_paragraph": self.evidence.paragraph_evidence(
                        section.paragraphs[index + 1]
                        if index + 1 < len(section.paragraphs)
                        else None
                    ),
                }
                role_statement, attempt_id = self._role_statement(
                    stage, insertion, paragraph.id, context
                )
                paragraph.role_statement = role_statement
                results.append(
                    {
                        "paragraph_id": paragraph.id,
                        "role_statement": role_statement,
                        "source": "model",
                        "attempt_id": attempt_id,
                    }
                )
        return results

    def _match_paragraphs(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        if not insertion.section_assignments:
            raise PipelineError("match_paragraphs requires reconcile_sections to run first")
        # Paragraphs match only inside their section group. Section fan-in can put two
        # sections of one paper in the same group, so batch by group, not by section:
        # one batch must see every new paragraph before any of the group's nodes change.
        by_group: dict[str, list] = {}
        for unit in insertion.paper.sections:
            by_group.setdefault(insertion.section_assignments[unit.id], []).append(unit)
        results = {}
        for structural_group_id, units in by_group.items():
            unit_ids = [paragraph.id for unit in units for paragraph in unit.paragraphs]
            existing = self.role_graph.paragraph_groups_for_section(
                structural_group_id, insertion.paper.paper_id
            )
            batch = self._match_units(
                stage,
                insertion,
                "paragraph",
                structural_group_id,
                unit_ids,
                existing,
            )
            # Keyed by the group's first section; reconciliation reads its section group.
            insertion.paragraph_matches[units[0].id] = batch
            results[units[0].id] = {
                "section_ids": [unit.id for unit in units],
                **self._match_batch_dump(batch),
            }
        return results

    def _recurse_reparented_sections(self, insertion: InsertionState) -> None:
        """An absorbed older section is a new contribution to its destination's child scope."""
        merges = insertion.stage_results.get("section_rerepresentation", {}).get("merged", [])
        pending = [m for m in merges if m["paper_id"] != insertion.paper.paper_id]
        # Sections absorbed by reverse fan-in while this paper was reconciled move the
        # same way, so their paragraphs are matched again inside the new section group.
        pending += [{**m, "absorbed": True} for m in insertion.absorbed_sections]
        if not pending:
            return
        matching = next(s for s in self.config.stages if s.handler == "match_paragraphs")
        role_statements = next(
            s for s in self.config.stages if s.handler == "generate_paragraph_group_role_statements"
        )
        # As in paragraph matching, one batch per (paper, section group): two sections of
        # one paper moved into the same group are matched together, in reading order.
        batches: dict[tuple[str, str], list] = {}
        for merge in pending:
            owner = self.insertions_by_paper[merge["paper_id"]]
            section = next(s for s in owner.paper.sections if s.id == merge["unit_id"])
            unit_ids = [p.id for p in section.paragraphs]
            if merge.get("absorbed"):
                # An absorbed group may already have matched some of these paragraphs
                # across papers; those groups moved with it. Match the paragraphs that
                # are still alone.
                unit_ids = [
                    unit_id
                    for unit_id in unit_ids
                    if len(self.role_graph.node(owner.paragraph_assignments[unit_id])["members"])
                    == 1
                ]
            # A singleton section cannot already own cross-paper paragraph groups.
            for unit_id in unit_ids:
                node = self.role_graph.node(owner.paragraph_assignments[unit_id])
                if len(node["members"]) != 1:
                    raise PipelineError(
                        "A reparented singleton section must own singleton paragraphs"
                    )
            if unit_ids:
                key = (merge["paper_id"], merge["target_group_id"])
                batches.setdefault(key, []).append((section, unit_ids))
        results = []
        for (paper_id, parent_id), sections in batches.items():
            owner = self.insertions_by_paper[paper_id]
            sections.sort(key=lambda item: item[0].ordinal)
            unit_ids = [unit_id for _, ids in sections for unit_id in ids]
            section = sections[0][0]
            contribution = InsertionState(
                paper=owner.paper,
                paper_index=insertion.paper_index,
                section_assignments=owner.section_assignments,
                paragraph_assignments=owner.paragraph_assignments,
            )
            batch = self._match_units(
                matching,
                contribution,
                "paragraph",
                parent_id,
                unit_ids,
                self.role_graph.paragraph_groups_for_section(parent_id, owner.paper.paper_id),
            )
            owner.paragraph_assignments.update(
                self._reconcile(
                    contribution,
                    level="paragraph",
                    parent_id=parent_id,
                    batch=batch,
                )
            )
            if not self.jev_judge:
                self._generate_group_role_statements(
                    role_statements,
                    insertion,
                    "paragraph",
                    group_ids=self.role_graph.group_ids("paragraph", parent_id),
                )
            results.append(
                {
                    "paper_id": owner.paper.paper_id,
                    "section_id": section.id,
                    "section_ids": [s.id for s, _ in sections],
                    "parent_id": parent_id,
                    **self._match_batch_dump(batch),
                }
            )
        self.journal.stage(insertion.paper_index, "recursive_paragraph_matching", results)

    def _reconcile_paragraphs(
        self, stage: StageConfig, insertion: InsertionState
    ) -> dict[str, str]:
        if not insertion.paragraph_matches and any(
            section.paragraphs for section in insertion.paper.sections
        ):
            raise PipelineError("reconcile_paragraphs requires match_paragraphs to run first")
        assignments = {}
        for unit_id, batch in insertion.paragraph_matches.items():
            assignments.update(
                self._reconcile(
                    insertion,
                    level="paragraph",
                    parent_id=insertion.section_assignments[unit_id],
                    batch=batch,
                )
            )
        insertion.paragraph_assignments = assignments
        return assignments

    def _generate_paragraph_group_role_statements(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._generate_group_role_statements(stage, insertion, "paragraph")

    def _role_statement(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        source_id: str,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        request = JudgmentRequest(
            key=f"{insertion.paper.paper_id}:{stage.id}:{source_id}",
            paper_index=insertion.paper_index,
            stage_id=stage.id,
            output_kind="role_statement",
            prompt_ref=stage.prompt or "",
            context_ref=stage.context or "",
            context=context,
            skill_ref=stage.skill,
            max_tokens=stage.max_tokens,
            max_input_tokens=stage.max_input_tokens,
            force=self._forced(stage, insertion),
        )
        result = self.judge.judge(request)
        attempt_id = self.journal.attempt(request, result)
        return str(result.normalized[ROLE_FIELD]).strip(), attempt_id

    def _match_units(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        level: str,
        parent_id: str | None,
        new_unit_ids: list[str],
        existing_group_ids: list[str],
    ) -> MatchBatch:
        self._require_match_prompts(stage)
        batch = MatchBatch(existing_group_ids=existing_group_ids, new_unit_ids=new_unit_ids)
        inherit = level == "paragraph" and self._can_inherit_paragraph_match(
            insertion, parent_id, new_unit_ids, existing_group_ids
        )
        scope = self.evidence.scope_context(level, parent_id)
        if self._uses_pairwise(insertion) and not inherit:
            return self._pairwise_batch(
                stage,
                insertion,
                scope=scope,
                directions=("new_to_group", "group_to_new"),
                sources=new_unit_ids,
                targets=existing_group_ids,
                eligible={unit_id: existing_group_ids for unit_id in new_unit_ids},
                reverse_eligible=lambda unit_id, group_id: True,
                source_context=lambda unit_id, selectable: self.evidence.match_unit_context(
                    insertion.paper.paper_id, unit_id, level, selectable=selectable
                ),
                target_context=lambda group_id, selectable: self.evidence.match_group_context(
                    group_id, selectable=selectable
                ),
            )
        group_candidates = [
            self.evidence.match_group_context(group_id, selectable=True)
            for group_id in existing_group_ids
        ]
        unit_candidates = [
            self.evidence.match_unit_context(
                insertion.paper.paper_id, unit_id, level, selectable=True
            )
            for unit_id in new_unit_ids
        ]

        for unit_id in new_unit_ids:
            if not existing_group_ids:
                continue
            context = {
                "scope": scope,
                "focus": self.evidence.match_unit_context(insertion.paper.paper_id, unit_id, level),
                "candidates": group_candidates,
            }
            decision = self._match(
                stage,
                insertion,
                direction="new_to_group",
                source_id=unit_id,
                allowed_ids=existing_group_ids,
                context=context,
                inherit_structural_match=inherit,
            )
            batch.forward[unit_id] = decision

        for group_id in existing_group_ids:
            if not new_unit_ids:
                continue
            context = {
                "scope": scope,
                "focus": self.evidence.match_group_context(group_id),
                "candidates": unit_candidates,
            }
            decision = self._match(
                stage,
                insertion,
                direction="group_to_new",
                source_id=group_id,
                allowed_ids=new_unit_ids,
                context=context,
                inherit_structural_match=inherit,
            )
            batch.reverse[group_id] = decision
        return batch

    def _can_inherit_paragraph_match(
        self,
        insertion: InsertionState,
        parent_id: str | None,
        new_unit_ids: list[str],
        existing_group_ids: list[str],
    ) -> bool:
        # A paragraph-only corpus root is not an established structural match.
        if (
            self.max_granularity == "paragraph"
            or parent_id is None
            or len(new_unit_ids) != 1
            or len(existing_group_ids) != 1
        ):
            return False
        structural_members = {
            (member["paper_id"], member["unit_id"]) for member in self.role_graph.members(parent_id)
        }
        sources = [(insertion.paper.paper_id, new_unit_ids[0])] + [
            (member["paper_id"], member["unit_id"])
            for member in self.role_graph.members(existing_group_ids[0])
        ]
        for paper_id, paragraph_id in sources:
            section, paragraph = self.evidence.paragraph_lookup[(paper_id, paragraph_id)]
            if (
                (paper_id, section.id) not in structural_members
                or len(section.paragraphs) != 1
                or not paragraph.text.strip()
                # A section's structural text can also contain subsection paragraphs.
                or section.text.strip() != paragraph.text.strip()
            ):
                return False
        return True

    def _match(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        *,
        direction: MatchDirection,
        source_id: str,
        allowed_ids: list[str],
        context: dict[str, Any],
        inherit_structural_match: bool = False,
    ) -> MatchDecision:
        attempt_id, result = self._ranked_vote(
            stage,
            insertion,
            direction=direction,
            source_id=source_id,
            allowed_ids=allowed_ids,
            context=context,
            inherit_structural_match=inherit_structural_match,
        )
        return self._record_decision(
            insertion,
            context["scope"],
            direction=direction,
            source_id=source_id,
            target_id=result.normalized.get("target_id"),
            candidate_ids=allowed_ids,
            attempt_id=attempt_id,
        )

    def _vote(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        *,
        direction: MatchDirection,
        source_id: str,
        allowed_ids: list[str],
        context: dict[str, Any],
        inherit_structural_match: bool = False,
        rank_only: bool = False,
        key_suffix: str = "",
        candidate_papers: bool = True,
    ) -> tuple[str, JudgmentResult]:
        request = JudgmentRequest(
            key=f"{insertion.paper.paper_id}:{stage.id}:{direction}:{source_id}{key_suffix}",
            paper_index=insertion.paper_index,
            stage_id=stage.id,
            output_kind="match",
            prompt_ref=stage.prompts[direction],
            context_ref=stage.contexts[direction],
            context=context,
            allowed_match_ids=allowed_ids,
            skill_ref=stage.skill,
            max_tokens=stage.max_tokens,
            max_input_tokens=stage.max_input_tokens,
            force=self._forced(stage, insertion),
        )
        vote_request = request
        if self.jev_judge and not inherit_structural_match:
            annotations = self.evidence.jev_annotations(
                context, self.shared_root_id, candidate_papers=candidate_papers
            )
            vote_request = request.model_copy(
                update={"context": {**context, "outline": annotations}}
            )
        result = (
            inherited_structural_match(request)
            if inherit_structural_match
            else self.jev_judge.vote(vote_request, rank_only=rank_only)
            if self.jev_judge
            else self.judge.judge(request)
        )
        attempt_id = self.journal.attempt(request, result)
        return attempt_id, result

    def _ranked_vote(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        *,
        resolve_close_calls: bool = True,
        **vote: Any,
    ) -> tuple[str, JudgmentResult]:
        """Vote; if the ranking is close, re-ask among the close options, then hold."""
        attempt_id, result = self._vote(stage, insertion, **vote)
        margin = self.config.close_call_margin
        jev = result.raw_response.get("jev") if margin and resolve_close_calls else None
        ranking = jev.get("choice") if isinstance(jev, dict) else None
        if not ranking:
            return attempt_id, result
        close = close_options(ranking["probabilities"], margin)
        if len(close) < 2:
            return attempt_id, result
        allowed = vote["allowed_ids"]
        record: dict[str, Any] = {
            "margin": margin,
            "options": len(ranking["probabilities"]),
            "first": {
                "attempt_id": attempt_id,
                "probabilities": ranking["probabilities"],
                "close_ids": close,
            },
        }
        if len(close) < len(ranking["probabilities"]):
            # Keep the original candidate order; only the far options are dropped.
            keep = [i for i in allowed if i in close]
            candidates = [
                c for i, c in zip(allowed, vote["context"]["candidates"], strict=True) if i in close
            ]
            attempt_id, result = self._vote(
                stage,
                insertion,
                **{
                    **vote,
                    "allowed_ids": keep,
                    "context": {**vote["context"], "candidates": candidates},
                    "rank_only": True,
                    "key_suffix": vote.get("key_suffix", "") + ":close",
                },
            )
            ranking = result.raw_response["jev"]["choice"]
            still_close = close_options(ranking["probabilities"], margin)
            record["reask"] = {
                "attempt_id": attempt_id,
                "probabilities": ranking["probabilities"],
                "close_ids": still_close,
            }
            if len(still_close) < 2:
                record["outcome"] = "resolved"
        record.setdefault("outcome", "held")
        if record["outcome"] == "held":
            result = result.model_copy(
                update={"normalized": {**result.normalized, "target_id": None}}
            )
        direction = vote["direction"]
        source_id = vote["source_id"]
        unit: dict[str, Any] = {}
        if direction == "new_to_group":
            unit = {"paper_id": insertion.paper.paper_id, "unit_id": source_id}
        elif direction == "singleton_to_group":
            member = self.role_graph.members(source_id)[0]
            unit = {"paper_id": member["paper_id"], "unit_id": member["unit_id"]}
        scope = vote["context"]["scope"]
        self.journal.event(
            "close_call",
            paper_index=insertion.paper_index,
            level=scope["level"],
            parent_id=scope.get("parent_group_id"),
            direction=direction,
            source_id=source_id,
            target_id=result.normalized.get("target_id"),
            **unit,
            **record,
        )
        return attempt_id, result

    def _record_decision(
        self,
        insertion: InsertionState,
        scope: dict[str, Any],
        *,
        direction: MatchDirection,
        source_id: str,
        target_id: str | None,
        candidate_ids: list[str],
        attempt_id: str,
        **payload: Any,
    ) -> MatchDecision:
        self.journal.event(
            "match_recorded",
            paper_index=insertion.paper_index,
            level=scope["level"],
            parent_id=scope.get("parent_group_id"),
            direction=direction,
            source_id=source_id,
            target_id=target_id,
            candidate_ids=candidate_ids,
            attempt_id=attempt_id,
            **(
                {"unit_paper_id": insertion.paper.paper_id}
                if direction in {"new_to_group", "group_to_new"}
                else {}
            ),
            **payload,
        )
        return MatchDecision(
            source_id=source_id,
            target_id=target_id,
            direction=direction,
            attempt_id=attempt_id,
        )

    def _uses_pairwise(self, insertion: InsertionState) -> bool:
        # Until the third paper, one request already holds at most two complete papers.
        return self.jev_judge is not None and insertion.paper_index >= PAIRWISE_FROM_PAPER

    def _pairwise_batch(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        *,
        scope: dict[str, Any],
        directions: tuple[MatchDirection, MatchDirection],
        sources: list[str],
        targets: list[str],
        eligible: dict[str, list[str]],
        reverse_eligible: Callable[[str, str], bool],
        source_context: Callable[[str, bool], dict[str, Any]],
        target_context: Callable[[str, bool], dict[str, Any]],
    ) -> MatchBatch:
        """Ask one yes/no question per eligible pair, then choose among the passes.

        Each yes/no request holds the focus's paper and the one candidate node's latest
        paper. Both directions read the same pass table; when two or more options pass,
        one ranking question goes over exactly those options.
        """
        forward_direction, reverse_direction = directions
        batch = MatchBatch(existing_group_ids=targets, new_unit_ids=sources)
        scores: dict[tuple[str, str], tuple[float, str]] = {}
        limit = self.config.shortlist
        for source_id in sources:
            candidates = eligible[source_id]
            if limit and len(candidates) > limit:
                # One ranking over every option narrows the yes/no questions to the top
                # few; the reverse direction reads the same (narrower) yes table.
                candidates = self._shortlist(
                    stage,
                    insertion,
                    scope,
                    direction=forward_direction,
                    source_id=source_id,
                    options=candidates,
                    limit=limit,
                    focus=source_context(source_id, False),
                    option_context=lambda t: target_context(t, True),
                )
            for target_id in candidates:
                vote = dict(
                    direction=forward_direction,
                    source_id=source_id,
                    allowed_ids=[target_id],
                    context={
                        "scope": scope,
                        "focus": source_context(source_id, False),
                        "candidates": [target_context(target_id, True)],
                    },
                )
                # Both complete papers, always: an oversized question goes to Jev's long
                # context window, and if even that is too large the run stops. The node is
                # never shrunk to its member sections.
                attempt_id, result = self._vote(
                    stage, insertion, key_suffix=f":pair:{target_id}", **vote
                )
                score = result.raw_response["jev"]["has_match"]["noul"]
                self.journal.event(
                    "pair_scored",
                    paper_index=insertion.paper_index,
                    level=scope["level"],
                    parent_id=scope.get("parent_group_id"),
                    source_id=source_id,
                    target_id=target_id,
                    score=score,
                    attempt_id=attempt_id,
                )
                if result.normalized.get("target_id") == target_id:
                    scores[source_id, target_id] = (score, attempt_id)

        for source_id in sources:
            options = {
                t: scores[source_id, t] for t in eligible[source_id] if (source_id, t) in scores
            }
            decision = self._choose_passed(
                stage,
                insertion,
                scope,
                direction=forward_direction,
                source_id=source_id,
                options=options,
                focus=source_context(source_id, False),
                option_context=lambda t: target_context(t, True),
            )
            if decision:
                batch.forward[source_id] = decision
        for target_id in targets:
            options = {
                s: scores[s, target_id]
                for s in sources
                if (s, target_id) in scores and reverse_eligible(s, target_id)
            }
            decision = self._choose_passed(
                stage,
                insertion,
                scope,
                direction=reverse_direction,
                source_id=target_id,
                options=options,
                focus=target_context(target_id, False),
                option_context=lambda s: source_context(s, True),
            )
            if decision:
                batch.reverse[target_id] = decision
        return batch

    def _shortlist(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        scope: dict[str, Any],
        *,
        direction: MatchDirection,
        source_id: str,
        options: list[str],
        limit: int,
        focus: dict[str, Any],
        option_context: Callable[[str], dict[str, Any]],
        suffix: str = ":shortlist",
    ) -> list[str]:
        """Keep the ``limit`` options a single Jev ranking finds most likely.

        The ranking shows the focus's complete paper and each option's members and role,
        like the ranking among yeses; it needs recall, not a decision, so no close-call
        rule applies. A pool over Jev's option or size limit is shortlisted in halves.
        """
        if len(options) <= limit:
            return list(options)
        if len(options) > 255:
            middle = len(options) // 2
            halves = [options[:middle], options[middle:]]
        else:
            try:
                attempt_id, result = self._vote(
                    stage,
                    insertion,
                    direction=direction,
                    source_id=source_id,
                    allowed_ids=options,
                    context={
                        "scope": scope,
                        "focus": focus,
                        "candidates": [option_context(option) for option in options],
                    },
                    rank_only=True,
                    key_suffix=suffix,
                    candidate_papers=False,
                )
            except JevRequestTooLarge:
                if len(options) <= 2 * limit:
                    raise
                middle = len(options) // 2
                halves = [options[:middle], options[middle:]]
            else:
                probabilities = result.raw_response["jev"]["choice"]["probabilities"]
                order = {option: index for index, option in enumerate(options)}
                kept = sorted(options, key=lambda o: (-probabilities[o], order[o]))[:limit]
                self.journal.event(
                    "shortlisted",
                    paper_index=insertion.paper_index,
                    level=scope["level"],
                    parent_id=scope.get("parent_group_id"),
                    direction=direction,
                    source_id=source_id,
                    candidate_count=len(options),
                    kept=kept,
                    probabilities=probabilities,
                    attempt_id=attempt_id,
                )
                return [option for option in options if option in kept]
        merged = [
            option
            for index, half in enumerate(halves)
            for option in self._shortlist(
                stage,
                insertion,
                scope,
                direction=direction,
                source_id=source_id,
                options=half,
                limit=limit,
                focus=focus,
                option_context=option_context,
                suffix=f"{suffix}:{index}",
            )
        ]
        return self._shortlist(
            stage,
            insertion,
            scope,
            direction=direction,
            source_id=source_id,
            options=merged,
            limit=limit,
            focus=focus,
            option_context=option_context,
            suffix=f"{suffix}:final",
        )

    def _choose_passed(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        scope: dict[str, Any],
        *,
        direction: MatchDirection,
        source_id: str,
        options: dict[str, tuple[float, str]],
        focus: dict[str, Any],
        option_context: Callable[[str], dict[str, Any]],
    ) -> MatchDecision | None:
        # Gate scores come from separate requests, so they are not compared with each
        # other; a comparative ranking question decides among every option that passed.
        # Passing options can come from many papers and Jev's context holds about two,
        # so the ranking shows the focus's complete paper and each option's own
        # members and roles only.
        if not options:
            return None
        passed = sorted(options)
        if len(passed) == 1:
            target_id, attempt_id = passed[0], options[passed[0]][1]
        else:
            target_id, attempt_id = self._rank_passed(
                stage,
                insertion,
                scope,
                direction=direction,
                source_id=source_id,
                passed=passed,
                focus=focus,
                option_context=option_context,
            )
        return self._record_decision(
            insertion,
            scope,
            direction=direction,
            source_id=source_id,
            target_id=target_id,
            candidate_ids=sorted(options),
            attempt_id=attempt_id,
            pair_scores={option: score for option, (score, _) in sorted(options.items())},
            choice_ids=passed if len(passed) > 1 else [],
        )

    def _rank_passed(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        scope: dict[str, Any],
        *,
        direction: MatchDirection,
        source_id: str,
        passed: list[str],
        focus: dict[str, Any],
        option_context: Callable[[str], dict[str, Any]],
        suffix: str = ":choice",
        resolve_close_calls: bool = True,
    ) -> tuple[str | None, str]:
        """Rank every passed option at once; halve the pool only if Jev rejects its size.

        Each half's winner goes to a final ranking. No source text is truncated. Only the
        final ranking can be held as a close call; a close half still sends its winner on.
        """
        if len(passed) == 1:
            return passed[0], ""  # A half with one option needs no question.
        try:
            attempt_id, result = self._ranked_vote(
                stage,
                insertion,
                resolve_close_calls=resolve_close_calls,
                direction=direction,
                source_id=source_id,
                allowed_ids=passed,
                context={
                    "scope": scope,
                    "focus": focus,
                    "candidates": [option_context(option) for option in passed],
                },
                rank_only=True,
                key_suffix=suffix,
                candidate_papers=False,
            )
            return result.normalized["target_id"], attempt_id
        except JevRequestTooLarge:
            if len(passed) <= 2:
                raise
        middle = len(passed) // 2
        finalists = sorted(
            self._rank_passed(
                stage,
                insertion,
                scope,
                direction=direction,
                source_id=source_id,
                passed=half,
                focus=focus,
                option_context=option_context,
                suffix=f"{suffix}:{index}",
                resolve_close_calls=False,
            )[0]
            for index, half in enumerate((passed[:middle], passed[middle:]))
        )
        return self._rank_passed(
            stage,
            insertion,
            scope,
            direction=direction,
            source_id=source_id,
            passed=finalists,
            focus=focus,
            option_context=option_context,
            suffix=f"{suffix}:final",
            resolve_close_calls=resolve_close_calls,
        )

    def _reconcile(
        self,
        insertion: InsertionState,
        *,
        level: str,
        parent_id: str | None,
        batch: MatchBatch,
    ) -> dict[str, str]:
        assignments: dict[str, str] = {}
        reciprocal = reciprocal_matches(batch)
        fan_in = self._fan_in(level)
        forward_fan_in = (
            adjacent_paragraph_fan_in(
                batch,
                reciprocal,
                {
                    unit_id: self._adjacency_position(insertion.paper.paper_id, unit_id, level)
                    for unit_id in batch.new_unit_ids
                },
            )
            if fan_in
            else {}
        )
        reverse_fan_in = {}
        if fan_in:
            reverse_fan_in = self._adjacent_existing_group_fan_in(batch, reciprocal)
            for source_id in sorted(reverse_fan_in):
                target_id, selected_unit_id, anchors = reverse_fan_in[source_id]
                moved = self.role_graph.merge_paragraph_group(
                    source_id,
                    target_id,
                    paper_index=insertion.paper_index,
                )
                if level == "section":
                    insertion.absorbed_sections.extend(
                        {
                            "paper_id": member["paper_id"],
                            "unit_id": member["unit_id"],
                            "target_group_id": target_id,
                        }
                        for member in moved
                        if member["paper_id"] != insertion.paper.paper_id
                    )
                for member in moved:
                    owner = self.insertions_by_paper[member["paper_id"]]
                    (
                        owner.section_assignments
                        if level == "section"
                        else owner.paragraph_assignments
                    )[member["unit_id"]] = target_id
                    anchor = anchors[(member["paper_id"], member["unit_id"])]
                    self.journal.event(
                        f"{level}_fan_in_added",
                        paper_index=insertion.paper_index,
                        inserted_paper_id=insertion.paper.paper_id,
                        paper_id=member["paper_id"],
                        node_id=target_id,
                        parent_id=parent_id,
                        unit_id=member["unit_id"],
                        reciprocal_unit_id=anchor["unit_id"],
                        selected_unit_id=selected_unit_id,
                        direction="group_to_new",
                        source_group_id=source_id,
                        attempt_id=batch.reverse[source_id].attempt_id,
                    )
        # Insert reciprocal cores before moving their existing singleton neighbors.
        for unit_id in sorted(batch.new_unit_ids, key=lambda unit: unit not in reciprocal):
            previous_group = (
                insertion.paragraph_assignments.get(unit_id) if level == "paragraph" else None
            )
            selected_group = reciprocal.get(unit_id) or forward_fan_in.get(unit_id)
            if selected_group:
                assignments[unit_id] = selected_group
                metadata = self.evidence.member_metadata(insertion, unit_id, level)
                if fan_in:
                    metadata["membership_role"] = "fan_in" if unit_id in forward_fan_in else "core"
                if previous_group:
                    if unit_id in forward_fan_in:
                        self.role_graph.merge_paragraph_group(
                            previous_group, selected_group, paper_index=insertion.paper_index
                        )
                    else:
                        self.role_graph.merge_singleton(
                            previous_group,
                            selected_group,
                            paper_index=insertion.paper_index,
                            attempt_id=batch.forward[unit_id].attempt_id,
                            reverse_attempt_id=batch.reverse[selected_group].attempt_id,
                            recursive=True,
                        )
                else:
                    self.role_graph.add_member(
                        selected_group,
                        unit_id,
                        insertion.paper.paper_id,
                        insertion.paper_index,
                        self.evidence.unit_ordinal(insertion.paper.paper_id, unit_id, level),
                        **metadata,
                    )
                if unit_id in forward_fan_in:
                    anchor_unit_id = next(
                        anchor_id
                        for anchor_id, group_id in reciprocal.items()
                        if group_id == selected_group
                    )
                    self.journal.event(
                        f"{level}_fan_in_added",
                        paper_index=insertion.paper_index,
                        inserted_paper_id=insertion.paper.paper_id,
                        paper_id=insertion.paper.paper_id,
                        node_id=selected_group,
                        parent_id=parent_id,
                        unit_id=unit_id,
                        reciprocal_unit_id=anchor_unit_id,
                        direction="new_to_group",
                        attempt_id=batch.forward[unit_id].attempt_id,
                    )
            else:
                if previous_group:
                    assignments[unit_id] = previous_group
                    continue
                metadata = self.evidence.member_metadata(insertion, unit_id, level)
                if level == "paragraph":
                    metadata["membership_role"] = "core"
                group_id = self.role_graph.create_group(
                    level=level,
                    parent_id=parent_id,
                    member_id=unit_id,
                    paper_id=insertion.paper.paper_id,
                    paper_index=insertion.paper_index,
                    ordinal=self.evidence.unit_ordinal(insertion.paper.paper_id, unit_id, level),
                    **metadata,
                )
                assignments[unit_id] = group_id

        for group_id, decision in batch.reverse.items():
            if group_id in reverse_fan_in:
                continue
            unit_id = decision.target_id
            absorbed_group = reciprocal.get(unit_id) if unit_id else None
            if absorbed_group and absorbed_group != group_id:
                self.journal.event(
                    "projected_edge_ignored",
                    paper_index=insertion.paper_index,
                    level=level,
                    parent_id=parent_id,
                    source_group_id=group_id,
                    selected_unit_id=unit_id,
                    absorbed_group_id=absorbed_group,
                    attempt_id=decision.attempt_id,
                )
        return assignments

    def _adjacency_position(self, paper_id: str, unit_id: str, level: str) -> int:
        """Position where ±1 means next-door in the same section.

        Paragraph ordinals restart in every section, and one batch can hold two sections
        of a paper, so a gap keeps paragraphs of different sections from looking adjacent.
        """
        if level == "section":
            return self.evidence.unit_ordinal(paper_id, unit_id, level)
        section, paragraph = self.evidence.paragraph_lookup[(paper_id, unit_id)]
        return section.ordinal * 1_000_000 + paragraph.ordinal

    def _adjacent_existing_group_fan_in(
        self,
        batch: MatchBatch,
        reciprocal: dict[str, str],
    ) -> dict[
        str,
        tuple[str, str, dict[tuple[str, str], dict[str, Any]]],
    ]:
        """Find existing paragraph nodes directly adjacent to reciprocal nodes."""

        accepted = {}
        for source_id, decision in batch.reverse.items():
            selected_unit_id = decision.target_id
            target_id = reciprocal.get(selected_unit_id or "")
            if target_id is None or source_id == target_id:
                continue
            anchors = adjacent_core_anchors(
                self.role_graph.members(source_id), self.role_graph.members(target_id)
            )
            if anchors is not None:
                accepted[source_id] = (target_id, selected_unit_id, anchors)
        return accepted

    def _generate_group_role_statements(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        level: str,
        *,
        group_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        self._require_prompt(stage)
        results = []
        selected_ids = (
            [group_id for group_id, _ in self.role_graph.nodes(level)]
            if group_ids is None
            else sorted(group_ids)
        )
        for group_id in selected_ids:
            group = self.evidence.group_context(group_id)
            if len(group["members"]) == 1:
                role_statement = str(group["members"][0]["role_statement"]).strip()
                self.role_graph.set_role_statement(
                    group_id,
                    role_statement,
                    insertion.paper_index,
                    None,
                    source="member_role_statement",
                )
                results.append(
                    {
                        "group_id": group_id,
                        "role_statement": role_statement,
                        "source": "member_role_statement",
                    }
                )
                continue
            group.pop("role_statement", None)
            context = {
                "scope": self.evidence.scope_context(
                    level, self.role_graph.node(group_id).get("parent_id")
                ),
                "group": group,
                "latest_paper": self.evidence.latest_paper_context(group_id),
            }
            role_statement, attempt_id = self._role_statement(stage, insertion, group_id, context)
            self.role_graph.set_role_statement(
                group_id, role_statement, insertion.paper_index, attempt_id
            )
            results.append(
                {
                    "group_id": group_id,
                    "role_statement": role_statement,
                    "source": "model",
                    "attempt_id": attempt_id,
                }
            )
        return results

    def _forced(self, stage: StageConfig, insertion: InsertionState) -> bool:
        return self.force_paper_index == insertion.paper_index and self.force_stage_id == stage.id

    @staticmethod
    def _require_prompt(stage: StageConfig) -> None:
        if not stage.prompt or not stage.context:
            raise PipelineError(f"Stage {stage.id} requires prompt and context references")
        if not stage.skill:
            raise PipelineError(f"Stage {stage.id} requires a role_statement Skill")

    @staticmethod
    def _require_match_prompts(stage: StageConfig) -> None:
        required = {"new_to_group", "group_to_new"}
        if not required.issubset(stage.prompts) or not required.issubset(stage.contexts):
            raise PipelineError(
                f"Stage {stage.id} requires new_to_group and group_to_new prompt/context entries"
            )
        if not stage.skill:
            raise PipelineError(f"Stage {stage.id} requires a matching Skill")

    @staticmethod
    def _match_batch_dump(batch: MatchBatch) -> dict[str, Any]:
        return {
            "existing_group_ids": batch.existing_group_ids,
            "new_unit_ids": batch.new_unit_ids,
            "forward": {key: value.model_dump(mode="json") for key, value in batch.forward.items()},
            "reverse": {key: value.model_dump(mode="json") for key, value in batch.reverse.items()},
        }
