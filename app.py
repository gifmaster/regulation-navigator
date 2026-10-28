"""Streamlit front end for the Regulation Navigator and the Incident Clock.

Run locally:  streamlit run app.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from navigator import Navigator, evaluate, to_markdown  # noqa: E402
from navigator.engine import STATUSES, checker  # noqa: E402
from navigator.incidents import REGIME_NAMES, IncidentRules, timeline  # noqa: E402
from navigator.incidents import to_markdown as incident_markdown  # noqa: E402
from navigator.pdf import markdown_to_pdf  # noqa: E402

REPO = "https://github.com/gifmaster/regulation-navigator"
ICON = {"applies": "🟥", "check": "🟨", "not_applicable": "⬜"}
SHORT = {"applies": "Applies", "check": "Check", "not_applicable": "No"}
EXAMPLES = {
    "Food producer screening job applicants with AI": "food_manufacturer_cv_screening",
    "Pension fund answering members with AI": "pension_fund_member_service",
    "Life insurer pricing with an AI model": "insurer_life_pricing",
    "Managed IT provider triaging tickets with AI": "managed_service_provider",
    "Accounting firm using an AI assistant": "accounting_firm_copilot",
}

st.set_page_config(page_title="Regulation Navigator", page_icon="🧭", layout="wide")


@st.cache_resource
def load():
    cases = yaml.safe_load((ROOT / "tests" / "acceptance_cases.yaml").read_text(encoding="utf-8"))["cases"]
    return Navigator.builtin(), IncidentRules.builtin(), {c["id"]: c for c in cases}


NAV, INC, CASES = load()


def set_answers(answers: dict) -> None:
    for q in NAV.questions.values():
        st.session_state[f"q_{q.id}"] = answers.get(q.id, None if q.is_choice else False)


def load_example() -> None:
    label = st.session_state.example
    if label in EXAMPLES:
        set_answers(CASES[EXAMPLES[label]]["answers"])
        st.session_state.use_case = label
    else:
        set_answers({})
        st.session_state.use_case = ""


if "q_ai_tier" not in st.session_state:
    set_answers(CASES[EXAMPLES[next(iter(EXAMPLES))]]["answers"])
    st.session_state.use_case = next(iter(EXAMPLES))

st.title("Regulation Navigator")
st.caption("Which EU rules apply to your AI use case: the EU AI Act, GDPR, NIS2 and DORA, where they overlap, "
           "and what to do. Written for organisations in Denmark.")

tab_nav, tab_clock, tab_about = st.tabs(["Navigator", "Incident Clock", "How it works"])

# --- Navigator ------------------------------------------------------------------------
with tab_nav:
    left, right = st.columns([5, 6], gap="large")
    with left:
        c1, c2 = st.columns(2)
        c1.selectbox("Start from an example", list(EXAMPLES) + ["Start empty"], key="example", on_change=load_example)
        c2.text_input("AI use case", key="use_case")
        st.text_input("Organisation (optional)", key="org")
        answers: dict = {}
        for section in NAV.sections:
            with st.expander(section["title"], expanded=section["id"] in ("ai", "org")):
                st.caption(section["intro"])
                visible = checker({k[2:]: v for k, v in st.session_state.items() if str(k).startswith("q_")}, NAV.facts, {})
                for q in NAV.questions_in(section["id"]):
                    if q.show_if is not None and not visible(q.show_if):
                        continue
                    if q.is_choice:
                        opts = [o for o, _ in q.options]
                        answers[q.id] = st.selectbox(q.text, opts, key=f"q_{q.id}", index=None, help=q.help or None,
                                                     format_func=lambda o, q=q: dict(q.options)[o], placeholder="Choose")
                    else:
                        answers[q.id] = st.checkbox(q.text, key=f"q_{q.id}", help=q.help or None)
                if section["id"] == "ai":
                    st.markdown("Not sure about the tier? Use the [EU AI Act Risk Check](https://ai-act-risk-check.streamlit.app).")

    result = evaluate(NAV, {k: v for k, v in answers.items() if v})
    st.session_state.applies = [rid for rid in REGIME_NAMES if result.status(rid) == "applies"]
    with right:
        st.subheader("Result")
        cols = st.columns(4)
        for col, (rid, r) in zip(cols, [(k, v) for k, v in result.regimes.items() if k != "overlaps"]):
            col.metric(r.regime.short, SHORT[r.status])
            col.caption(f"{ICON[r.status]} {r.title}")
        for rid, r in result.regimes.items():
            if rid == "overlaps":
                continue
            with st.expander(f"{ICON[r.status]} **{r.regime.title}**: {r.title}", expanded=r.status == "applies"):
                cite = r.decided_by.cite if r.decided_by else ""
                st.markdown(f"{r.reason}  \n`{r.regime.short + ' ' if cite.startswith('Art.') else ''}{cite}`")
                if r.obligations:
                    for ob in r.obligations:
                        due = ""
                        if ob.applies_from:
                            due = f" · from {ob.applies_from:%-d %b %Y}" if ob.applies_from > date.today() else ""
                        tool = f" → [{NAV.tools[ob.tool]['label']}]({NAV.tools[ob.tool]['url']})" if ob.tool else ""
                        st.markdown(f"- {ob.text} `{ob.cite}`{due}{tool}")
                if r.status != "not_applicable" and r.regime.authority:
                    st.caption(f"Authority in Denmark: {r.regime.authority}")
        if result.overlaps:
            st.subheader(f"Where they overlap ({len(result.overlaps)})")
            for rule in result.overlaps:
                with st.container(border=True):
                    st.markdown(f"**{rule.title}**  \n{rule.reason}  \n`{rule.cite}`")
                    for ob in rule.obligations:
                        tool = f" → [{NAV.tools[ob.tool]['label']}]({NAV.tools[ob.tool]['url']})" if ob.tool else ""
                        st.markdown(f"- {ob.text}{tool}")
        report = to_markdown(NAV, result, st.session_state.get("use_case", ""), st.session_state.get("org", ""))
        st.download_button("Download report (PDF)", markdown_to_pdf(report, "Regulation Navigator"),
                           "regulation-navigator.pdf", "application/pdf", type="primary", width="stretch", key="dl_report_pdf")
        st.download_button("Download report (Markdown)", report, "regulation-navigator.md", "text/markdown",
                           width="stretch", key="dl_report")
        st.caption("Screening aid, not legal advice. Every result cites the rule behind it.")

# --- Incident Clock -------------------------------------------------------------------
with tab_clock:
    st.markdown("When an incident hits, several reporting clocks can start at once. Enter when you became aware, "
                "and what kind of incident it is.")
    a, b = st.columns([2, 3], gap="large")
    with a:
        applies = st.session_state.get("applies", [])
        regimes = st.multiselect("Regulations that apply to you", list(REGIME_NAMES), key="clock_" + "-".join(applies),
                                 default=applies, format_func=REGIME_NAMES.get,
                                 help="Filled in from the Navigator tab. Change it if needed.")
        c1, c2 = st.columns(2)
        aware_d = c1.date_input("Became aware: date", value=date.today(), key="aware_d")
        aware_t = c2.time_input("Time", value=time(9, 0), key="aware_t", step=900)
        aware = datetime.combine(aware_d, aware_t)
        classified = None
        if "dora" in regimes:
            c1, c2 = st.columns(2)
            cd = c1.date_input("Classified as major (DORA): date", value=aware_d, key="cls_d")
            ct = c2.time_input("Time ", value=aware_t, key="cls_t", step=900)
            classified = datetime.combine(cd, ct)
        incident: dict = {}
        for q in INC.questions:
            if q.get("show_if") and not incident.get(q["show_if"]):
                continue
            if q.get("options"):
                opts = [o["id"] for o in q["options"]]
                labels = {o["id"]: o["label"] for o in q["options"]}
                incident[q["id"]] = st.radio(q["text"], opts, format_func=labels.get, key=f"i_{q['id']}")
            else:
                incident[q["id"]] = st.checkbox(q["text"], key=f"i_{q['id']}", help=q.get("help"))
    with b:
        context = {"ai_role": st.session_state.get("q_ai_role")}
        deadlines = timeline(INC, {k: v for k, v in incident.items() if v}, aware, regimes, classified, context)
        if not deadlines:
            st.info("Tick what happened to see the deadlines.")
        now = datetime.now()
        for d in deadlines:
            if d.asap:
                when, left_txt = "Immediately", ""
            else:
                when = f"{d.due:%a %d %b %H:%M}"
                hours = (d.due - now).total_seconds() / 3600
                left_txt = "passed" if hours < 0 else f"{hours:.0f} hours left" if hours < 72 else f"{hours / 24:.0f} days left"
            with st.container(border=True):
                st.markdown(f"**{when}** · {REGIME_NAMES[d.regime]} · **{d.report}**"
                            + ("" if d.in_force else f" · *applies from {d.applies_from:%-d %b %Y}*"))
                st.markdown(f"To: {d.to}  \n{d.note}  \n`{d.cite}` · {d.basis}" + (f" · {left_txt}" if left_txt else ""))
        if deadlines:
            clock = incident_markdown(deadlines, aware)
            st.download_button("Download deadlines (PDF)", markdown_to_pdf(clock, "Regulation Navigator: Incident Clock"),
                               "incident-deadlines.pdf", "application/pdf", type="primary", key="dl_clock_pdf",
                               help="Print it or send it to the people handling the incident.")
            st.download_button("Download deadlines (Markdown)", clock, "incident-deadlines.md", "text/markdown",
                               key="dl_clock")
        st.caption("Chained deadlines assume the earlier report was sent at its deadline. Weekend and bank holiday relief "
                   "is not applied. Screening aid, not legal advice.")

# --- About ----------------------------------------------------------------------------
with tab_about:
    st.markdown(f"""
**What it does.** You describe your organisation and one AI use case. The Navigator tells you whether the EU AI Act,
GDPR, NIS2 and DORA apply, what each one asks of you, and where they overlap, so one piece of work can serve several laws.

**How it decides.** Each regulation is a [readable rule file]({REPO}/tree/main/src/navigator/rules). Rules are read top
to bottom, and the first matching rule decides the result. Every rule cites its article. No AI guesses the answer.

**What it does not do.** It does not classify the AI system under the AI Act; the
[EU AI Act Risk Check](https://ai-act-risk-check.streamlit.app) does that. It does not cover national options in full,
sector-specific Danish rules for energy and telecom in detail, or the Digital Omnibus proposals that are not yet adopted.

**Your data.** Nothing is stored. Rules last reviewed {NAV.last_reviewed}.

Part of a toolkit: [Risk Check](https://ai-act-risk-check.streamlit.app) ·
[Contract Clause Checker](https://contract-clause-checker.streamlit.app) ·
[AI Use Case Register](https://ai-use-case-register.streamlit.app) ·
[Framework](https://github.com/gifmaster/ai-governance-framework) · [Source code]({REPO})

Built by Alexander Senderovitz, [senderovitz.eu](https://senderovitz.eu).
""")
