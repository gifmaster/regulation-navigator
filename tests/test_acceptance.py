"""Acceptance cases: realistic organisations, with the result written from the legal texts."""

from pathlib import Path

import pytest
import yaml

from navigator import Navigator, evaluate, to_markdown

NAV = Navigator.builtin()
CASES = yaml.safe_load((Path(__file__).parent / "acceptance_cases.yaml").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(case):
    result = evaluate(NAV, case["answers"])
    for rid, want in case["expect"].items():
        got = result.regimes[rid]
        assert got.status == want[0], f"{rid}: expected {want[0]}, got {got.status} ({got.title})"
        if len(want) > 1:
            assert got.title == want[1], f"{rid}: expected '{want[1]}', got '{got.title}'"
    if "overlaps" in case:
        got = {r.id for r in result.overlaps}
        missing = set(case["overlaps"]) - got
        assert not missing, f"missing overlaps {missing}"
        if case.get("overlaps_exact"):
            assert got == set(case["overlaps"]), f"unexpected overlaps {got - set(case['overlaps'])}"
    for rid, snippets in case.get("obligations", {}).items():
        texts = " | ".join(f"{o.text} ({o.cite})" for o in result.regimes[rid].obligations)
        for s in snippets:
            assert s in texts, f"{rid}: '{s}' not in obligations"
    assert "not legal advice" in to_markdown(NAV, result)
