"""A small, transparent rules engine for regulatory scoping.

The engine knows nothing about any regulation. Questions live in ``rules/questions.yaml``
and each regulation has its own rule file (``ai_act.yaml``, ``gdpr.yaml``, ``nis2.yaml``,
``dora.yaml``), plus ``overlaps.yaml`` for the places where they meet.

How a regulation file works:

* Rules are read top to bottom. The **first rule with a status** that matches decides the
  status of the regulation for you: applies, check, or not_applicable. That makes each file
  a readable decision table.
* Every matching rule adds its obligations, as long as the regulation does not end up
  not_applicable. Rules without a status only add obligations or notes.
* Every rule must cite its legal basis.

Conditions (in rules and facts):

* ``question_id``           a yes/no question answered yes
* ``question_id=option``    a choice question answered with that option
* ``$fact``                 a named condition from ``facts`` in questions.yaml
* ``@regulation``           an earlier regulation (in REGIMES order) has status applies
* ``{all: [...]}``, ``{any: [...]}``, ``{not: ...}``, ``{at_least: {n: 2, of: [...]}}``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

RULES_DIR = Path(__file__).parent / "rules"
REGIMES = ("ai_act", "gdpr", "dora", "nis2", "overlaps")  # evaluation order; later files may refer to earlier ones
STATUSES = {"applies": "Applies", "check": "Check", "not_applicable": "Does not apply"}


class RulebookError(ValueError):
    """Raised when a rule file is malformed or refers to something that does not exist."""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Question:
    id: str
    section: str
    text: str
    help: str = ""
    options: tuple[tuple[str, str], ...] = ()  # (id, label) for choice questions
    show_if: Any = None

    @property
    def is_choice(self) -> bool:
        return bool(self.options)


@dataclass(frozen=True)
class Obligation:
    text: str
    cite: str
    applies_from: date | None = None
    tool: str = ""  # id of a toolkit link, see TOOLS in questions.yaml


@dataclass(frozen=True)
class Rule:
    id: str
    when: Any
    cite: str
    status: str | None = None
    title: str = ""
    reason: str = ""
    obligations: tuple[Obligation, ...] = ()


@dataclass(frozen=True)
class Regime:
    id: str
    title: str
    short: str
    source: str
    authority: str
    rules: tuple[Rule, ...]
    default_reason: str = ""


@dataclass
class RegimeResult:
    regime: Regime
    status: str
    decided_by: Rule | None
    matched: list[Rule]
    obligations: list[Obligation]

    @property
    def title(self) -> str:
        return self.decided_by.title if self.decided_by else STATUSES[self.status]

    @property
    def reason(self) -> str:
        return self.decided_by.reason if self.decided_by else self.regime.default_reason


@dataclass
class Result:
    regimes: dict[str, RegimeResult]
    answers: dict[str, Any] = field(default_factory=dict)

    def status(self, regime_id: str) -> str:
        return self.regimes[regime_id].status

    @property
    def overlaps(self) -> list[Rule]:
        return self.regimes["overlaps"].matched


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #


def _date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _obligation(raw: Mapping[str, Any]) -> Obligation:
    return Obligation(raw["text"], raw.get("cite", ""), _date(raw.get("applies_from")), raw.get("tool", ""))


def _rule(raw: Mapping[str, Any]) -> Rule:
    return Rule(
        id=raw["id"], when=raw["when"], cite=raw.get("cite", ""), status=raw.get("status"),
        title=raw.get("title", ""), reason=raw.get("reason", ""),
        obligations=tuple(_obligation(o) for o in raw.get("obligations", [])),
    )


class Navigator:
    def __init__(self, questions: Mapping[str, Any], regimes: Mapping[str, Mapping[str, Any]]):
        try:
            self.sections: list[dict] = list(questions["sections"])
            self.questions: dict[str, Question] = {}
            for q in questions["questions"]:
                opts = tuple((o["id"], o["label"]) for o in q.get("options", []))
                self.questions[q["id"]] = Question(q["id"], q["section"], q["text"], q.get("help", ""), opts, q.get("show_if"))
            self.facts: dict[str, Any] = dict(questions.get("facts", {}))
            self.tools: dict[str, dict] = dict(questions.get("tools", {}))
            self.version: str = str(questions.get("version", ""))
            self.last_reviewed: str = str(questions.get("last_reviewed", ""))
            self.regimes: dict[str, Regime] = {}
            for rid in REGIMES:
                r = regimes[rid]
                self.regimes[rid] = Regime(rid, r["title"], r.get("short", r["title"]), r.get("source", ""),
                                           r.get("authority", ""), tuple(_rule(x) for x in r["rules"]),
                                           r.get("default_reason", ""))
        except KeyError as exc:
            raise RulebookError(f"Missing required field: {exc}") from exc
        self._validate()

    @classmethod
    def builtin(cls) -> "Navigator":
        load = lambda name: yaml.safe_load((RULES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))  # noqa: E731
        return cls(load("questions"), {rid: load(rid) for rid in REGIMES})

    def _validate(self) -> None:
        section_ids = {s["id"] for s in self.sections}
        for q in self.questions.values():
            if q.section not in section_ids:
                raise RulebookError(f"Question '{q.id}' uses unknown section '{q.section}'")
            if q.show_if is not None:
                self._check_refs(q.show_if, f"question '{q.id}'", set())
        for name, cond in self.facts.items():
            self._check_refs(cond, f"fact '{name}'", set())
        earlier: set[str] = set()
        seen: set[str] = set()
        for rid, regime in self.regimes.items():
            for rule in regime.rules:
                if rule.id in seen:
                    raise RulebookError(f"Duplicate rule id '{rule.id}'")
                seen.add(rule.id)
                if not rule.cite:
                    raise RulebookError(f"Rule '{rule.id}' must cite its legal basis")
                if rule.status is not None and rule.status not in STATUSES:
                    raise RulebookError(f"Rule '{rule.id}' has unknown status '{rule.status}'")
                if rule.status and not rule.title:
                    raise RulebookError(f"Rule '{rule.id}' sets a status and needs a title")
                if rid == "overlaps" and rule.status:
                    raise RulebookError(f"Overlap rule '{rule.id}' must not set a status")
                for ob in rule.obligations:
                    if not ob.cite:
                        raise RulebookError(f"Every obligation in rule '{rule.id}' must cite its source")
                    if ob.tool and ob.tool not in self.tools:
                        raise RulebookError(f"Rule '{rule.id}' links to unknown tool '{ob.tool}'")
                self._check_refs(rule.when, f"rule '{rule.id}'", earlier)
            earlier.add(rid)

    def _check_refs(self, cond: Any, where: str, earlier: set[str]) -> None:
        for ref in _refs(cond):
            if ref.startswith("$"):
                if ref[1:] not in self.facts:
                    raise RulebookError(f"{where} refers to unknown fact '{ref}'")
            elif ref.startswith("@"):
                if ref[1:] not in earlier:
                    raise RulebookError(f"{where} refers to '{ref}', which is not evaluated before it")
            elif "=" in ref:
                qid, opt = ref.split("=", 1)
                q = self.questions.get(qid)
                if not q or not q.is_choice or opt not in dict(q.options):
                    raise RulebookError(f"{where} refers to unknown choice '{ref}'")
            elif ref not in self.questions or self.questions[ref].is_choice:
                raise RulebookError(f"{where} refers to unknown yes/no question '{ref}'")

    def questions_in(self, section_id: str) -> list[Question]:
        return [q for q in self.questions.values() if q.section == section_id]


def _refs(cond: Any) -> Iterable[str]:
    if isinstance(cond, str):
        yield cond
    elif isinstance(cond, Mapping):
        if len(cond) != 1:
            raise RulebookError(f"A condition must have exactly one operator, got {list(cond)}")
        (op, value), = cond.items()
        if op in ("all", "any"):
            for item in value:
                yield from _refs(item)
        elif op == "not":
            yield from _refs(value)
        elif op == "at_least":
            if not isinstance(value, Mapping) or "n" not in value or "of" not in value:
                raise RulebookError("at_least needs {n: <number>, of: [...]}")
            for item in value["of"]:
                yield from _refs(item)
        else:
            raise RulebookError(f"Unknown condition operator '{op}'")
    else:
        raise RulebookError(f"Invalid condition: {cond!r}")


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def checker(answers: Mapping[str, Any], facts: Mapping[str, Any], applies: Mapping[str, bool]):
    """Return a function that evaluates a condition against answers, facts and regulation results."""
    cache: dict[str, bool] = {}

    def check(cond: Any) -> bool:
        if isinstance(cond, str):
            if cond.startswith("$"):
                if cond not in cache:
                    cache[cond] = check(facts[cond[1:]])
                return cache[cond]
            if cond.startswith("@"):
                return bool(applies.get(cond[1:]))
            if "=" in cond:
                qid, opt = cond.split("=", 1)
                return answers.get(qid) == opt
            return bool(answers.get(cond))
        (op, value), = cond.items()
        if op == "all":
            return all(check(c) for c in value)
        if op == "any":
            return any(check(c) for c in value)
        if op == "at_least":
            return sum(check(c) for c in value["of"]) >= value["n"]
        return not check(value)

    return check


def evaluate(nav: Navigator, answers: Mapping[str, Any]) -> Result:
    """Run all regulations against the answers.

    Yes/no questions take True/False (missing means no). Choice questions take an option id
    (missing means none chosen). Unknown question ids or options are rejected, so a typo
    cannot silently change a result.
    """
    unknown = set(answers) - set(nav.questions)
    if unknown:
        raise ValueError(f"Unknown question id(s): {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for qid, q in nav.questions.items():
        v = answers.get(qid)
        if q.is_choice:
            if v is not None and v not in dict(q.options):
                raise ValueError(f"'{v}' is not an option for '{qid}'")
            clean[qid] = v
        else:
            clean[qid] = bool(v)

    applies: dict[str, bool] = {}
    check = checker(clean, nav.facts, applies)

    results: dict[str, RegimeResult] = {}
    for rid, regime in nav.regimes.items():
        matched = [r for r in regime.rules if check(r.when)]
        decider = next((r for r in matched if r.status), None)
        status = decider.status if decider else ("check" if rid != "overlaps" else "applies")
        obligations: list[Obligation] = []
        if status != "not_applicable":
            seen = set()
            for r in matched:
                for ob in r.obligations:
                    if ob.text not in seen:
                        seen.add(ob.text)
                        obligations.append(ob)
        applies[rid] = status == "applies"
        results[rid] = RegimeResult(regime, status, decider, matched, obligations)
    return Result(results, {k: v for k, v in clean.items() if v})
