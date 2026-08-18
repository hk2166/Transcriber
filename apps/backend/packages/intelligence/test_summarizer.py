"""Summarizer tests with a fake client (no Ollama / model required)."""

import pytest

from packages.intelligence import generate_title, summarize


class FakeClient:
    """Returns scripted replies; records the prompts it received."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []

    def complete(self, prompt, system=None, format=None, options=None) -> str:
        self.calls.append(prompt)
        return self.replies.pop(0)


def test_summarize_parses_valid_json():
    reply = (
        '{"summary":"We reviewed the roadmap.","key_points":["migration done"],'
        '"action_items":["send the budget"],"decisions":["ship in Q3"],'
        '"open_questions":["launch date?"]}'
    )
    result = summarize(FakeClient([reply]), "transcript")
    assert result.summary == "We reviewed the roadmap."
    assert result.action_items == ["send the budget"]
    assert result.decisions == ["ship in Q3"]


def test_summarize_retries_once_then_succeeds():
    client = FakeClient(["this is not json", '{"summary":"ok"}'])
    result = summarize(client, "transcript")
    assert result.summary == "ok"
    assert result.key_points == []  # defaulted
    assert len(client.calls) == 2


def test_summarize_raises_after_two_bad_replies():
    client = FakeClient(["nope", "still nope"])
    with pytest.raises(ValueError):
        summarize(client, "transcript")


def test_generate_title_strips_quotes_and_whitespace():
    client = FakeClient(['  "Quarterly Roadmap Review"\n'])
    assert generate_title(client, "transcript") == "Quarterly Roadmap Review"
