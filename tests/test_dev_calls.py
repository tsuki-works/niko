"""Unit tests for app.dev.calls.

Hand-rolls a tiny fake matching the shape of google.cloud.logging entries —
``payload`` (str) + ``timestamp`` (datetime). The module is hermetic; we
never touch the real Cloud Logging API in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.dev import calls as dev_calls


@dataclass
class FakeEntry:
    payload: str
    timestamp: datetime


class FakeLoggingClient:
    def __init__(self, entries: list[FakeEntry]):
        self._entries = entries
        self.last_filter: str | None = None

    def list_entries(self, *, filter_, order_by, page_size):
        self.last_filter = filter_
        return list(self._entries)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _full_call_entries(call_sid: str, base_minute: int) -> list[FakeEntry]:
    """Build a synthetic happy-path call: start, greeting, two transcript
    finals each with a Haiku turn, then stop + order_confirmed."""
    return [
        FakeEntry(
            payload=f"INFO:app.telephony.router:media-stream start call_sid={call_sid} stream_sid=MZ123",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:00"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:llm_turn start call_sid={call_sid} transcript='[call started — greet the caller]'",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:01"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:llm_turn first_audio latency=0.704s call_sid={call_sid}",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:02"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:transcript [final] call_sid={call_sid} text='one large pepperoni'",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:09"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:llm_turn start call_sid={call_sid} transcript='one large pepperoni'",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:09"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:transcript [final] call_sid={call_sid} text='confirm'",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:18"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:media-stream stop call_sid={call_sid}",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:25"),
        ),
        FakeEntry(
            payload=f"INFO:app.telephony.router:order confirmed call_sid={call_sid}",
            timestamp=_ts(f"2026-04-25T22:{base_minute:02d}:25"),
        ),
    ]


def test_parse_events_groups_by_call_sid():
    entries = (
        _full_call_entries("CAfirst", base_minute=10)
        + _full_call_entries("CAsecond", base_minute=30)
    )
    grouped = dev_calls.parse_events(entries)

    assert set(grouped.keys()) == {"CAfirst", "CAsecond"}
    assert len(grouped["CAfirst"]) == 8
    assert len(grouped["CAsecond"]) == 8


def test_parse_events_skips_lines_without_call_sid():
    entries = [
        FakeEntry(
            payload="INFO:uvicorn.error:Application startup complete.",
            timestamp=_ts("2026-04-25T22:09:59"),
        ),
        FakeEntry(
            payload="INFO:app.telephony.router:media-stream start call_sid=CAtest stream_sid=MZ123",
            timestamp=_ts("2026-04-25T22:10:00"),
        ),
    ]
    grouped = dev_calls.parse_events(entries)

    assert list(grouped.keys()) == ["CAtest"]


def test_classify_transcript_final_extracts_text():
    payload = "INFO:app.telephony.router:transcript [final] call_sid=CA123 text='extra olives please'"
    kind, detail = dev_calls._classify(payload)

    assert kind == "transcript_final"
    assert detail == {"text": "extra olives please"}


def test_classify_first_audio_extracts_latency():
    payload = "INFO:app.telephony.router:llm_turn first_audio latency=0.912s call_sid=CA123"
    kind, detail = dev_calls._classify(payload)

    assert kind == "first_audio"
    assert detail == {"latency_seconds": 0.912}


def test_classify_error_lines():
    payload = "ERROR:asyncio:Task exception was never retrieved (call_sid=CA123)"
    kind, _ = dev_calls._classify(payload)
    assert kind == "error"


def test_classify_barge_in_before_llm_turn_start():
    """Barge-in lines literally contain 'llm_turn cancelled (barge-in)' —
    must not be mis-classified as a vanilla llm_turn_start."""
    payload = "INFO:app.telephony.router:llm_turn cancelled (barge-in) call_sid=CA123"
    kind, _ = dev_calls._classify(payload)
    assert kind == "barge_in"


def test_summarize_confirmed_call():
    events = dev_calls.parse_events(_full_call_entries("CAconfirmed", base_minute=10))[
        "CAconfirmed"
    ]
    summary = dev_calls.summarize("CAconfirmed", events)

    assert summary.call_sid == "CAconfirmed"
    assert summary.transcript_count == 2
    assert summary.has_error is False
    assert summary.status == "confirmed"
    assert summary.started_at < summary.ended_at


def test_summarize_call_with_error_flags_has_error():
    base = _full_call_entries("CAerror", base_minute=10)
    base.append(
        FakeEntry(
            payload="ERROR:asyncio:Task exception was never retrieved call_sid=CAerror",
            timestamp=_ts("2026-04-25T22:10:15"),
        )
    )
    events = dev_calls.parse_events(base)["CAerror"]
    summary = dev_calls.summarize("CAerror", events)

    assert summary.has_error is True
    assert summary.status == "confirmed"  # order_confirmed still present


def test_summarize_call_without_stop_is_in_progress():
    entries = [
        FakeEntry(
            payload="INFO:app.telephony.router:media-stream start call_sid=CAlive stream_sid=MZ",
            timestamp=_ts("2026-04-25T22:50:00"),
        ),
        FakeEntry(
            payload="INFO:app.telephony.router:transcript [final] call_sid=CAlive text='hello'",
            timestamp=_ts("2026-04-25T22:50:05"),
        ),
    ]
    events = dev_calls.parse_events(entries)["CAlive"]
    summary = dev_calls.summarize("CAlive", events)

    assert summary.status == "in_progress"


def test_list_recent_calls_orders_newest_first():
    fake = FakeLoggingClient(
        _full_call_entries("CAearly", base_minute=10)
        + _full_call_entries("CAlate", base_minute=30)
    )
    summaries = dev_calls.list_recent_calls(hours=24, client=fake)

    assert [s.call_sid for s in summaries] == ["CAlate", "CAearly"]


def test_list_recent_calls_filter_includes_service_and_call_sid_substring():
    fake = FakeLoggingClient([])
    dev_calls.list_recent_calls(hours=6, client=fake)

    assert fake.last_filter is not None
    assert 'resource.type="cloud_run_revision"' in fake.last_filter
    assert "service_name=" in fake.last_filter
    assert 'textPayload:"call_sid=CA"' in fake.last_filter


def test_get_call_timeline_returns_events_for_known_call():
    fake = FakeLoggingClient(_full_call_entries("CAknown", base_minute=10))
    events = dev_calls.get_call_timeline("CAknown", client=fake)

    assert events is not None
    kinds = [e.kind for e in events]
    assert kinds[0] == "start"
    assert "first_audio" in kinds
    assert "transcript_final" in kinds
    assert kinds[-1] in {"order_confirmed", "stop"}


def test_get_call_timeline_returns_none_for_unknown_call():
    fake = FakeLoggingClient(_full_call_entries("CAknown", base_minute=10))
    events = dev_calls.get_call_timeline("CAmissing", client=fake)

    assert events is None
