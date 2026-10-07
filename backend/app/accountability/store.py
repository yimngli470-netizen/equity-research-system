"""Transactional, append-only research records.

Registration uses the actual UTC clock, not a caller-supplied historical timestamp.
Evidence/adjudication adapters are supplied by the caller; nothing fetches data or
starts a model here. PostgreSQL advisory locks serialize writers per logical key.
Qualitative-call admission and finalization commit internally, preserving both
attempts and returned answers across crashes. Run resolution/retry paths in a
dedicated session; other functions leave commit to callers.
"""
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.accountability.contracts import EventContract, Observation, SubmissionInput, VERSION, digest
from app.accountability.resolution import (
    resolving_packet, numeric_resolution, qualitative_request, validate_grades, binary_scores,
)
from app.models.accountability import (
    ResearchEvidence, ResearchEvent, ResearchSubmission, ResearchResolution, ResearchGradeCall,
)


def utcnow():
    return datetime.now(timezone.utc)


async def lock(db, key):
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def save_evidence(db, payload: dict) -> ResearchEvidence:
    key = digest(payload)
    await db.execute(insert(ResearchEvidence).values(id=key, payload=payload).on_conflict_do_nothing())
    return await db.get(ResearchEvidence, key)


async def append_revision(db, model, ticker, values, inputs, *, identity_fields=None):
    """Full forecast identity by default; thesis writers explicitly select opinion fields.

    Market prices/scores remain in the original input snapshot, but do not turn an
    unchanged thesis into another independent opinion. Never refresh an old row.
    """
    await lock(db, f"revision:{model.__tablename__}:{ticker}")
    latest = (await db.execute(select(model).where(model.ticker == ticker)
                              .order_by(model.id.desc()).limit(1))).scalar_one_or_none()
    identity = ({k: values[k] for k in identity_fields} if identity_fields else {"values": values, "inputs": inputs})
    fingerprint = digest(identity)
    same = (all(getattr(latest, k) == values[k] for k in identity_fields)
            if latest is not None and identity_fields else latest is not None and latest.content_sha256 == fingerprint)
    if same:
        return latest
    evidence = await save_evidence(db, {"kind": "prediction_inputs", "inputs": inputs})
    now = utcnow()
    row = model(ticker=ticker, as_of=now.date(), created_at=now, status="open",
                writer_version=VERSION, revision_of=latest.id if latest else None,
                content_sha256=fingerprint, evidence_id=evidence.id, **values)
    db.add(row)
    await db.flush()
    return row


async def register_event(db, contract: EventContract) -> ResearchEvent:
    await lock(db, f"event:{contract.ticker}:{contract.event_key}")
    payload = contract.model_dump(mode="json")
    row = (await db.execute(select(ResearchEvent).where(
        ResearchEvent.ticker == contract.ticker, ResearchEvent.event_key == contract.event_key
    ))).scalar_one_or_none()
    if row:
        if row.contract_sha256 != digest(payload):
            raise ValueError("Event definition is immutable; use a new event_key for a new hypothesis")
        return row
    if utcnow() >= contract.primary_cutoff:
        raise ValueError("Cannot register a backdated primary event")
    row = ResearchEvent(ticker=contract.ticker, event_key=contract.event_key,
                        contract=payload, contract_sha256=digest(payload), created_at=utcnow())
    db.add(row)
    await db.flush()
    return row


async def submit_forecast(db, event: ResearchEvent, submission: SubmissionInput, evidence: list[Observation],
                          *, thesis_id=None, forecast_id=None) -> ResearchSubmission:
    """One primary submission per event/forecaster: first registration. Revisions kept separately."""
    contract = EventContract.model_validate(event.contract)
    await lock(db, f"submission:{event.id}:{submission.forecaster}")
    now = utcnow()
    if submission.information_cutoff > now:
        raise ValueError("Future information cutoff")
    for obs in evidence:
        _, high = obs.publication_bounds()
        if high is None or max(high, obs.observed_at) > submission.information_cutoff:
            raise ValueError("Forecast evidence was not available by information cutoff")
    if len({o.observation_id for o in evidence}) != len(evidence):
        raise ValueError("Duplicate observation ID")
    for mid, cls in ((thesis_id, "thesis"), (forecast_id, "forecast")):
        if mid is not None:
            from app.models.thesis import StockThesis
            from app.models.forecast import Forecast
            parent = await db.get(StockThesis if cls == "thesis" else Forecast, mid)
            if parent is None or parent.ticker != event.ticker:
                raise ValueError("Parent prediction belongs to a different issuer or does not exist")
    payload = submission.model_dump(mode="json")
    snapshot = {"kind": "forecast_evidence", "observations": [o.model_dump(mode="json") for o in evidence]}
    fingerprint = digest({"payload": payload, "evidence": snapshot, "thesis_id": thesis_id, "forecast_id": forecast_id})
    existing = (await db.execute(select(ResearchSubmission).where(
        ResearchSubmission.event_id == event.id, ResearchSubmission.fingerprint == fingerprint
    ))).scalar_one_or_none()
    if existing:
        return existing
    # No later revisions enter the registered score. Register a different future event instead.
    if now >= contract.primary_cutoff or now >= contract.release_window_start:
        raise ValueError("Submission after primary cutoff; cannot backdate a forecast")
    prior = list((await db.execute(select(ResearchSubmission).where(
        ResearchSubmission.event_id == event.id).order_by(ResearchSubmission.ordinal, ResearchSubmission.id))).scalars())
    same = [r for r in prior if r.payload["forecaster"] == submission.forecaster]
    snapshot_row = await save_evidence(db, snapshot)
    row = ResearchSubmission(event_id=event.id, evidence_id=snapshot_row.id,
        revision_of=same[-1].id if same else None, ordinal=(same[-1].ordinal + 1) if same else 1,
        thesis_id=thesis_id, forecast_id=forecast_id,
        payload={**payload, "is_primary": not same}, fingerprint=fingerprint, created_at=now)
    db.add(row)
    await db.flush()
    return row


async def capture_observations(db, observations: list[Observation]):
    """Retain complete supplied vintages. Does not promote mutable financial rows to first releases."""
    now = utcnow()
    for o in observations:
        if o.observed_at > now:
            raise ValueError("Cannot capture future evidence")
        await lock(db, f"observation:{o.observation_id}")
        old = (await db.execute(select(ResearchEvidence).where(
            ResearchEvidence.payload["observation"]["observation_id"].astext == o.observation_id
        ))).scalars().all()
        payload = {"kind": "observation", "observation": o.model_dump(mode="json")}
        if old and any(r.id != digest(payload) for r in old):
            raise ValueError("Observation ID was reused with changed content; create a new vintage ID")
        await save_evidence(db, payload)


async def resolve_events(db, ticker: str, *, grader=None) -> int:
    """Grade registered events. Invalid qualitative batches cannot discard numeric resolutions.

    A grader is an async callable(request)->dict. Normal resolution never retries
    an attempted packet. Only retry_transport_failure permits an explicit, logged
    operator retry of a confirmed no-response failure. Adapters must not retry.
    """
    await lock(db, f"resolve:{ticker}")
    at = utcnow()
    events = (await db.execute(select(ResearchEvent).where(ResearchEvent.ticker == ticker)
                               .order_by(ResearchEvent.id))).scalars().all()
    evidence = (await db.execute(select(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "observation",
        ResearchEvidence.payload["observation"]["ticker"].astext == ticker,
    ))).scalars().all()
    observations = [Observation.model_validate(r.payload["observation"]) for r in evidence]
    pending, numeric = [], []
    for event in events:
        contract = EventContract.model_validate(event.contract)
        if at < contract.occurrence_deadline:
            continue
        prior = (await db.execute(select(ResearchResolution).where(
            ResearchResolution.event_id == event.id).order_by(ResearchResolution.ordinal.desc())
            .limit(1))).scalar_one_or_none()
        if prior and prior.status == "expired_by_policy":
            continue
        packet = resolving_packet(event.id, contract, observations, at)
        packet_hash = digest(packet)
        if (await db.execute(select(ResearchResolution.id).where(
            ResearchResolution.event_id == event.id, ResearchResolution.packet_sha256 == packet_hash
        ))).scalar_one_or_none():
            continue
        item = (event, prior, packet, packet_hash)
        if contract.kind == "qualitative" and packet["observations"]:
            pending.append(item)
        else:
            result = ({"status": packet["status_if_missing"], "outcome": None, "reason": "No admissible observation"}
                      if contract.kind == "qualitative" else numeric_resolution(packet))
            numeric.append((item, result))

    # Deterministic work is independent of inference: admission commits these marks
    # before a qualitative call, and a failed reply cannot discard or delay them.
    written = await _write_resolutions(db, numeric)
    if pending and grader:
        attempted = {
            digest(packet)
            for call in (await db.execute(select(ResearchGradeCall))).scalars()
            for packet in call.request["events"]
        }
        pending = [item for item in pending if item[3] not in attempted]
    if pending and grader:
        request = qualitative_request([item[2] for item in pending])
        written += await _adjudicate(db, ticker, request, pending, grader)
    return written


class ConfirmedNoResponse(Exception):
    """Adapter assertion backed by provider evidence: no answer was produced.

    A generic timeout/connection error does NOT qualify. The eventual transport
    adapter must only raise this for e.g. a request rejected before inference or
    a provider request-status lookup confirming non-execution.
    """
    def __init__(self, message: str, *, confirmation: str):
        if not confirmation.strip():
            raise ValueError("No-response confirmation must be recorded")
        super().__init__(message)
        self.confirmation = confirmation


def _safe_response(raw):
    from app.accountability.contracts import canonical
    try:
        canonical(raw)
        return raw
    except (TypeError, ValueError):
        return {"unserializable_response_repr": repr(raw)}


async def _adjudicate(db, ticker, request, pending, grader):
    request_id = digest(request)
    if await db.get(ResearchGradeCall, request_id) is not None:
        return 0
    db.add(ResearchGradeCall(id=request_id, request=request, response=None,
                             error="in_progress_or_interrupted"))
    await db.commit()  # durable admission + earlier numeric outcomes
    await lock(db, f"resolve:{ticker}")
    raw, returned, grades = None, False, None
    failure_class, error, confirmation = None, None, None
    try:
        raw = await grader(request)
        returned = True
        grades = validate_grades(raw, [item[2] for item in pending])
    except Exception as exc:
        failure_class = ("invalid_response" if returned else
                         "transport_no_response" if isinstance(exc, ConfirmedNoResponse) else
                         "transport_unknown" if isinstance(exc, (TimeoutError, ConnectionError)) else
                         "execution_unknown")
        error = f"{type(exc).__name__}: {exc}"
        confirmation = getattr(exc, "confirmation", None) if failure_class == "transport_no_response" else None
    call = await db.get(ResearchGradeCall, request_id)
    call.response = {"raw_response": _safe_response(raw), "failure_class": failure_class,
                     "no_response_confirmation": confirmation, "finalized_at": utcnow().isoformat()}
    call.error = error
    written = await _write_resolutions(db, [(item, grades[item[0].id]) for item in pending]) if grades else 0
    # Preserve the actual returned answer/failure durably, not only admission.
    await db.commit()
    return written


async def retry_transport_failure(db, failed_call_id: str, *, operator_id: str, reason: str, grader) -> int:
    """Explicit operator action only; never called by resolve_events or a scheduler.

    At most one child per failed receipt. A further retry needs a separate explicit
    action against that child's confirmed failure. Interrupted/uncertain calls and
    invalid answers cannot be retried. Exact evidence must still match current data.
    """
    if not operator_id.strip() or not reason.strip():
        raise ValueError("Retry needs an operator identity and reason")
    failed = await db.get(ResearchGradeCall, failed_call_id)
    if (failed is None or not failed.error
            or (failed.response or {}).get("failure_class") != "transport_no_response"
            or not (failed.response or {}).get("no_response_confirmation")):
        raise ValueError("Only confirmed transport_no_response failures are retryable")
    packets = failed.request["events"]
    tickers = {p["contract"]["ticker"] for p in packets}
    if len(tickers) != 1:
        raise ValueError("Retry must belong to one issuer")
    ticker = tickers.pop()
    await lock(db, f"resolve:{ticker}")
    calls = (await db.execute(select(ResearchGradeCall))).scalars().all()
    if any(c.request.get("operator_retry", {}).get("retry_of") == failed_call_id for c in calls):
        raise ValueError("This failure already has a retry receipt")
    evidence = (await db.execute(select(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "observation",
        ResearchEvidence.payload["observation"]["ticker"].astext == ticker))).scalars().all()
    observations = [Observation.model_validate(r.payload["observation"]) for r in evidence]
    pending = []
    for original in packets:
        event = await db.get(ResearchEvent, original["event_id"])
        if event is None:
            raise ValueError("Missing registered event")
        packet = resolving_packet(event.id, EventContract.model_validate(event.contract), observations, utcnow())
        if digest(packet) != digest(original):
            raise ValueError("Evidence/policy has changed; cannot retry the old packet")
        if (await db.execute(select(ResearchResolution.id).where(
            ResearchResolution.event_id == event.id,
            ResearchResolution.packet_sha256 == digest(packet)))).scalar_one_or_none():
            raise ValueError("Event packet has already been resolved/adjudicated")
        # A different attempted batch must not be bypassed through this old receipt.
        for call in calls:
            if call.id != failed.id and any(digest(p) == digest(packet) for p in call.request["events"]):
                ancestors = set()
                parent = failed
                while parent.request.get("operator_retry"):
                    parent_id = parent.request["operator_retry"]["retry_of"]
                    ancestors.add(parent_id)
                    parent = await db.get(ResearchGradeCall, parent_id)
                if call.id not in ancestors:
                    raise ValueError("A later or separate attempt already exists for this packet")
        pending.append((event, None, packet, digest(packet)))
    request = qualitative_request(packets)
    request["operator_retry"] = {"retry_of": failed.id, "operator_id": operator_id,
        "reason": reason, "authorized_at": utcnow().isoformat(),
        "no_response_confirmation": failed.response["no_response_confirmation"]}
    return await _adjudicate(db, ticker, request, pending, grader)


async def _write_resolutions(db, items):
    written = 0
    for (event, prior, packet, packet_hash), result in items:
        saved = await save_evidence(db, {"kind": "resolution_packet", "packet": packet})
        prior = (await db.execute(select(ResearchResolution).where(
            ResearchResolution.event_id == event.id).order_by(ResearchResolution.ordinal.desc())
            .limit(1))).scalar_one_or_none()
        stmt = insert(ResearchResolution).values(event_id=event.id, evidence_id=saved.id,
            supersedes_id=prior.id if prior else None, ordinal=(prior.ordinal + 1) if prior else 1, status=result["status"],
            payload={"version": VERSION, **result}, packet_sha256=packet_hash, created_at=utcnow()
        ).on_conflict_do_nothing(constraint="uq_research_resolution_packet").returning(ResearchResolution.id)
        if (await db.execute(stmt)).scalar_one_or_none():
            written += 1
    await db.flush()
    return written


async def probability_report(db) -> dict:
    submissions = (await db.execute(select(ResearchSubmission))).scalars().all()
    resolutions = (await db.execute(select(ResearchResolution).order_by(
        ResearchResolution.ordinal, ResearchResolution.id))).scalars().all()
    latest = {r.event_id: r for r in resolutions}
    events = {e.id: e for e in (await db.execute(select(ResearchEvent))).scalars()}
    results = []
    for sub in submissions:
        if not sub.payload["is_primary"]:
            continue
        resolution = latest.get(sub.event_id)
        outcome = resolution.payload.get("outcome") if resolution and resolution.status == "resolved" else None
        p = sub.payload["probability"]
        actual = resolution.payload.get("actual") if resolution and resolution.status == "resolved" else None
        estimate = sub.payload.get("point_estimate")
        error = estimate - actual if estimate is not None and actual is not None else None
        results.append({"submission_id": sub.id, "event_id": sub.event_id,
            "thesis_id": sub.thesis_id, "forecast_id": sub.forecast_id,
            "prediction_evidence_id": sub.evidence_id,
            "resolution_evidence_id": resolution.evidence_id if resolution else None,
            "forecaster": sub.payload["forecaster"], "probability": p,
            "event_cluster": events[sub.event_id].contract["event_cluster"],
            "resolution_id": resolution.id if resolution else None,
            "status": resolution.status if resolution else "pending", "outcome": outcome,
            "point_estimate": estimate, "actual": actual, "absolute_error": abs(error) if error is not None else None,
            "absolute_percentage_error": abs(error / actual) if error is not None and actual else None,
            **binary_scores(p, outcome)})
    scored = [r for r in results if r["brier"] is not None]
    # Never average different forecasters into a purported model score.
    by_forecaster = {}
    for name in sorted({r["forecaster"] for r in results}):
        rows = [r for r in results if r["forecaster"] == name]
        resolved = [r for r in rows if r["brier"] is not None]
        inf = any(r["log_loss_infinite"] for r in resolved)
        by_forecaster[name] = {"n_registered": len(rows), "n_scored": len(resolved),
            "n_resolved": sum(r["status"] == "resolved" for r in rows),
            "n_abstained": sum(r["probability"] is None for r in rows),
            "brier": sum(r["brier"] for r in resolved) / len(resolved) if resolved else None,
            "log_loss": sum(r["log_loss"] for r in resolved) / len(resolved) if resolved and not inf else None,
            "log_loss_infinite": inf}
    calls = (await db.execute(select(ResearchGradeCall))).scalars().all()
    return {"version": VERSION, "n_primary_submissions": len(results), "n_scored": len(scored),
            "n_unique_events": len({r["event_id"] for r in results}),
            "n_event_clusters": len({r["event_cluster"] for r in results}),
            "adjudication_calls": [{"call_id": c.id, "event_ids": [p["event_id"] for p in c.request["events"]],
                                     "error": c.error, "failure_class": (c.response or {}).get("failure_class"),
                                     "operator_retry": c.request.get("operator_retry")} for c in calls],
            "by_forecaster": by_forecaster, "rows": results,
            "note": "First registered submission per event/forecaster only. Correlated clusters and revisions are not independent trials."}
