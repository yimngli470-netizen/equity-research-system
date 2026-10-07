"""Regressions for Claude review P1-P6; all data/model responses are synthetic."""
import copy
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select, func

from app.accountability import store
from app.accountability.contracts import EventContract, digest
from app.accountability.resolution import numeric_resolution
from app.models.accountability import ResearchEvidence, ResearchGradeCall, ResearchResolution
from app.models.thesis import StockThesis
from app.models.price import DailyPrice
from tests.test_accountability import (BEFORE, AFTER, UTC, contract, observation, packet,
    submission, setup_event, qualitative_contract, qualitative_observation, good_answer)


def price(ticker, on, close):
    return DailyPrice(ticker=ticker, date=on, open=close, high=close, low=close,
                      close=close, adj_close=close, volume=100)


async def test_P1_market_marks_update_without_changing_original_grades(db, client):
    from app.thesis.grading import grade_due_theses
    from app.thesis.market_marks import latest_market_marks, mark_thesis_returns
    from app.agents.synthesis import _own_track_record
    from app.notes.builder import _gather
    original = {"hit_rate": .5, "realized_return": -.1, "excess_return": -.12}
    th = StockThesis(ticker="TEST", as_of=BEFORE.date(), price_at=100, kill_criteria=[],
                     status="graded", outcome=copy.deepcopy(original), conviction=.8)
    db.add_all([th, price("SPY", BEFORE.date(), 200),
        price("TEST", date(2025, 10, 2), 110), price("SPY", date(2025, 10, 2), 204),
        price("TEST", date(2025, 10, 3), 125)])
    await db.commit()
    assert await grade_due_theses(db, "TEST") == 0  # mark is not an event resolution
    marks = await latest_market_marks(db, "TEST")
    assert marks[th.id]["mark_date"] == "2025-10-02"  # unmatched newer stock candle excluded
    assert marks[th.id]["realized_return"] == pytest.approx(.1)
    assert marks[th.id]["benchmark_return"] == pytest.approx(.02)
    assert marks[th.id]["excess_return"] == pytest.approx(.08)
    assert await mark_thesis_returns(db, "TEST") == 0
    db.add(price("SPY", date(2025, 10, 3), 210))
    await db.commit()
    await grade_due_theses(db, "TEST")
    marks = await latest_market_marks(db, "TEST")
    assert marks[th.id]["excess_return"] == pytest.approx(.2)
    assert marks[th.id]["mark_date"] == "2025-10-03"
    await db.refresh(th)
    assert th.outcome == original and th.status == "graded"
    rows = (await client.get("/api/track-record/theses")).json()
    assert rows[0]["return_source"] == "separate_market_mark"
    assert rows[0]["excess_return"] == pytest.approx(.2)
    assert "grading is frozen" in rows[0]["grading_note"]
    summary = (await client.get("/api/track-record/summary")).json()
    assert summary["mean_excess_return"] == -.12  # historical field remains historical
    assert summary["mean_marked_excess_return"] == pytest.approx(.2)
    context = await _own_track_record(db, "TEST")
    assert "grading is frozen" in context and "2025-10-03" in context
    assert "not evidence of fundamental" in context
    gathered = await _gather(db, "TEST")
    assert gathered["market_marks"][th.id]["excess_return"] == pytest.approx(.2)
    assert (await db.execute(select(func.count()).select_from(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "legacy_thesis_market_mark"))).scalar_one() == 2
    # Resolution admission reads only qualified observations, never market marks.
    assert await store.resolve_events(db, "TEST") == 0


@pytest.mark.parametrize("kind", ["numeric", "qualitative", "price"])
def test_P2_claude_release_before_cutoff_probe_rejected(kind):
    changes = dict(kind=kind, period_end=date(2026, 10, 25),
        release_window_start=datetime(2026, 11, 18, tzinfo=UTC),
        primary_cutoff=datetime(2026, 11, 25, tzinfo=UTC),
        occurrence_deadline=datetime(2026, 11, 30, tzinfo=UTC),
        release_window_end=datetime(2026, 12, 15, tzinfo=UTC))
    if kind == "qualitative":
        changes.update(comparison=None, threshold=None)
    with pytest.raises(ValidationError, match="inconsistent"):
        contract(**changes)


async def test_P2_no_submission_at_release_or_primary_cutoff(db, monkeypatch):
    spec = contract(release_window_start=datetime(2025, 11, 1, tzinfo=UTC))
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    event = await store.register_event(db, spec)
    await db.commit()
    monkeypatch.setattr(store, "utcnow", lambda: spec.primary_cutoff)
    with pytest.raises(ValueError, match="cutoff"):
        await store.submit_forecast(db, event, submission(), [])
    with pytest.raises(ValueError, match="backdated"):
        await store.register_event(db, contract(event_key="too-late", release_window_start=spec.primary_cutoff))


async def test_P3_same_opinion_new_price_and_score_reuses_original_snapshot(db, monkeypatch):
    from app.models.analysis import AnalysisReport
    from app.models.score import StockScore
    from app.thesis.journal import snapshot_thesis
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    db.add(AnalysisReport(ticker="TEST", agent_type="judge", run_date=BEFORE.date(),
                          report={"leaning": "bull", "conviction": .8, "kill_criteria": []}))
    db.add(price("TEST", BEFORE.date(), 100))
    await db.commit()
    first = await snapshot_thesis(db, "TEST", "BUY")
    next_day = BEFORE + timedelta(days=1)
    monkeypatch.setattr(store, "utcnow", lambda: next_day)
    db.add(price("TEST", next_day.date(), 150))
    db.add(StockScore(ticker="TEST", date=next_day.date(), composite_score=.9, signal="STRONG_BUY",
        **{f"{name}_score": .5 for name in ("growth", "profitability", "valuation", "momentum", "sentiment", "risk", "event")}))
    await db.commit()
    same = await snapshot_thesis(db, "TEST", "BUY")
    assert same.id == first.id and first.price_at == 100
    source = await db.get(ResearchEvidence, first.evidence_id)
    assert source.payload["inputs"]["price_at"] == 100
    assert source.payload["inputs"]["price_date"] == BEFORE.date().isoformat()
    changed = await snapshot_thesis(db, "TEST", "HOLD")
    assert changed.id != first.id and changed.revision_of == first.id and changed.price_at == 150
    assert (await db.execute(select(func.count()).select_from(StockThesis))).scalar_one() == 2


@pytest.mark.parametrize("failure", ["confirmed", "timeout", "connection", "invalid", "exception"])
async def test_P4_failure_classification_and_explicit_retry_only(db, monkeypatch, failure):
    event = await setup_event(db, monkeypatch, qualitative_contract())
    await store.capture_observations(db, [qualitative_observation()])
    calls = []
    async def fail(request):
        calls.append(request)
        if failure == "confirmed":
            raise store.ConfirmedNoResponse("Request not executed", confirmation="Mock provider status req-1: rejected before inference")
        if failure == "timeout": raise TimeoutError("No observed answer; execution unknown")
        if failure == "connection": raise ConnectionError("Connection reset")
        if failure == "exception": raise RuntimeError("Unknown adapter failure")
        return {"grades": []}
    assert await store.resolve_events(db, "TEST", grader=fail) == 0
    receipt = (await db.execute(select(ResearchGradeCall))).scalar_one()
    classes = {"confirmed": "transport_no_response", "timeout": "transport_unknown", "connection": "transport_unknown",
               "invalid": "invalid_response", "exception": "execution_unknown"}
    assert receipt.response["failure_class"] == classes[failure]
    assert await store.resolve_events(db, "TEST", grader=fail) == 0 and len(calls) == 1
    async def success(request):
        calls.append(request)
        return good_answer(event.id)
    if failure != "confirmed":
        with pytest.raises(ValueError, match="Only confirmed"):
            await store.retry_transport_failure(db, receipt.id, operator_id="tester", reason="investigated", grader=success)
        assert len(calls) == 1
        return
    with pytest.raises(ValueError, match="operator"):
        await store.retry_transport_failure(db, receipt.id, operator_id="", reason="investigated", grader=success)
    assert await store.retry_transport_failure(db, receipt.id, operator_id="tester", reason="Provider confirmed non-execution", grader=success) == 1
    receipts = (await db.execute(select(ResearchGradeCall))).scalars().all()
    assert len(receipts) == len(calls) == 2
    retried = next(r for r in receipts if r.id != receipt.id)
    assert retried.request["operator_retry"]["retry_of"] == receipt.id
    assert retried.request["operator_retry"]["operator_id"] == "tester"
    assert receipt.error is not None and retried.error is None
    with pytest.raises(ValueError, match="already has a retry"):
        await store.retry_transport_failure(db, receipt.id, operator_id="tester", reason="again", grader=success)
    assert len(calls) == 2


async def test_P4_crash_receipt_never_implicitly_retries(db, monkeypatch):
    event = await setup_event(db, monkeypatch, qualitative_contract())
    await store.capture_observations(db, [qualitative_observation()])
    async def crash(_):
        raise KeyboardInterrupt("simulated process interruption")
    with pytest.raises(KeyboardInterrupt):
        await store.resolve_events(db, "TEST", grader=crash)
    await db.rollback()
    receipt = (await db.execute(select(ResearchGradeCall))).scalar_one()
    assert receipt.error == "in_progress_or_interrupted" and receipt.response is None
    async def must_not_call(_):
        raise AssertionError("Must not run")
    assert await store.resolve_events(db, "TEST", grader=must_not_call) == 0
    with pytest.raises(ValueError, match="Only confirmed"):
        await store.retry_transport_failure(db, receipt.id, operator_id="tester", reason="a crash is not confirmation", grader=must_not_call)


async def test_P5_qualitative_failure_cannot_delay_numeric_results(db, monkeypatch):
    qualitative = await setup_event(db, monkeypatch, qualitative_contract())
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    numeric = await store.register_event(db, contract(event_key="numeric"))
    await db.commit()
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    await store.capture_observations(db, [qualitative_observation(), observation(observation_id="numeric")])
    async def invalid(_):
        # Already written before model inference, not deferred to a later morning.
        assert (await db.execute(select(ResearchResolution).where(ResearchResolution.event_id == numeric.id))).scalar_one().status == "resolved"
        return {"grades": []}
    assert await store.resolve_events(db, "TEST", grader=invalid) == 1
    await db.rollback()  # even caller failure cannot undo durably admitted numeric accounting
    rows = (await db.execute(select(ResearchResolution))).scalars().all()
    assert len(rows) == 1 and rows[0].event_id == numeric.id and rows[0].payload["outcome"] == 1


@pytest.mark.parametrize("tolerance,value,outcome", [(1e-9, 1.1000000001, 1), (1e-9, 1.100000001, 1),
                                                     (1e-9, 1.1000000011, 0), (0, 1.1000000001, 0), (0, 1.1, 1)])
def test_P6_declared_equality_tolerance(tolerance, value, outcome):
    spec = contract(comparison="eq", threshold=1.1, equality_tolerance=tolerance)
    result = numeric_resolution(packet(spec, [observation(value=value)]))
    assert result["outcome"] == outcome


@pytest.mark.parametrize("changes", [{"comparison": "eq"}, {"equality_tolerance": .01},
    {"comparison": "eq", "equality_tolerance": -.01}, {"comparison": "eq", "equality_tolerance": float("inf")}])
def test_P6_equality_tolerance_is_required_and_finite(changes):
    with pytest.raises(ValidationError):
        contract(**changes)
