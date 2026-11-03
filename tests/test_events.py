"""Append-only event log: ordering, immutability, redaction and replay."""
import asyncio
import sqlite3

import pytest

from services.api import events

RUN = "a" * 32


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.sqlite3"))
    yield


def test_sequence_is_monotonic_and_replay_is_contiguous():
    first = events.append(RUN, "run.created", "orchestrator", {"goal": "x"})
    second = events.append(RUN, "step.started", "planner", {"step": 1})
    assert (first["sequence"], second["sequence"]) == (1, 2)
    replayed = events.replay(RUN)
    assert replayed["count"] == 2
    assert replayed["contiguous"] is True
    assert [item["type"] for item in replayed["events"]] == ["run.created", "step.started"]
    assert [item["sequence"] for item in events.list_events(RUN, after=1)] == [2]


def test_events_are_immutable_after_append():
    events.append(RUN, "run.created", "orchestrator", {})
    with events.connect() as con:
        with pytest.raises(sqlite3.DatabaseError):
            con.execute("UPDATE run_events SET actor='tampered' WHERE run_id=?", (RUN,))
        with pytest.raises(sqlite3.DatabaseError):
            con.execute("DELETE FROM run_events WHERE run_id=?", (RUN,))


def test_credentials_are_redacted_recursively():
    event = events.append(RUN, "tool.completed", "builder", {
        "api_key": "sk-live-secret",
        "nested": {"authorization": "Bearer abc", "ok": "visible"},
        "items": [{"password": "hunter2"}],
    })
    payload = event["payload"]
    assert payload["api_key"] == "[redacted]"
    assert payload["nested"]["authorization"] == "[redacted]"
    assert payload["nested"]["ok"] == "visible"
    assert payload["items"][0]["password"] == "[redacted]"


def test_invalid_ids_types_and_oversized_payloads_are_rejected():
    with pytest.raises(ValueError):
        events.append("bad id", "run.created")
    with pytest.raises(ValueError):
        events.append(RUN, "Not A Type")
    with pytest.raises(ValueError):
        events.append(RUN, "run.created", payload={"blob": "x" * 70_000})
    with pytest.raises(ValueError):
        events.list_events("bad id")


def test_sse_frame_has_one_id_and_no_injected_events():
    event = events.append(RUN, "step.completed", "builder", {"text": "a\n\nevent: done"})
    frame = events.encode_sse(event)
    assert frame.startswith("id: 1\nevent: step.completed\ndata: ")
    assert sum(line.startswith("event: ") for line in frame.splitlines()) == 1
    assert frame.endswith("\n\n")


def test_tail_streams_new_events():
    events.append(RUN, "run.created", "orchestrator", {})

    async def collect():
        frames = []
        async for frame in events.tail(RUN, after=0, poll_seconds=0.01, max_seconds=2):
            frames.append(frame)
            if len(frames) >= 2:
                break
        return frames

    async def run():
        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        events.append(RUN, "step.started", "planner", {})
        return await asyncio.wait_for(task, timeout=3)

    frames = asyncio.run(run())
    assert "run.created" in frames[0]
    assert "step.started" in frames[1]
