"""Incident Clock: the reporting deadlines that start when an incident happens.

All deadlines live in ``rules/incidents.yaml``. This module only does the date arithmetic.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .engine import RulebookError, _refs, checker

RULES = Path(__file__).parent / "rules" / "incidents.yaml"
REGIME_NAMES = {"gdpr": "GDPR", "nis2": "NIS2", "dora": "DORA", "ai_act": "AI Act"}


@dataclass(frozen=True)
class Deadline:
    id: str
    regime: str
    report: str
    due: datetime | None  # None means "without undue delay" / "immediately"
    basis: str
    to: str
    note: str
    cite: str
    in_force: bool = True
    applies_from: date | None = None

    @property
    def asap(self) -> bool:
        return self.due is None


def add_months(d: datetime, months: int) -> datetime:
    """Same day number in a later month; the last day of the month when that day does not exist."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


class IncidentRules:
    def __init__(self, data: Mapping[str, Any]):
        self.questions: list[dict] = list(data["incident_questions"])
        self.clocks: list[dict] = list(data["clocks"])
        self._validate()

    @classmethod
    def builtin(cls) -> "IncidentRules":
        return cls(yaml.safe_load(RULES.read_text(encoding="utf-8")))

    def _validate(self) -> None:
        qids = {q["id"] for q in self.questions}
        choices = {f"{q['id']}={o['id']}" for q in self.questions for o in q.get("options", [])}
        allowed_external = {"ai_role=provider", "ai_role=deployer"}
        seen: list[str] = []
        for c in self.clocks:
            for f in ("id", "regime", "when", "report", "after", "to", "cite"):
                if not c.get(f):
                    raise RulebookError(f"Clock {c.get('id')} is missing '{f}'")
            if c["regime"] not in REGIME_NAMES:
                raise RulebookError(f"Clock {c['id']} has unknown regime {c['regime']}")
            if c["after"] not in ("aware", "classified") and c["after"] not in seen:
                raise RulebookError(f"Clock {c['id']} counts from '{c['after']}', which is not an earlier clock")
            if not c.get("asap") and not any(k in c for k in ("hours", "days", "months")):
                raise RulebookError(f"Clock {c['id']} needs hours, days, months or asap")
            for ref in _refs(c["when"]):
                if ref not in qids and ref not in choices and ref not in allowed_external:
                    raise RulebookError(f"Clock {c['id']} refers to unknown '{ref}'")
            seen.append(c["id"])


def timeline(
    rules: IncidentRules,
    incident: Mapping[str, Any],
    aware: datetime,
    regimes: Iterable[str],
    classified: datetime | None = None,
    context: Mapping[str, Any] | None = None,
) -> list[Deadline]:
    """All deadlines for an incident, sorted by due time (immediate ones first).

    incident:   answers to the incident questions
    aware:      when you became aware of the incident
    regimes:    the regulations that apply to you, e.g. from the Navigator: {"gdpr", "nis2"}
    classified: when you classified it as a major ICT incident (DORA); defaults to `aware`
    context:    other answers used in conditions, such as ai_role
    """
    regimes = set(regimes)
    answers = {**(context or {}), **incident}
    check = checker(answers, {}, {})
    due: dict[str, datetime] = {}
    out: list[Deadline] = []
    for c in rules.clocks:
        if c["regime"] not in regimes or not check(c["when"]):
            continue
        start = {"aware": aware, "classified": classified or aware}.get(c["after"], due.get(c["after"]))
        basis = {"aware": "after becoming aware", "classified": "after classification as major"}.get(
            c["after"], "after the previous report, if sent at its deadline")
        if c.get("asap"):
            when = None
            basis = "without undue delay"
        else:
            when = start + timedelta(hours=c.get("hours", 0), days=c.get("days", 0))
            if c.get("months"):
                when = add_months(when, c["months"])
            if c.get("or_hours_after_aware"):
                when = min(when, aware + timedelta(hours=c["or_hours_after_aware"]))
            due[c["id"]] = when
        applies_from = c.get("applies_from")
        if isinstance(applies_from, str):
            applies_from = date.fromisoformat(applies_from)
        out.append(Deadline(
            c["id"], c["regime"], c["report"], when, basis, c["to"], c.get("note", ""), c["cite"],
            in_force=applies_from is None or aware.date() >= applies_from, applies_from=applies_from,
        ))
    out.sort(key=lambda d: (d.due is not None, d.due or aware))
    return out


def to_markdown(deadlines: list[Deadline], aware: datetime) -> str:
    lines = [f"# Incident deadlines", "", f"Became aware: **{aware:%d %b %Y %H:%M}**", "",
             "| Due | Regulation | Report | To | Basis |", "|---|---|---|---|---|"]
    for d in deadlines:
        when = "Immediately" if d.asap else f"{d.due:%a %d %b %Y %H:%M}"
        flag = "" if d.in_force else f" (applies from {d.applies_from:%d %b %Y})"
        lines.append(f"| {when} | {REGIME_NAMES[d.regime]} | {d.report}{flag} | {d.to} | {d.cite} |")
    lines += ["", "*Chained deadlines assume the earlier report was sent at its deadline. Weekend and bank holiday "
              "relief is not applied. Screening aid, not legal advice.*", ""]
    return "\n".join(lines)
