"""Structured representation for one paper, modeled on Gentner's structure-mapping
representations: entities (objects/concepts) plus propositions (labeled relations)
that can connect entities directly (first-order) or connect other propositions
(higher-order, e.g. a causal/motivational relation between two claims).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

ENTITY_KINDS = [
    "method", "system", "tool", "dataset", "population", "concept",
    "phenomenon", "artifact", "metric", "problem", "claim",
]

SUGGESTED_PREDICATES = [
    "motivates", "addresses", "causes", "enables", "requires", "uses",
    "produces", "evaluates", "measures", "compares", "contrasts-with",
    "extends", "is-instance-of", "has-property", "part-of", "applies-to",
    "results-in", "supports", "contradicts",
]


class Entity(BaseModel):
    id: str = Field(description="short stable id, e.g. 'e1'")
    name: str = Field(description="concise name of the object/concept")
    kind: str = Field(description=f"category of entity, e.g. one of {ENTITY_KINDS} (or a close variant)")


class Proposition(BaseModel):
    id: str = Field(description="short stable id, e.g. 'p1'")
    predicate: str = Field(
        description=f"the relation name connecting the args, e.g. one of {SUGGESTED_PREDICATES} (or a close variant)"
    )
    args: list[str] = Field(
        description=(
            "ordered list of ids this predicate connects. Each id must refer to an "
            "Entity.id or another Proposition.id -- referencing a Proposition makes "
            "this a higher-order relation."
        )
    )
    evidence: str = Field(description="a short quote or tight paraphrase (<25 words) from the paper supporting this")


class PaperGraph(BaseModel):
    paper_id: str
    title: str
    entities: list[Entity]
    propositions: list[Proposition]

    def proposition_orders(self) -> dict[str, int]:
        """order 0 = connects only entities; order N = connects a proposition of order N-1."""
        by_id = {p.id: p for p in self.propositions}
        entity_ids = {e.id for e in self.entities}
        memo: dict[str, int] = {}

        def order_of(pid: str, stack: tuple[str, ...] = ()) -> int:
            if pid in memo:
                return memo[pid]
            if pid in stack:
                return 0  # guard against cycles in malformed extractions
            prop = by_id.get(pid)
            if prop is None:
                return 0
            arg_orders = []
            for a in prop.args:
                if a in entity_ids:
                    arg_orders.append(0)
                elif a in by_id:
                    arg_orders.append(order_of(a, stack + (pid,)) + 1)
            result = max(arg_orders, default=0)
            memo[pid] = result
            return result

        return {p.id: order_of(p.id) for p in self.propositions}

    def systematicity_summary(self) -> dict[str, float]:
        orders = self.proposition_orders()
        if not orders:
            return {"num_propositions": 0, "max_order": 0, "mean_order": 0.0}
        return {
            "num_propositions": len(orders),
            "max_order": max(orders.values()),
            "mean_order": sum(orders.values()) / len(orders),
        }
