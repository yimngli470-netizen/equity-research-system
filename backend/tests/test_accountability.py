"""Phase-2 acceptance: synthetic clocks/evidence, disposable DB, zero real models."""
import copy
import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select, func

from app.accountability import store
from app.accountability.contracts import EventContract, Observation, SubmissionInput, digest
from app.accountability.resolution import resolving_packet, numeric_resolution, validate_grades, binary_scores
from app.models.accountability import ResearchResolution, ResearchSubmission, ResearchGradeCall, ResearchEvidence
from app.models.thesis import StockThesis
from app.models.forecast import Forecast
from app.thesis.grading import _parse_by_date

UTC = timezone.utc
BEFORE = datetime(2025, 10, 1, tzinfo=UTC)
AFTER = datetime(2026, 3, 1, tzinfo=UTC)


def contract(**changes):
    data = dict(event_key="q1-eps", ticker="TEST", event_family="eps", event_cluster="TEST-q1",
        statement="Q1 FY2026 GAAP diluted EPS is at least USD 1 per share",
        kind="numeric", metric="eps_diluted", unit="USD/share", accounting_basis="gaap",
        fiscal_period="Q1 FY2026", period_end=date(2025, 12, 31),
        period_source="Synthetic September-year-end issuer calendar, exact quarter",
        primary_cutoff=datetime(2025, 11, 1, tzinfo=UTC),
        occurrence_deadline=datetime(2025, 12, 31, 23, 59, tzinfo=UTC),
        release_window_start=datetime(2026, 1, 1, tzinfo=UTC),
        release_window_end=datetime(2026, 2, 20, tzinfo=UTC),
        adjudication_sources=("issuer-release",), vintage_policy="first_release",
        missing_policy="keep_pending", comparison="ge", threshold=1.0)
    data.update(changes)
    return EventContract(**data)


def observation(**changes):
    data = dict(observation_id="q1-original", ticker="TEST", source_id="issuer-release",
        source_url="https://example.test/q1", document_version="original",
        excerpt="GAAP diluted EPS was $1.25 in Q1 FY2026.", citation="EPS table, Q1 row",
        coverage="section", published_at=datetime(2026, 1, 20, 12, tzinfo=UTC),
        publication_precision="timestamp", observed_at=datetime(2026, 1, 20, 13, tzinfo=UTC),
        kind="numeric", metric="eps_diluted", unit="USD/share", accounting_basis="gaap",
        fiscal_period="Q1 FY2026", period_end=date(2025, 12, 31), value=1.25,
        is_original_release=True)
    data.update(changes)
    data["content_sha256"] = hashlib.sha256(data["excerpt"].encode()).hexdigest()
    return Observation(**data)


def submission(**changes):
    data = dict(forecaster="synthetic-analyst", information_cutoff=BEFORE, probability=.8,
                requested_model="mock", served_model=None, prompt_version="test-1")
    data.update(changes)
    return SubmissionInput(**data)


def packet(e=None, obs=None, at=AFTER):
    return resolving_packet("event-one", e or contract(), obs if obs is not None else [observation()], at)


def test_T01_fiscal_quarter_is_not_calendar_quarter():
    assert _parse_by_date("Q1 FY2026") is None
    assert _parse_by_date("Q1 FY2026", {"Q1 FY2026": date(2025, 12, 31)}) == date(2025, 12, 31)
    assert _parse_by_date("2025-12-31") == date(2025, 12, 31)
    assert _parse_by_date("2025-12-31 extra") is None
    assert numeric_resolution(packet())["outcome"] == 1


@pytest.mark.parametrize("changes", [
    {"published_at": datetime(2026, 2, 21, tzinfo=UTC), "observed_at": AFTER},
    {"observed_at": AFTER + timedelta(days=1)},
    {"publication_precision": "unknown", "published_at": None},
    {"source_id": "other-source"}, {"coverage": "preview"},
])
def test_T02_unavailable_or_ineligible_evidence_is_unscored(changes):
    assert numeric_resolution(packet(obs=[observation(**changes)]))["status"] == "pending"


@pytest.mark.parametrize("changes", [
    {"period_end": date(2026, 1, 31)}, {"fiscal_period": "Q2 FY2026"},
    {"accounting_basis": "non_gaap"}, {"unit": "EUR/share"}, {"ticker": "OTHER"},
    {"metric": "eps_basic"},
])
def test_T03_no_adjacent_period_basis_or_identity_match(changes):
    assert not packet(obs=[observation(**changes)])["observations"]


def test_T04_later_prices_do_not_enter_operating_resolution():
    price = observation(observation_id="price", kind="price", metric="close", accounting_basis="market_price", value=50)
    first = packet(obs=[observation(), price])
    changed = packet(obs=[price.model_copy(update={"value": 500}), observation()])
    assert first == changed == packet()
    assert numeric_resolution(first) == numeric_resolution(changed)


def test_T05_later_good_quarter_cannot_rescue_miss():
    current = observation(value=.5, excerpt="GAAP EPS was $0.50 in Q1 FY2026.")
    later = observation(observation_id="q2", fiscal_period="Q2 FY2026", period_end=date(2026, 3, 31), value=5)
    result = numeric_resolution(packet(obs=[later, current]))
    assert result["outcome"] == 0 and result["actual"] == .5


@pytest.mark.parametrize("model,values", [
    (StockThesis, {"leaning": "bull", "conviction": .8, "kill_criteria": []}),
    (Forecast, {"assumptions": {"growth": .1}, "projections": {"base": {"eps": 1}}}),
])
async def test_T06_T12_same_day_revision_preserves_old_grade_and_deduplicates(db, monkeypatch, model, values):
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    first = await store.append_revision(db, model, "TEST", values, {"fingerprint": "one"})
    first.outcome = {"legacy_sentinel": True}
    await db.commit()
    same = await store.append_revision(db, model, "TEST", values, {"fingerprint": "one"})
    assert same.id == first.id
    altered = copy.deepcopy(values)
    if model is StockThesis:
        altered["leaning"] = "bear"
    else:
        altered["projections"]["base"]["eps"] = 2
    second = await store.append_revision(db, model, "TEST", altered, {"fingerprint": "two"})
    await db.commit()
    assert second.id != first.id and second.revision_of == first.id
    assert second.as_of == first.as_of
    assert first.outcome == {"legacy_sentinel": True} and second.outcome is None
    assert first.evidence_id != second.evidence_id
    assert (await db.execute(select(func.count()).select_from(model))).scalar_one() == 2


async def test_T07_conviction_has_no_probability_score_or_sizing_effect(db):
    from app.thesis.calibration import compute_calibration, calibration_shrink
    db.add(StockThesis(ticker="TEST", as_of=BEFORE.date(), conviction=.8, leaning="bull",
                      kill_criteria=[], status="graded", outcome={"hit_rate": 0, "realized_return": 1}))
    await db.commit()
    result = await compute_calibration(db)
    assert result["overall"]["brier_hit"] is None
    assert result["event_probabilities"]["n_scored"] == 0
    assert result["legacy_diagnostics"]["overall"]["brier_hit"] == .64
    assert await calibration_shrink(db, None) == (1.0, None)


def test_T08_binary_scores_no_partial_imputation():
    assert binary_scores(.8, 1)["brier"] == pytest.approx(.04)
    assert binary_scores(.8, 0)["brier"] == pytest.approx(.64)
    assert binary_scores(.8, 1)["log_loss"] == pytest.approx(.223143551)
    assert binary_scores(0., 1) == {"brier": 1., "log_loss": None, "log_loss_infinite": True}
    assert binary_scores(1., 1)["log_loss"] == 0
    assert binary_scores(None, 1)["brier"] is None
    with pytest.raises(ValueError):
        binary_scores(.8, .5)
    for p in (float("nan"), float("inf"), -.1, 1.1, True):
        with pytest.raises(ValueError):
            binary_scores(p, 1)


async def setup_event(db, monkeypatch, spec=None):
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    event = await store.register_event(db, spec or contract())
    await store.submit_forecast(db, event, submission(), [])
    await db.commit()
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    return event


async def test_T09_pending_resolves_when_later_observed_eligible_evidence_arrives(db, monkeypatch):
    event = await setup_event(db, monkeypatch)
    assert await store.resolve_events(db, "TEST") == 1
    await db.commit()
    assert await store.resolve_events(db, "TEST") == 0
    await store.capture_observations(db, [observation(observed_at=AFTER)])
    assert await store.resolve_events(db, "TEST") == 1
    await db.commit()
    rows = list((await db.execute(select(ResearchResolution).where(ResearchResolution.event_id == event.id))).scalars())
    assert sorted(r.status for r in rows) == ["pending", "resolved"]
    assert next(r for r in rows if r.status == "resolved").supersedes_id == next(r for r in rows if r.status == "pending").id
    report = await store.probability_report(db)
    assert report["n_scored"] == 1
    assert report["by_forecaster"]["synthetic-analyst"]["brier"] == pytest.approx(.04)


def qualitative_contract():
    return contract(kind="qualitative", metric="production_started", unit="boolean", accounting_basis="operating",
                    statement="Commercial production started by quarter end", comparison=None, threshold=None)


def qualitative_observation():
    return observation(kind="qualitative", metric="production_started", unit="boolean", accounting_basis="operating",
                       value=None, excerpt="Commercial production started during Q1 FY2026.")


def good_answer(eid):
    return {"grades": [{"event_id": eid, "status": "resolved", "outcome": 1,
        "evidence": [{"observation_id": "q1-original", "quote": "Commercial production started"}]}]}


@pytest.mark.parametrize("mode", ["foreign", "duplicate", "missing", "invalid_status", "partial", "false_citation", "bool_outcome"])
async def test_T10_invalid_grader_batch_preserved_without_resolution_or_reroll(db, monkeypatch, mode):
    event = await setup_event(db, monkeypatch, qualitative_contract())
    await store.capture_observations(db, [qualitative_observation()])
    calls = []
    async def grader(request):
        calls.append(request)
        out = good_answer(event.id)
        if mode == "foreign": out["grades"][0]["event_id"] = "other"
        if mode == "duplicate": out["grades"].append(copy.deepcopy(out["grades"][0]))
        if mode == "missing": out["grades"] = []
        if mode == "invalid_status": out["grades"][0]["status"] = "hit"
        if mode == "partial": out["grades"][0]["outcome"] = .5
        if mode == "false_citation": out["grades"][0]["evidence"][0]["quote"] = "invented"
        if mode == "bool_outcome": out["grades"][0]["outcome"] = True
        return out
    assert await store.resolve_events(db, "TEST", grader=grader) == 0
    await db.commit()
    assert (await db.execute(select(func.count()).select_from(ResearchResolution))).scalar_one() == 0
    receipt = (await db.execute(select(ResearchGradeCall))).scalar_one()
    assert receipt.error and receipt.response is not None
    assert await store.resolve_events(db, "TEST", grader=grader) == 0
    assert len(calls) == 1


async def test_valid_qualitative_grade_and_no_price_context(db, monkeypatch):
    event = await setup_event(db, monkeypatch, qualitative_contract())
    await store.capture_observations(db, [qualitative_observation(), observation(observation_id="price-only", kind="price", metric="close")])
    async def grader(request):
        assert "close" not in str(request) and "price_at" not in str(request)
        return good_answer(event.id)
    assert await store.resolve_events(db, "TEST", grader=grader) == 1
    await db.commit()
    assert (await store.probability_report(db))["n_scored"] == 1


async def test_T11_vintages_preserved_and_latest_policy_appends_resolution(db, monkeypatch):
    event = await setup_event(db, monkeypatch, contract(vintage_policy="latest_in_window"))
    await store.capture_observations(db, [observation()])
    await store.resolve_events(db, "TEST")
    await db.commit()
    revised = observation(observation_id="q1-restatement", document_version="restated", value=.5,
        excerpt="Restated diluted EPS: $0.50.", is_original_release=False,
        published_at=datetime(2026, 2, 1, tzinfo=UTC), observed_at=datetime(2026, 2, 2, tzinfo=UTC))
    await store.capture_observations(db, [revised])
    await store.resolve_events(db, "TEST")
    await db.commit()
    rows = list((await db.execute(select(ResearchResolution))).scalars())
    assert len(rows) == 2 and {r.payload["outcome"] for r in rows} == {0, 1}
    assert len(list((await db.execute(select(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "observation"))).scalars())) == 2
    assert numeric_resolution(packet(obs=[observation(), revised]))["actual"] == 1.25


async def test_primary_prediction_fixed_and_revisions_not_pseudoreplicated(db, monkeypatch):
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    event = await store.register_event(db, contract())
    a = await store.submit_forecast(db, event, submission(), [])
    assert (await store.submit_forecast(db, event, submission(), [])).id == a.id
    b = await store.submit_forecast(db, event, submission(probability=.1), [])
    assert b.revision_of == a.id and not b.payload["is_primary"]
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    with pytest.raises(ValueError, match="cutoff"):
        await store.submit_forecast(db, event, submission(probability=.9), [])
    await store.capture_observations(db, [observation()])
    await store.resolve_events(db, "TEST")
    await db.commit()
    report = await store.probability_report(db)
    assert report["n_primary_submissions"] == report["n_unique_events"] == 1
    assert report["by_forecaster"]["synthetic-analyst"]["brier"] == pytest.approx(.04)


def test_date_precision_unknown_and_conflicting_actuals():
    dated = observation(published_at=None, publication_precision="date", published_date=date(2026, 1, 20))
    assert not packet(obs=[dated], at=datetime(2026, 1, 20, 23, tzinfo=UTC))["observations"]
    assert packet(obs=[dated], at=datetime(2026, 1, 21, tzinfo=UTC))["observations"]
    conflict = observation(observation_id="conflict", value=2, excerpt="EPS: 2.")
    assert numeric_resolution(packet(obs=[observation(), conflict]))["status"] == "disputed"
    assert numeric_resolution(packet(contract(missing_policy="expire_unscored"), []))["status"] == "expired_by_policy"


async def test_legacy_forecast_and_thesis_outcomes_unchanged_without_contracts(db):
    from app.forecast.grading import grade_due_forecasts
    from app.thesis.grading import grade_due_theses
    from app.models.financial import Financial
    original = {"sentinel": [1, 2, 3], "quarters": {"1": {"actual_eps": 4}}}
    f = Forecast(ticker="TEST", as_of=BEFORE.date(), assumptions={}, projections={"base": {"quarters": [
        {"q": 1, "end_approx": "2025-12-31", "eps": 1}]}}, outcome=copy.deepcopy(original))
    t = StockThesis(ticker="TEST", as_of=BEFORE.date(), kill_criteria=[{"by_date": "Q1 FY2026"}], outcome=copy.deepcopy(original))
    db.add_all([f, t, Financial(ticker="TEST", period="Q1 FY2026", period_end_date=date(2025, 12, 31), eps=2)])
    await db.commit()
    assert await grade_due_forecasts(db, "TEST") == await grade_due_theses(db, "TEST") == 0
    await db.refresh(f); await db.refresh(t)
    assert f.outcome == t.outcome == original


async def test_reject_reused_observation_id_and_event_definition(db, monkeypatch):
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    await store.register_event(db, contract())
    with pytest.raises(ValueError, match="immutable"):
        await store.register_event(db, contract(threshold=3))
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    await store.capture_observations(db, [observation()])
    with pytest.raises(ValueError, match="reused"):
        await store.capture_observations(db, [observation(value=3)])


@pytest.mark.parametrize("changes", [{"probability": None}, {"probability": float("nan")},
                                       {"probability": .8, "abstention_reason": "No opinion"}])
def test_invalid_submission_contract(changes):
    with pytest.raises(ValidationError):
        submission(**changes)


async def test_failed_event_not_rerolled_when_batch_membership_changes(db, monkeypatch):
    event = await setup_event(db, monkeypatch, qualitative_contract())
    await store.capture_observations(db, [qualitative_observation()])
    requests = []
    async def invalid(request):
        requests.append(request)
        return {"grades": []}
    assert await store.resolve_events(db, "TEST", grader=invalid) == 0
    await db.commit()
    # A different, already registered future event now becomes due. Its admission must
    # not include the first failed event again just because the batch hash changed.
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    other = await store.register_event(db, qualitative_contract().model_copy(update={"event_key": "second-event"}))
    await db.commit()
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    async def valid(request):
        requests.append(request)
        assert [p["event_id"] for p in request["events"]] == [other.id]
        return good_answer(other.id)
    assert await store.resolve_events(db, "TEST", grader=valid) == 1
    await db.commit()
    assert len(requests) == 2
    report = await store.probability_report(db)
    assert len(report["adjudication_calls"]) == 2
    assert any(c["event_ids"] == [event.id] and c["error"] for c in report["adjudication_calls"])


async def test_real_journal_saves_changed_same_day_judge_and_input_snapshot(db):
    from app.models.analysis import AnalysisReport
    from app.thesis.journal import snapshot_thesis
    db.add(AnalysisReport(ticker="TEST", agent_type="judge", run_date=BEFORE.date(),
                          report={"leaning": "bull", "conviction": .8, "kill_criteria": []}))
    await db.commit()
    first = await snapshot_thesis(db, "TEST", "BUY")
    assert (await snapshot_thesis(db, "TEST", "BUY")).id == first.id
    db.add(AnalysisReport(ticker="TEST", agent_type="judge", run_date=BEFORE.date(),
                          report={"leaning": "bear", "conviction": .6, "kill_criteria": []}))
    await db.commit()
    second = await snapshot_thesis(db, "TEST", "REDUCE")
    assert first.leaning == "bull" and second.leaning == "bear" and second.revision_of == first.id
    saved = await db.get(ResearchEvidence, first.evidence_id)
    assert saved.payload["inputs"]["judge"]["leaning"] == "bull"


async def test_concurrent_snapshot_writers_do_not_duplicate(engine, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def write():
        async with sessions() as session:
            result = await store.append_revision(session, StockThesis, "TEST",
                {"leaning": "bull", "kill_criteria": []}, {"input": "unchanged"})
            await session.commit()
            return result.id
    assert len(set(await asyncio.gather(write(), write()))) == 1


async def test_numeric_registration_resolution_and_readonly_api(client, db, monkeypatch):
    monkeypatch.setattr(store, "utcnow", lambda: BEFORE)
    event = await store.register_event(db, contract())
    # A numerical point forecast need not assert a probability of a separate threshold.
    await store.submit_forecast(db, event, submission(probability=None, abstention_reason="Point forecast only",
                                                    point_estimate=1.0), [])
    await db.commit()
    monkeypatch.setattr(store, "utcnow", lambda: AFTER)
    await store.capture_observations(db, [observation()])
    from app.forecast.grading import grade_due_forecasts
    assert await grade_due_forecasts(db, "TEST") == 1
    result = await client.get("/api/track-record/events")
    assert result.status_code == 200
    row = result.json()["rows"][0]
    assert row["actual"] == 1.25 and row["absolute_error"] == .25
    assert row["absolute_percentage_error"] == .2 and row["brier"] is None
    assert row["resolution_evidence_id"] and row["prediction_evidence_id"]
