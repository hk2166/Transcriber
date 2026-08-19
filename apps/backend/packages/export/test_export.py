"""Export tests — each format renders valid, openable output."""

import io
import json

import pytest

from packages.export import (
    FORMATS,
    ExportSegment,
    ExportSummary,
    MeetingExport,
    to_docx,
    to_json,
    to_markdown,
    to_pdf,
)


@pytest.fixture
def export() -> MeetingExport:
    return MeetingExport(
        title="Quarterly Review",
        started_at="2026-08-17 09:30",
        source="both",
        speakers=["Alice", "Bob"],
        summary=ExportSummary(
            summary="We reviewed the roadmap and budget.",
            key_points=["Migration done"],
            action_items=["Draft the job description"],
            decisions=["Hire a backend engineer"],
            open_questions=[],
        ),
        segments=[
            ExportSegment(start_ms=1000, end_ms=4000, speaker="Alice", text="Let's begin."),
            ExportSegment(start_ms=4000, end_ms=8000, speaker="Bob", text="We're under budget."),
        ],
    )


def test_markdown_has_title_summary_and_transcript(export):
    md = to_markdown(export)
    assert "# Quarterly Review" in md
    assert "## Summary" in md
    assert "- [ ] Draft the job description" in md  # action items as checkboxes
    assert "[00:01]" in md and "**Alice:**" in md
    assert "We're under budget." in md


def test_json_roundtrips(export):
    data = json.loads(to_json(export))
    assert data["title"] == "Quarterly Review"
    assert data["summary"]["decisions"] == ["Hire a backend engineer"]
    # Re-validate against the model.
    assert MeetingExport.model_validate(data).segments[1].text == "We're under budget."


def test_pdf_is_a_pdf(export):
    data = to_pdf(export)
    assert data[:5] == b"%PDF-"
    assert len(data) > 500


def test_docx_opens_and_contains_title(export):
    from docx import Document

    data = to_docx(export)
    assert data[:2] == b"PK"  # docx is a zip
    document = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Quarterly Review" in text
    assert "We're under budget." in text


def test_formats_registry_covers_all_four(export):
    assert set(FORMATS) == {"markdown", "json", "pdf", "docx"}
    for fmt in FORMATS.values():
        blob = fmt.render(export)
        assert isinstance(blob, bytes) and len(blob) > 0
