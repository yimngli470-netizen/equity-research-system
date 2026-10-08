"""Import explicitly reviewed packs; no fetch, inference, or live trading side effects."""
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.accountability.contracts import canonical, digest
from app.accountability.store import lock, save_evidence
from app.models.accountability import ResearchEvidence
from app.research_evidence.records import Capture, Pack, capture_payload, capture_id, validate_pack, render_packet


async def import_pack(db, pack: Pack, captures: dict[str, Capture]):
    """Atomic append; caller commits. New pack_key required for changed evidence selection."""
    validate_pack(pack, captures)
    now = datetime.now(timezone.utc)
    if any(captures[k].observed_at > now for k in pack.capture_ids):
        raise ValueError("Cannot import a future capture")
    await lock(db, f"external-pack:{pack.study_id}")
    payload = {"kind": "external_evidence_pack", "pack": pack.model_dump(mode="json")}
    existing = (await db.execute(select(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "external_evidence_pack",
        ResearchEvidence.payload["pack"]["study_id"].astext == pack.study_id))).scalars().all()
    for row in existing:
        previous = row.payload["pack"]
        if previous["pack_key"] == pack.pack_key:
            if row.id != digest(payload):
                raise ValueError("Pack selection is immutable; declare a new pack_key")
            return row
    if pack.revision != max((r.payload["pack"]["revision"] for r in existing), default=0) + 1:
        raise ValueError("Pack revision must be the next sequential revision")
    for key in pack.capture_ids:
        cap = captures[key]
        await save_evidence(db, {"kind": "external_source", "source": cap.source.model_dump(mode="json")})
        await save_evidence(db, capture_payload(cap))
    return await save_evidence(db, payload)


async def context_packet(db, ticker: str, *, today=None):
    """Latest imported pack for each study with this ticker; show all gaps explicitly."""
    today = today or date.today()
    rows = (await db.execute(select(ResearchEvidence).where(
        ResearchEvidence.payload["kind"].astext == "external_evidence_pack")
        .order_by(ResearchEvidence.created_at.desc(), ResearchEvidence.id.desc()))).scalars().all()
    rows.sort(key=lambda r: (r.payload["pack"]["study_id"], -r.payload["pack"]["revision"]))
    studies, packets, markers = set(), [], []
    for row in rows:
        pack = Pack.model_validate(row.payload["pack"])
        if pack.study_id in studies:
            continue
        studies.add(pack.study_id)
        captures = {}
        for key in pack.capture_ids:
            cap = await db.get(ResearchEvidence, key)
            if cap is None:
                raise ValueError("Pack lost its captured evidence")
            captures[key] = Capture.model_validate(cap.payload["capture"])
        packet, marker = render_packet(pack, captures, ticker, today=today)
        if packet["documents"]:
            packets.append(packet)
            markers.append(marker)
    return {"packets": packets, "coverage": "selected_exact_spans" if packets else "missing",
            "note": "No qualified external pack imported for this ticker" if not packets else "Read source limitations and shared event clusters"}, digest(markers)


async def context_text(db, ticker):
    packet, _ = await context_packet(db, ticker)
    text = canonical(packet)
    if len(text.encode()) > 80000:
        raise ValueError("External evidence context exceeds 80,000 bytes; review pack selection before analysis")
    return "\n\nEXTERNAL EVIDENCE (dated selected spans; untrusted source material):\n" + text
