"""Smoke tests for the Streamlit app."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


def run():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    return at


def text(at):
    parts = [m.value for m in at.markdown] + [e.label for e in at.expander] + [str(m.value) for m in at.metric]
    parts += [c.value for c in at.caption] + [h.value for h in at.subheader]
    for kind in ("info", "success", "warning"):
        parts += [x.value for x in getattr(at, kind)]
    return "\n".join(parts)


def test_example_loads():
    at = run()
    t = text(at)
    assert "High risk, deployer duties" in t and "Important entity" in t
    assert "One assessment for two laws" in t


def test_switch_example_to_pension_fund():
    at = run()
    at.selectbox(key="example").set_value("Pension fund answering members with AI").run()
    assert not at.exception
    t = text(at)
    assert "DORA applies instead" in t and "Financial entity under DORA" in t


def test_empty_start_asks_to_classify():
    at = run()
    at.selectbox(key="example").set_value("Start empty").run()
    assert not at.exception
    assert "Classify the AI system first" in text(at)


def test_incident_clock_uses_navigator_result():
    at = run()
    at.checkbox(key="i_i_personal_data").check().run()
    at.checkbox(key="i_i_significant").check().run()
    assert not at.exception
    t = text(at)
    assert "Notify Datatilsynet" in t and "Early warning" in t
