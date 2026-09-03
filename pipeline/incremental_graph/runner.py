"""Execute the configured incremental mapping stages in paper insertion order."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..document import QUESTION_FIELD
from .export import export_revision
from .graph import QuestionGraph
from .journal import RevisionJournal, write_json
from .llm import JudgmentProvider
from .models import (
    InsertionState,
    JudgmentRequest,
    MatchBatch,
    MatchDecision,
    MatchDirection,
    Paper,
    Phase,
    PipelineConfig,
    StageConfig,
)


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
        force_paper_index: int | None = None,
        force_stage_id: str | None = None,
    ):
        self.config = config
        self.judge = judge
        self.revision_dir = revision_dir
        self.revision_dir.mkdir(parents=True, exist_ok=False)
        self.force_paper_index = force_paper_index
        self.force_stage_id = force_stage_id
        self.journal = RevisionJournal(revision_dir)
        self.question_graph = QuestionGraph(self.journal)
        self.papers: list[Paper] = []
        self.insertions_by_paper: dict[str, InsertionState] = {}
        self.section_lookup: dict[tuple[str, str], Any] = {}
        self.paragraph_lookup: dict[tuple[str, str], tuple[Any, Any]] = {}
        self.handlers: dict[str, Callable[[StageConfig, InsertionState], Any]] = {
            "ingest_paper": self._ingest_paper,
            "generate_section_questions": self._generate_section_questions,
            "match_sections": self._match_sections,
            "reconcile_sections": self._reconcile_sections,
            "generate_section_group_questions": self._generate_section_group_questions,
            "rerepresent_section_singletons": self._rerepresent_section_singletons,
            "regenerate_rerepresented_section_questions": (
                self._regenerate_rerepresented_section_questions
            ),
            "generate_paragraph_questions": self._generate_paragraph_questions,
            "match_paragraphs": self._match_paragraphs,
            "reconcile_paragraphs": self._reconcile_paragraphs,
            "generate_paragraph_group_questions": self._generate_paragraph_group_questions,
        }

    def run(self, papers: list[Paper]) -> dict[str, Any]:
        insertions: list[InsertionState] = []
        for paper_index, paper in enumerate(papers, start=1):
            self._register_paper(paper)
            insertion = InsertionState(paper=paper, paper_index=paper_index)
            insertions.append(insertion)
            self.insertions_by_paper[paper.paper_id] = insertion
            self._run_phase("structural", insertion)
        if insertions:
            self._run_phase("rerepresentation", insertions[-1])
        for insertion in insertions:
            self._run_phase("paragraph", insertion)
        self.journal.finalize()
        export_revision(self.revision_dir / "dataset", self.question_graph, self.papers)
        summary = {
            "schema_version": 1,
            "pipeline_id": self.config.pipeline_id,
            "paper_count": len(self.papers),
            "paper_order": [paper.paper_id for paper in self.papers],
            "graph_hash": self.question_graph.graph_hash(),
            "event_count": len(self.journal.events),
            "attempt_count": self.journal.attempt_count,
            "dataset_dir": str((self.revision_dir / "dataset").resolve()),
        }
        write_json(self.revision_dir / "summary.json", summary)
        return summary

    def _run_phase(self, phase: Phase, insertion: InsertionState) -> None:
        for stage in (stage for stage in self.config.stages if stage.phase == phase):
            handler = self.handlers.get(stage.handler)
            if handler is None:
                raise PipelineError(f"Unknown stage handler {stage.handler!r} for stage {stage.id}")
            result = handler(stage, insertion)
            insertion.stage_results[stage.id] = result
            self.journal.stage(insertion.paper_index, stage.id, result)

    def _register_paper(self, paper: Paper) -> None:
        self.papers.append(paper)
        for section in paper.sections:
            self.section_lookup[(paper.paper_id, section.id)] = section
            for paragraph in section.paragraphs:
                self.paragraph_lookup[(paper.paper_id, paragraph.id)] = (section, paragraph)

    def _ingest_paper(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        self.question_graph.add_paper(insertion.paper.paper_id, insertion.paper.title, insertion.paper_index)
        return {
            "paper_id": insertion.paper.paper_id,
            "sections": len(insertion.paper.sections),
            "paragraphs": sum(len(section.paragraphs) for section in insertion.paper.sections),
        }

    def _generate_section_questions(self, stage: StageConfig, insertion: InsertionState) -> list[dict[str, str]]:
        self._require_prompt(stage)
        results = []
        for section in insertion.paper.sections:
            if section.question:
                results.append({"section_id": section.id, "question": section.question, "source": "input"})
                continue
            context = {
                "paper": {"paper_id": insertion.paper.paper_id, "title": insertion.paper.title},
                "section": self._section_context(insertion.paper.paper_id, section.id),
            }
            question, attempt_id = self._question(stage, insertion, section.id, context)
            section.question = question
            results.append({
                "section_id": section.id,
                "question": question,
                "source": "model",
                "attempt_id": attempt_id,
            })
        return results

    def _match_sections(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        existing = self.question_graph.group_ids("section")
        unit_ids = [section.id for section in insertion.paper.sections]
        insertion.section_matches = self._match_units(stage, insertion, "section", None, unit_ids, existing)
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
        for unit in insertion.paper.sections:
            if unit.parent_id:
                self.question_graph.add_hierarchy_edge(
                    insertion.section_assignments[unit.parent_id],
                    insertion.section_assignments[unit.id],
                    paper_id=insertion.paper.paper_id,
                    paper_index=insertion.paper_index,
                )
        return insertion.section_assignments

    def _generate_section_group_questions(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._generate_group_questions(stage, insertion, "section")

    def _rerepresent_section_singletons(
        self, stage: StageConfig, insertion: InsertionState
    ) -> dict[str, Any]:
        """Run one frozen singleton-to-established-node structural match pass."""

        self._require_match_direction(stage, "singleton_to_group")
        frozen_nodes = list(self.question_graph.nodes("section"))
        singleton_ids = [
            node_id for node_id, data in frozen_nodes if len(data["members"]) == 1
        ]
        established_ids = [
            node_id for node_id, data in frozen_nodes if len(data["members"]) > 1
        ]
        decisions: dict[str, MatchDecision] = {}
        candidates_by_singleton: dict[str, list[str]] = {}

        for source_id in singleton_ids:
            member = self.question_graph.members(source_id)[0]
            candidate_ids = [
                target_id
                for target_id in established_ids
                if not any(
                    target_member["paper_id"] == member["paper_id"]
                    for target_member in self.question_graph.members(target_id)
                )
            ]
            candidates_by_singleton[source_id] = candidate_ids
            if not candidate_ids:
                continue
            context = {
                "scope": {
                    **self._scope_context("section", None),
                    "match_mode": "rerepresentation",
                },
                "focus": self._group_context(source_id),
                "candidates": [self._group_context(group_id) for group_id in candidate_ids],
            }
            decisions[source_id] = self._match(
                stage,
                insertion,
                direction="singleton_to_group",
                source_id=source_id,
                allowed_ids=candidate_ids,
                context=context,
                key_prefix="corpus",
            )

        merged = []
        ignored = []
        changed_group_ids: set[str] = set()
        for source_id in singleton_ids:
            decision = decisions.get(source_id)
            target_id = decision.target_id if decision else None
            if target_id is None:
                continue
            member = self.question_graph.members(source_id)[0]
            if any(
                target_member["paper_id"] == member["paper_id"]
                for target_member in self.question_graph.members(target_id)
            ):
                ignored.append(
                    {
                        "source_group_id": source_id,
                        "target_group_id": target_id,
                        "reason": "target_already_contains_paper",
                    }
                )
                self.journal.event(
                    "rerepresentation_merge_ignored",
                    paper_index=insertion.paper_index,
                    source_group_id=source_id,
                    target_group_id=target_id,
                    paper_id=member["paper_id"],
                    reason="target_already_contains_paper",
                    attempt_id=decision.attempt_id,
                )
                continue
            self.question_graph.merge_section_singleton(
                source_id,
                target_id,
                paper_index=insertion.paper_index,
                attempt_id=decision.attempt_id,
            )
            source_insertion = self.insertions_by_paper[member["paper_id"]]
            if source_insertion.section_assignments.get(member["unit_id"]) != source_id:
                raise PipelineError(f"Structural assignment for {source_id} is stale")
            source_insertion.section_assignments[member["unit_id"]] = target_id
            changed_group_ids.add(target_id)
            merged.append(
                {
                    "source_group_id": source_id,
                    "target_group_id": target_id,
                    "paper_id": member["paper_id"],
                    "unit_id": member["unit_id"],
                    "attempt_id": decision.attempt_id,
                }
            )

        return {
            "singleton_ids": singleton_ids,
            "established_group_ids": established_ids,
            "candidates_by_singleton": candidates_by_singleton,
            "decisions": {
                source_id: decision.model_dump(mode="json")
                for source_id, decision in decisions.items()
            },
            "merged": merged,
            "ignored": ignored,
            "changed_group_ids": sorted(changed_group_ids),
        }

    def _regenerate_rerepresented_section_questions(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        rerepresentation = insertion.stage_results.get("section_rerepresentation")
        if rerepresentation is None:
            raise PipelineError(
                "regenerate_rerepresented_section_questions requires section_rerepresentation"
            )
        return self._generate_group_questions(
            stage,
            insertion,
            "section",
            group_ids=rerepresentation["changed_group_ids"],
        )

    def _generate_paragraph_questions(self, stage: StageConfig, insertion: InsertionState) -> list[dict[str, str]]:
        self._require_prompt(stage)
        results = []
        for section in insertion.paper.sections:
            for paragraph in section.paragraphs:
                if paragraph.question:
                    results.append({
                        "paragraph_id": paragraph.id,
                        "question": paragraph.question,
                        "source": "input",
                    })
                    continue
                context = {
                    "paper": {"paper_id": insertion.paper.paper_id, "title": insertion.paper.title},
                    "section": self._section_context(insertion.paper.paper_id, section.id),
                    "paragraph": self._paragraph_context(insertion.paper.paper_id, paragraph.id),
                }
                question, attempt_id = self._question(stage, insertion, paragraph.id, context)
                paragraph.question = question
                results.append({
                    "paragraph_id": paragraph.id,
                    "question": question,
                    "source": "model",
                    "attempt_id": attempt_id,
                })
        return results

    def _match_paragraphs(self, stage: StageConfig, insertion: InsertionState) -> dict[str, Any]:
        if not insertion.section_assignments:
            raise PipelineError("match_paragraphs requires reconcile_sections to run first")
        results = {}
        for unit in insertion.paper.sections:
            structural_group_id = insertion.section_assignments[unit.id]
            unit_ids = [paragraph.id for paragraph in unit.paragraphs]
            existing = self.question_graph.paragraph_groups_for_section(
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
            insertion.paragraph_matches[unit.id] = batch
            results[unit.id] = self._match_batch_dump(batch)
        return results

    def _reconcile_paragraphs(self, stage: StageConfig, insertion: InsertionState) -> dict[str, str]:
        if not insertion.paragraph_matches and any(section.paragraphs for section in insertion.paper.sections):
            raise PipelineError("reconcile_paragraphs requires match_paragraphs to run first")
        assignments = {}
        for unit_id, batch in insertion.paragraph_matches.items():
            assignments.update(self._reconcile(
                insertion,
                level="paragraph",
                parent_id=insertion.section_assignments[unit_id],
                batch=batch,
            ))
        insertion.paragraph_assignments = assignments
        return assignments

    def _generate_paragraph_group_questions(
        self, stage: StageConfig, insertion: InsertionState
    ) -> list[dict[str, str]]:
        return self._generate_group_questions(stage, insertion, "paragraph")

    def _question(
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
            output_kind="question",
            prompt_ref=stage.prompt or "",
            context_ref=stage.context or "",
            context=context,
            skill_ref=stage.skill,
            force=self._forced(stage, insertion),
        )
        result = self.judge.judge(request)
        attempt_id = self.journal.attempt(request, result)
        return str(result.normalized[QUESTION_FIELD]).strip(), attempt_id

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
        scope = self._scope_context(level, parent_id)
        group_candidates = [self._group_context(group_id) for group_id in existing_group_ids]
        unit_candidates = [self._unit_context(insertion.paper.paper_id, unit_id, level) for unit_id in new_unit_ids]

        for unit_id in new_unit_ids:
            if not existing_group_ids:
                continue
            context = {
                "scope": scope,
                "focus": self._unit_context(insertion.paper.paper_id, unit_id, level),
                "candidates": group_candidates,
            }
            decision = self._match(
                stage,
                insertion,
                direction="new_to_group",
                source_id=unit_id,
                allowed_ids=existing_group_ids,
                context=context,
            )
            batch.forward[unit_id] = decision

        for group_id in existing_group_ids:
            if not new_unit_ids:
                continue
            context = {
                "scope": scope,
                "focus": self._group_context(group_id),
                "candidates": unit_candidates,
            }
            decision = self._match(
                stage,
                insertion,
                direction="group_to_new",
                source_id=group_id,
                allowed_ids=new_unit_ids,
                context=context,
            )
            batch.reverse[group_id] = decision
        return batch

    def _match(
        self,
        stage: StageConfig,
        insertion: InsertionState,
        *,
        direction: MatchDirection,
        source_id: str,
        allowed_ids: list[str],
        context: dict[str, Any],
        key_prefix: str | None = None,
    ) -> MatchDecision:
        request = JudgmentRequest(
            key=f"{key_prefix or insertion.paper.paper_id}:{stage.id}:{direction}:{source_id}",
            paper_index=insertion.paper_index,
            stage_id=stage.id,
            output_kind="match",
            prompt_ref=stage.prompts[direction],
            context_ref=stage.contexts[direction],
            context=context,
            allowed_match_ids=allowed_ids,
            skill_ref=stage.skill,
            force=self._forced(stage, insertion),
        )
        result = self.judge.judge(request)
        attempt_id = self.journal.attempt(request, result)
        target_id = result.normalized.get("target_id")
        self.journal.event(
            "match_recorded",
            paper_index=insertion.paper_index,
            level=context["scope"]["level"],
            parent_id=context["scope"].get("parent_group_id"),
            direction=direction,
            source_id=source_id,
            target_id=target_id,
            candidate_ids=allowed_ids,
            attempt_id=attempt_id,
        )
        return MatchDecision(
            source_id=source_id,
            target_id=target_id,
            direction=direction,
            attempt_id=attempt_id,
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
        reciprocal = self._reciprocal_matches(batch)
        forward_fan_in = (
            self._adjacent_paragraph_fan_in(insertion, batch, reciprocal)
            if level == "paragraph"
            else {}
        )
        reverse_fan_in = {}
        if level == "paragraph":
            reverse_fan_in = self._adjacent_existing_group_fan_in(batch, reciprocal)
            for source_id in sorted(reverse_fan_in):
                target_id, selected_unit_id, anchors = reverse_fan_in[source_id]
                moved = self.question_graph.merge_paragraph_group(
                    source_id,
                    target_id,
                    paper_index=insertion.paper_index,
                )
                for member in moved:
                    anchor = anchors[(member["paper_id"], member["unit_id"])]
                    self.journal.event(
                        "paragraph_fan_in_added",
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
        for unit_id in batch.new_unit_ids:
            selected_group = reciprocal.get(unit_id) or forward_fan_in.get(unit_id)
            if selected_group:
                assignments[unit_id] = selected_group
                metadata = self._member_metadata(insertion, unit_id, level)
                if level == "paragraph":
                    metadata["membership_role"] = (
                        "fan_in" if unit_id in forward_fan_in else "core"
                    )
                self.question_graph.add_member(
                    selected_group,
                    unit_id,
                    insertion.paper.paper_id,
                    insertion.paper_index,
                    self._unit_ordinal(insertion.paper.paper_id, unit_id, level),
                    **metadata,
                )
                if unit_id in forward_fan_in:
                    anchor_unit_id = next(
                        anchor_id
                        for anchor_id, group_id in reciprocal.items()
                        if group_id == selected_group
                    )
                    self.journal.event(
                        "paragraph_fan_in_added",
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
                metadata = self._member_metadata(insertion, unit_id, level)
                if level == "paragraph":
                    metadata["membership_role"] = "core"
                group_id = self.question_graph.create_group(
                    level=level,
                    parent_id=parent_id,
                    member_id=unit_id,
                    paper_id=insertion.paper.paper_id,
                    paper_index=insertion.paper_index,
                    ordinal=self._unit_ordinal(insertion.paper.paper_id, unit_id, level),
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

    @staticmethod
    def _reciprocal_matches(batch: MatchBatch) -> dict[str, str]:
        reciprocal: dict[str, str] = {}
        for unit_id, forward in batch.forward.items():
            if not forward.target_id:
                continue
            reverse = batch.reverse.get(forward.target_id)
            if reverse and reverse.target_id == unit_id:
                reciprocal[unit_id] = forward.target_id
        return reciprocal

    def _adjacent_paragraph_fan_in(
        self,
        insertion: InsertionState,
        batch: MatchBatch,
        reciprocal: dict[str, str],
    ) -> dict[str, str]:
        """Attach only one-way paragraphs immediately beside a reciprocal anchor."""

        anchor_by_group = {group_id: unit_id for unit_id, group_id in reciprocal.items()}
        accepted: dict[str, str] = {}
        for unit_id, forward in batch.forward.items():
            selected_group = forward.target_id
            anchor_id = anchor_by_group.get(selected_group or "")
            if unit_id in reciprocal or anchor_id is None:
                continue
            ordinal = self._unit_ordinal(insertion.paper.paper_id, unit_id, "paragraph")
            anchor_ordinal = self._unit_ordinal(
                insertion.paper.paper_id, anchor_id, "paragraph"
            )
            if abs(ordinal - anchor_ordinal) == 1 and selected_group is not None:
                accepted[unit_id] = selected_group
        return accepted

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
            anchors = self._adjacent_core_anchors(source_id, target_id)
            if anchors is not None:
                accepted[source_id] = (target_id, selected_unit_id, anchors)
        return accepted

    def _adjacent_core_anchors(
        self,
        source_id: str,
        target_id: str,
    ) -> dict[tuple[str, str], dict[str, Any]] | None:
        target_members = [
            member
            for member in self.question_graph.members(target_id)
            if member.get("membership_role") != "fan_in"
        ]
        anchors = {}
        for member in self.question_graph.members(source_id):
            candidates = [
                target
                for target in target_members
                if target["paper_id"] == member["paper_id"]
                and target.get("owner_group_id") == member.get("owner_group_id")
                and abs(target["ordinal"] - member["ordinal"]) == 1
            ]
            if not candidates:
                return None
            anchors[(member["paper_id"], member["unit_id"])] = min(
                candidates,
                key=lambda item: (item["ordinal"], item["unit_id"]),
            )
        return anchors

    def _generate_group_questions(
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
            [group_id for group_id, _ in self.question_graph.nodes(level)]
            if group_ids is None
            else sorted(group_ids)
        )
        for group_id in selected_ids:
            group = self._group_context(group_id)
            if len(group["members"]) == 1:
                question = str(group["members"][0]["generated_question_metadata"]).strip()
                self.question_graph.set_question(
                    group_id,
                    question,
                    insertion.paper_index,
                    None,
                    source="member_question",
                )
                results.append({
                    "group_id": group_id,
                    "question": question,
                    "source": "member_question",
                })
                continue
            group.pop("generated_question_metadata", None)
            context = {
                "scope": self._scope_context(
                    level, self.question_graph.graph.nodes[group_id].get("parent_id")
                ),
                "group": group,
            }
            question, attempt_id = self._question(stage, insertion, group_id, context)
            self.question_graph.set_question(group_id, question, insertion.paper_index, attempt_id)
            results.append({
                "group_id": group_id,
                "question": question,
                "source": "model",
                "attempt_id": attempt_id,
            })
        return results

    def _group_context(self, group_id: str) -> dict[str, Any]:
        data = self.question_graph.graph.nodes[group_id]
        return {
            "group_id": group_id,
            "generated_question_metadata": data.get("generated_question", ""),
            "members": [
                self._unit_context(member["paper_id"], member["unit_id"], data["level"])
                for member in data["members"]
            ],
        }

    def _unit_context(self, paper_id: str, unit_id: str, level: str) -> dict[str, Any]:
        if level == "section":
            return self._section_context(paper_id, unit_id)
        return self._paragraph_context(paper_id, unit_id)

    def _unit_ordinal(self, paper_id: str, unit_id: str, level: str) -> int:
        if level == "section":
            return self.section_lookup[(paper_id, unit_id)].ordinal
        return self.paragraph_lookup[(paper_id, unit_id)][1].ordinal

    def _member_metadata(self, insertion: InsertionState, unit_id: str, level: str) -> dict[str, Any]:
        if level == "section":
            unit = self.section_lookup[(insertion.paper.paper_id, unit_id)]
            return {
                "unit_kind": unit.kind,
                "parent_unit_id": unit.parent_id,
                "family_id": unit.family_id,
            }
        owner, _ = self.paragraph_lookup[(insertion.paper.paper_id, unit_id)]
        return {
            "unit_kind": "paragraph",
            "parent_unit_id": owner.id,
            "family_id": owner.family_id,
            "owner_group_id": insertion.section_assignments[owner.id],
        }

    def _section_context(self, paper_id: str, section_id: str) -> dict[str, Any]:
        section = self.section_lookup[(paper_id, section_id)]
        return {
            "paper_id": paper_id,
            "section_id": section.id,
            "section_label": section.label,
            "unit_kind": section.kind,
            "parent_unit_id": section.parent_id,
            "family_id": section.family_id,
            "ordinal": section.ordinal,
            "generated_question_metadata": section.question,
            "full_text": section.text,
        }

    def _paragraph_context(self, paper_id: str, paragraph_id: str) -> dict[str, Any]:
        section, paragraph = self.paragraph_lookup[(paper_id, paragraph_id)]
        return {
            "paper_id": paper_id,
            "paragraph_id": paragraph.id,
            "paragraph_label": paragraph.label,
            "ordinal": paragraph.ordinal,
            "generated_question_metadata": paragraph.question,
            "full_text": paragraph.text,
            "parent_section": {
                "section_id": section.id,
                "section_label": section.label,
                "unit_kind": section.kind,
                "family_id": section.family_id,
                "generated_question_metadata": section.question,
            },
        }

    def _scope_context(self, level: str, parent_id: str | None) -> dict[str, Any]:
        scope = {"level": level, "parent_group_id": parent_id}
        if parent_id:
            scope["parent_group_question_metadata"] = self.question_graph.graph.nodes[parent_id].get(
                "generated_question", ""
            )
        return scope

    def _forced(self, stage: StageConfig, insertion: InsertionState) -> bool:
        return self.force_paper_index == insertion.paper_index and self.force_stage_id == stage.id

    @staticmethod
    def _require_prompt(stage: StageConfig) -> None:
        if not stage.prompt or not stage.context:
            raise PipelineError(f"Stage {stage.id} requires prompt and context references")
        if not stage.skill:
            raise PipelineError(f"Stage {stage.id} requires a question Skill")

    @staticmethod
    def _require_match_prompts(stage: StageConfig) -> None:
        required = {"new_to_group", "group_to_new"}
        if not required.issubset(stage.prompts) or not required.issubset(stage.contexts):
            raise PipelineError(f"Stage {stage.id} requires new_to_group and group_to_new prompt/context entries")
        if not stage.skill:
            raise PipelineError(f"Stage {stage.id} requires a matching Skill")

    @staticmethod
    def _require_match_direction(stage: StageConfig, direction: MatchDirection) -> None:
        if direction not in stage.prompts or direction not in stage.contexts:
            raise PipelineError(f"Stage {stage.id} requires a {direction} prompt/context entry")
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
