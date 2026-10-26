"""Incident Clock: deadlines checked by hand against the legal texts."""

import copy
from datetime import datetime

import pytest
import yaml

from navigator import RulebookError
from navigator.incidents import RULES, IncidentRules, add_months, timeline, to_markdown

R = IncidentRules.builtin()
AWARE = datetime(2026, 10, 26, 9, 0)  # Monday 09:00
ALL = {"gdpr", "nis2", "dora", "ai_act"}


def due(deadlines, cid):
    return next(d for d in deadlines if d.id == cid).due


def test_gdpr_72_hours():
    d = timeline(R, {"i_personal_data": True}, AWARE, ALL)
    assert due(d, "gdpr_authority") == datetime(2026, 10, 29, 9, 0)
    assert "gdpr_people" not in {x.id for x in d}


def test_gdpr_tell_people_when_high_risk():
    d = timeline(R, {"i_personal_data": True, "i_high_risk_people": True}, AWARE, ALL)
    assert next(x for x in d if x.id == "gdpr_people").asap


def test_nis2_24_72_and_one_month_after_notification():
    d = timeline(R, {"i_significant": True}, AWARE, ALL)
    assert due(d, "nis2_early_warning") == datetime(2026, 10, 27, 9, 0)
    assert due(d, "nis2_notification") == datetime(2026, 10, 29, 9, 0)
    assert due(d, "nis2_final") == datetime(2026, 11, 29, 9, 0)


def test_dora_initial_is_4h_after_classification():
    d = timeline(R, {"i_major": True}, AWARE, ALL, classified=datetime(2026, 10, 26, 15, 0))
    assert due(d, "dora_initial") == datetime(2026, 10, 26, 19, 0)
    assert due(d, "dora_intermediate") == datetime(2026, 10, 29, 19, 0)
    assert due(d, "dora_final") == datetime(2026, 11, 29, 19, 0)


def test_dora_initial_never_later_than_24h_after_awareness():
    d = timeline(R, {"i_major": True}, AWARE, ALL, classified=datetime(2026, 10, 27, 8, 0))
    assert due(d, "dora_initial") == datetime(2026, 10, 27, 9, 0)


@pytest.mark.parametrize("kind, days", [("other", 15), ("widespread", 2), ("death", 10)])
def test_ai_act_serious_incident(kind, days):
    d = timeline(R, {"i_ai_serious": True, "i_ai_kind": kind}, AWARE, ALL, context={"ai_role": "provider"})
    reports = [x for x in d if x.regime == "ai_act"]
    assert len(reports) == 1 and (reports[0].due - AWARE).days == days
    assert not reports[0].in_force  # Annex III high-risk duties apply from 2 December 2027


def test_deployer_must_inform_provider_and_rules_apply_later():
    d = timeline(R, {"i_ai_serious": True}, datetime(2028, 1, 10, 9, 0), ALL, context={"ai_role": "deployer"})
    first = d[0]
    assert first.id == "ai_inform_provider" and first.asap and first.in_force


def test_only_regimes_that_apply():
    d = timeline(R, {"i_personal_data": True, "i_significant": True, "i_major": True}, AWARE, {"gdpr"})
    assert {x.regime for x in d} == {"gdpr"}


def test_sorted_immediate_first_then_by_time():
    d = timeline(R, {"i_personal_data": True, "i_high_risk_people": True, "i_significant": True}, AWARE, ALL)
    assert d[0].asap
    times = [x.due for x in d if not x.asap]
    assert times == sorted(times)


def test_add_months_end_of_month():
    assert add_months(datetime(2026, 1, 31, 12), 1) == datetime(2026, 2, 28, 12)
    assert add_months(datetime(2026, 12, 15), 1) == datetime(2027, 1, 15)


def test_markdown():
    md = to_markdown(timeline(R, {"i_significant": True}, AWARE, ALL), AWARE)
    assert "Early warning" in md and "not legal advice" in md


@pytest.mark.parametrize("mutate, msg", [
    (lambda c: c["clocks"][0].update(cite=""), "missing 'cite'"),
    (lambda c: c["clocks"][0].update(regime="pci"), "unknown regime"),
    (lambda c: c["clocks"][0].update(after="nis2_final"), "not an earlier clock"),
    (lambda c: c["clocks"][0].update(when="i_nope"), "unknown"),
    (lambda c: [c["clocks"][0].pop(k) for k in ("hours",)], "needs hours"),
])
def test_validation(mutate, msg):
    data = copy.deepcopy(yaml.safe_load(RULES.read_text(encoding="utf-8")))
    mutate(data)
    with pytest.raises(RulebookError, match=msg):
        IncidentRules(data)
