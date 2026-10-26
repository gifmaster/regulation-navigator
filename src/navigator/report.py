"""Markdown report of a Navigator result."""

from __future__ import annotations

from datetime import date

from .engine import STATUSES, Navigator, Obligation, Result


def _due(ob: Obligation, today: date) -> str:
    if not ob.applies_from:
        return ""
    when = ob.applies_from.strftime("%-d %B %Y")
    return f" *(applies from {when})*" if ob.applies_from > today else f" *(applies since {when})*"


def _answer_lines(nav: Navigator, result: Result) -> list[str]:
    lines = []
    for section in nav.sections:
        picked = []
        for q in nav.questions_in(section["id"]):
            v = result.answers.get(q.id)
            if not v:
                continue
            picked.append(f"{q.text}: {dict(q.options)[v]}" if q.is_choice else q.text)
        if picked:
            lines.append(f"**{section['title']}**")
            lines += [f"- {p}" for p in picked]
            lines.append("")
    return lines


def to_markdown(nav: Navigator, result: Result, use_case: str = "", org: str = "", today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        f"# Regulation Navigator: {use_case or 'AI use case'}",
        "",
        f"- **Organisation:** {org or 'Not given'}",
        f"- **Date:** {today.isoformat()}",
        f"- **Rules version:** {nav.version} (last reviewed {nav.last_reviewed})",
        "",
        "## Summary",
        "",
        "| Regulation | Result | Why |",
        "|---|---|---|",
    ]
    for rid, r in result.regimes.items():
        if rid == "overlaps":
            continue
        lines.append(f"| {r.regime.title} | **{STATUSES[r.status]}**: {r.title} | {r.reason} |")
    for rid, r in result.regimes.items():
        if rid == "overlaps":
            continue
        lines += ["", f"## {r.regime.title}: {r.title}", "", r.reason]
        if r.decided_by:
            cite = r.decided_by.cite
            lines.append(f"*Basis: {r.regime.short + ' ' if cite.startswith('Art.') else ''}{cite}*")
        if r.regime.authority and r.status != "not_applicable":
            lines += ["", f"Authority in Denmark: {r.regime.authority}."]
        if r.obligations:
            lines += ["", "What to do:", ""]
            lines += [f"- [ ] {ob.text} ({ob.cite}){_due(ob, today)}" for ob in r.obligations]
    if result.overlaps:
        lines += ["", "## Where they overlap", ""]
        for rule in result.overlaps:
            lines += [f"### {rule.title}", "", rule.reason, "", f"*{rule.cite}*", ""]
            lines += [f"- [ ] {ob.text}" for ob in rule.obligations]
            lines.append("")
    tools = {ob.tool for r in result.regimes.values() for ob in r.obligations if ob.tool}
    if tools:
        lines += ["", "## Tools that help", ""]
        lines += [f"- [{nav.tools[t]['label']}]({nav.tools[t]['url']})" for t in nav.tools if t in tools]
    lines += ["", "## Your answers", ""] + _answer_lines(nav, result)
    lines += ["---", "",
              "*Screening aid, not legal advice. Each result cites the rule behind it so a qualified person can check it. "
              "Rules reflect the law as of the review date above.*", ""]
    return "\n".join(lines)
