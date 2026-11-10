import asyncio

import pytest

from services.api import engine
from services.api.direct_answer import answer_directly


@pytest.mark.parametrize(
    "question,expected",
    [
        ("whats 9 plus ten", "9 + 10 = 19"),
        ("What is nine plus ten?", "9 + 10 = 19"),
        ("what is 9 + 10", "9 + 10 = 19"),
        ("what's two plus 3", "2 + 3 = 5"),
        ("what is 7 times 6?", "7 * 6 = 42"),
        ("what is 10 divided by 4?", "10 / 4 = 2.5"),
        ("calculate 2 + 3 * 4", "2 + 3 * 4 = 14"),
    ],
)
def test_direct_arithmetic_answers(question, expected):
    assert answer_directly(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "what is the capital of France?",
        "explain 9 plus ten in binary",
        "I have 9 apples and 10 oranges",
        "what is 2 to the power of 8",
    ],
)
def test_non_arithmetic_questions_fall_through(question):
    assert answer_directly(question) is None


def test_respond_answers_math_without_a_model(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)

    assert asyncio.run(engine.respond("demo", "whats 9 plus ten")) == "9 + 10 = 19"
    assert engine.history("demo")[-1] == {
        "role": "assistant",
        "content": "9 + 10 = 19",
    }
