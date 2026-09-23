"""Load and validate config/concepts.yaml into a canonical-concept registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from fa.core.settings import CONFIG_DIR


@dataclass(slots=True)
class Concept:
    key: str
    label: str
    statement: str            # income | balance | cashflow
    period: str               # duration | instant
    unit: str                 # USD | shares | USD/shares | pure
    tags: list[str] = field(default_factory=list)
    formula: str | None = None
    sign: int = 1


@dataclass(slots=True)
class ConceptMap:
    concepts: dict[str, Concept]
    statements: dict[str, list[str]]

    def for_statement(self, name: str) -> list[Concept]:
        return [self.concepts[k] for k in self.statements.get(name, []) if k in self.concepts]


@lru_cache(maxsize=1)
def load_concepts() -> ConceptMap:
    with open(CONFIG_DIR / "concepts.yaml", "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    concepts: dict[str, Concept] = {}
    for key, spec in (raw.get("concepts") or {}).items():
        tags = [t.strip().rstrip("?").strip() for t in (spec.get("tags") or []) if t and str(t).strip() not in ("", "?")]
        concepts[key] = Concept(
            key=key, label=spec.get("label", key), statement=spec.get("statement", "income"), period=spec.get("period", "duration"),
            unit=spec.get("unit", "USD"), tags=tags, formula=spec.get("formula"), sign=int(spec.get("sign", 1)),
        )
    return ConceptMap(concepts=concepts, statements=raw.get("statements") or {})
