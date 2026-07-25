"""Deterministic blast-radius scoring.

No LLM touches this. A judge (or an on-call engineer at 3am) can read rules.yaml
and reproduce any score by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fuse.state import Change, Impact, Severity

RULES_PATH = Path(__file__).with_name("rules.yaml")


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or RULES_PATH).read_text(encoding="utf-8"))


class RiskEngine:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = rules or load_rules()

    def _multiplier(self, change: Change) -> tuple[float, str]:
        table = self.rules["change_kind_multiplier"]
        factor = float(table.get(change.kind, 1.0))
        if change.kind == "retype_column":
            pair = [(change.from_type or "").upper(), (change.to_type or "").upper()]
            if pair in [[a, b] for a, b in self.rules["narrowing_types"]]:
                return 1.0, f"narrowing type change {pair[0]} -> {pair[1]} treated as lossy"
        return factor, f"change kind {change.kind} multiplier x{factor}"

    def score(
        self,
        *,
        change: Change,
        entity_type: str,
        hops: int,
        references_column: bool,
        column_lineage_edge: bool = False,
        tier: str | None = None,
        owners: list[str] | None = None,
        recently_queried: bool = False,
    ) -> tuple[int, Severity, list[str]]:
        rules = self.rules
        reasons: list[str] = []
        total = 0.0

        if references_column:
            total += rules["base"]["hard_column_reference"]
            reasons.append(
                f"+{rules['base']['hard_column_reference']} consumer SQL selects the changed column"
            )
        elif column_lineage_edge:
            total += rules["base"]["column_lineage_edge"]
            reasons.append(
                f"+{rules['base']['column_lineage_edge']} column-level lineage edge in DataHub"
            )
        else:
            total += rules["base"]["table_only_dependency"]
            reasons.append(
                f"+{rules['base']['table_only_dependency']} table-level dependency only"
            )

        bonus = rules["entity_type"].get(entity_type, 0)
        if bonus:
            total += bonus
            reasons.append(f"+{bonus} consumer is a {entity_type}")

        if tier and tier in rules["tier"]:
            total += rules["tier"][tier]
            reasons.append(f"+{rules['tier'][tier]} {tier} asset")

        decay = rules["modifiers"]["per_hop_decay"] * max(hops - 1, 0)
        if decay:
            total -= decay
            reasons.append(f"-{decay} {hops} hops downstream")

        if recently_queried:
            total += rules["modifiers"]["queried_last_30d"]
            reasons.append(f"+{rules['modifiers']['queried_last_30d']} queried in the last 30 days")

        if not owners:
            total += rules["modifiers"]["no_owner"]
            reasons.append(f"+{rules['modifiers']['no_owner']} no owner assigned")

        factor, why = self._multiplier(change)
        total *= factor
        reasons.append(why)

        final = max(0, min(100, round(total)))
        severity = self.severity(final)
        reasons.append(f"= {final} -> {severity}")
        return final, severity, reasons

    def severity(self, score: int) -> Severity:
        thresholds = self.rules["thresholds"]
        if score >= thresholds["BREAKING"]:
            return "BREAKING"
        if score >= thresholds["RISKY"]:
            return "RISKY"
        return "SAFE"


def to_impact(**kwargs: Any) -> Impact:
    """Convenience for tests: score and build an Impact in one call."""
    engine = RiskEngine()
    score, severity, reasons = engine.score(**kwargs)
    return Impact(
        urn=kwargs.get("urn", ""),
        entity_type=kwargs["entity_type"],
        name=kwargs.get("name", ""),
        hops=kwargs["hops"],
        references_column=kwargs["references_column"],
        score=score,
        severity=severity,
        reasons=reasons,
    )
