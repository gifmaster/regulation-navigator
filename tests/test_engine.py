"""Unit tests for the engine and the rule files."""

import copy

import pytest
import yaml

from navigator import Navigator, RulebookError, evaluate
from navigator.engine import REGIMES, RULES_DIR

NAV = Navigator.builtin()


def load_all():
    load = lambda n: yaml.safe_load((RULES_DIR / f"{n}.yaml").read_text(encoding="utf-8"))  # noqa: E731
    return load("questions"), {r: load(r) for r in REGIMES}


def test_every_regulation_is_decided_for_empty_answers():
    """No regulation may fall through to the engine's default: each file has its own catch-all."""
    result = evaluate(NAV, {})
    for rid in REGIMES[:-1]:
        assert result.regimes[rid].decided_by is not None, rid


def test_every_visible_rule_cites_and_titles():
    for regime in NAV.regimes.values():
        for rule in regime.rules:
            assert rule.cite
            if rule.status:
                assert rule.title and rule.reason


def test_first_matching_status_wins():
    # A large bank that also ticks food production: DORA applies; NIS2 decided by the sector rule, not DORA
    r = evaluate(NAV, {"f_bank": True, "staff_250": True, "s_food": True})
    assert r.status("dora") == "applies"
    assert r.status("nis2") == "applies"


def test_obligations_hidden_when_not_applicable():
    r = evaluate(NAV, {"f_pension": True, "f_small_pension": True, "ai_vendor": True})
    assert r.status("dora") == "not_applicable" and r.regimes["dora"].obligations == []


def test_at_least_operator():
    one = evaluate(NAV, {"pd": True, "pd_vulnerable": True})
    two = evaluate(NAV, {"pd": True, "pd_vulnerable": True, "pd_new_tech": True})
    assert one.regimes["gdpr"].title.endswith("probably not required")
    assert two.regimes["gdpr"].title.endswith("DPIA required")


@pytest.mark.parametrize("answers, msg", [
    ({"nope": True}, "Unknown question"),
    ({"ai_tier": "very high"}, "not an option"),
])
def test_bad_answers_are_rejected(answers, msg):
    with pytest.raises(ValueError, match=msg):
        evaluate(NAV, answers)


@pytest.mark.parametrize("mutate, msg", [
    (lambda q, r: r["gdpr"]["rules"][0].update(cite=""), "must cite"),
    (lambda q, r: r["gdpr"]["rules"][0].update(status="maybe"), "unknown status"),
    (lambda q, r: r["gdpr"]["rules"][0].update(when="no_such_question"), "unknown yes/no question"),
    (lambda q, r: r["gdpr"]["rules"][0].update(when="ai_tier=huge"), "unknown choice"),
    (lambda q, r: r["gdpr"]["rules"][0].update(when="$nope"), "unknown fact"),
    (lambda q, r: r["ai_act"]["rules"][0].update(when="@nis2"), "not evaluated before"),
    (lambda q, r: r["gdpr"]["rules"].append(dict(r["gdpr"]["rules"][0])), "Duplicate"),
    (lambda q, r: r["overlaps"]["rules"][0].update(status="applies"), "must not set a status"),
    (lambda q, r: r["dora"]["rules"][-1]["obligations"][0].update(tool="nope"), "unknown tool"),
    (lambda q, r: r["gdpr"]["rules"][0].update(when={"some": []}), "Unknown condition operator"),
])
def test_rule_validation(mutate, msg):
    q, r = copy.deepcopy(load_all())
    mutate(q, r)
    with pytest.raises(RulebookError, match=msg):
        Navigator(q, r)


def test_choice_questions_have_unique_options():
    for q in NAV.questions.values():
        ids = [o for o, _ in q.options]
        assert len(ids) == len(set(ids))


def test_no_em_dashes_in_rules():
    for f in RULES_DIR.glob("*.yaml"):
        assert "—" not in f.read_text(encoding="utf-8"), f.name
