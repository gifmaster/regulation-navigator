"""PDF reports: the PDF must say exactly what the Markdown report says."""

import io
import re
from datetime import datetime
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")

import yaml  # noqa: E402

from navigator import Navigator, evaluate, to_markdown  # noqa: E402
from navigator.incidents import IncidentRules, timeline  # noqa: E402
from navigator.incidents import to_markdown as incident_markdown  # noqa: E402
from navigator.pdf import fpdf_markdown, markdown_to_pdf, plain, spans  # noqa: E402


def pdf_text(data: bytes) -> str:
    """The PDF's text with the running page header and footer removed, so text that breaks across pages reads on."""
    pages = []
    for n, page in enumerate(pypdf.PdfReader(io.BytesIO(data)).pages):
        lines = (page.extract_text() or "").splitlines()
        lines = [ln for ln in lines if not re.search(r"\|\s+page \d+ of \d+$", ln) and not ln.startswith("Rules last reviewed")]
        if n > 0 and lines:
            lines = lines[1:]  # the running header repeats the title on every page after the first
        pages.append(" ".join(lines))
    return re.sub(r"\s+", " ", " ".join(pages))


def assert_same_content(md: str, data: bytes) -> int:
    """Every heading, bullet, checklist item and quote of the Markdown report is in the PDF."""
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    checked = 0
    for line in md.splitlines():
        if line.startswith(("#", "- ", ">")):
            body = re.sub(r"\s+", " ", plain(re.sub(r"^(#+ |- \[[ xX]\] |- |> ?)", "", line))).strip()
            if body:
                assert body in text, body
                checked += 1
    return checked


def test_danish_and_markdown_characters_render():
    md = "# Rapport: Østerbro Ølbryggeri\n\n- **Ejer:** Søren Ærø\n- Navn med A--B og __x__\n\n| Kolonne | Værdi |\n|---|---|\n| Åbent | ja |"
    text = pdf_text(markdown_to_pdf(md, "Test"))
    for needle in ("Østerbro Ølbryggeri", "Søren Ærø", "A--B og __x__", "Åbent"):
        assert needle in text, needle


def test_inline_parsing():
    assert spans("a **b** *c* [d](https://x.y)") == [
        ("", "a ", None), ("B", "b", None), ("", " ", None), ("I", "c", None), ("", " ", None), ("", "d", "https://x.y")]
    assert fpdf_markdown("*(Art. 4)* A--B") == "__(Art. 4)__ A\\--B"


CASES = yaml.safe_load((Path(__file__).parent / "acceptance_cases.yaml").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES[:3], ids=[c["id"] for c in CASES[:3]])
def test_report_pdf_matches_markdown(case):
    nav = Navigator.builtin()
    md = to_markdown(nav, evaluate(nav, case["answers"]), "Use case", "Org")
    assert assert_same_content(md, markdown_to_pdf(md, "Regulation Navigator")) >= 5


def test_incident_clock_pdf_has_every_deadline():
    aware = datetime(2026, 10, 26, 9, 0)
    deadlines = timeline(IncidentRules.builtin(), {"i_significant": True, "i_personal_data": True}, aware,
                         {"gdpr", "nis2", "dora", "ai_act"})
    md = incident_markdown(deadlines, aware)
    text = pdf_text(markdown_to_pdf(md, "Incident Clock"))
    for d in deadlines:
        assert d.report in text, d.report


def test_pdf_credits_the_author():
    data = markdown_to_pdf("# T\n\n- a", "Tool")
    raw = " ".join(pg.extract_text() or "" for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert "Built by Alexander Senderovitz, senderovitz.eu" in raw
    assert pypdf.PdfReader(io.BytesIO(data)).metadata.author == "Alexander Senderovitz"


def test_pdf_footer_shows_the_review_date():
    data = markdown_to_pdf("# T\n\n- a", "Tool", reviewed=Navigator.builtin().last_reviewed)
    raw = " ".join(pg.extract_text() or "" for pg in pypdf.PdfReader(io.BytesIO(data)).pages)
    assert f"Rules last reviewed: {Navigator.builtin().last_reviewed} by Alexander Senderovitz" in raw
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", Navigator.builtin().last_reviewed)
