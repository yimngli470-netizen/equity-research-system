"""Finite public-HTTPS capture CLI. Never imports into a DB or calls a model.

python -m app.research_evidence.collect manifest.json /new/output/directory
One attempt per declared document. A failed directory cannot be rerun/overwritten.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.research_evidence.records import Capture, Manifest, capture_id, text_hash

MAX_BYTES = 4_000_000


def extract_html(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.select("script,style,noscript,nav,header,footer"):
        node.decompose()
    # Keep tables' cell values; original response bytes preserve visual/table layout.
    text = soup.get_text("\n", strip=True)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def fetch(client, source, url):
    for _ in range(4):
        source.validate_url(url)
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers["location"]))
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", "").lower():
                raise ValueError("Only HTML capture supported by this collector; no inferred PDF text")
            chunks, length = [], 0
            for chunk in response.iter_bytes():
                length += len(chunk)
                if length > MAX_BYTES:
                    raise ValueError("Source exceeds declared byte limit")
                chunks.append(chunk)
            return b"".join(chunks), str(response.url)
    raise ValueError("Redirect limit exceeded")


def collect(manifest: Manifest, output: Path, *, client=None):
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "captures").mkdir()
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    sources = {s.source_id: s for s in manifest.sources}
    own_client = client is None
    client = client or httpx.Client(timeout=40, headers={"User-Agent": "ThesisEvidenceResearch/1.0 (personal source verification)"})
    attempts = []
    try:
        for doc in manifest.documents:
            item = {"document_id": doc.document_id, "url": doc.url,
                    "started_at": datetime.now(timezone.utc).isoformat()}
            try:
                raw, url = fetch(client, sources[doc.source_id], doc.url)
                raw_path = output / "raw" / f"{doc.document_id}.html"
                raw_path.write_bytes(raw)
                text = extract_html(raw)
                cap = Capture(document=doc, source=sources[doc.source_id],
                    observed_at=datetime.now(timezone.utc), fetched_url=url,
                    raw_sha256=hashlib.sha256(raw).hexdigest(), text_sha256=text_hash(text),
                    text=text, extraction="beautifulsoup-html-text-v1")
                key = capture_id(cap)
                (output / "captures" / f"{key}.json").write_text(cap.model_dump_json(indent=2) + "\n")
                item.update(status="captured", capture_id=key, raw_sha256=cap.raw_sha256,
                            text_sha256=cap.text_sha256, bytes=len(raw), characters=len(text))
            except Exception as exc:
                item.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            item["ended_at"] = datetime.now(timezone.utc).isoformat()
            attempts.append(item)
            # Preserve each attempt immediately; never pretend a failed capture is evidence.
            with (output / "attempts.jsonl").open("a") as stream:
                stream.write(json.dumps(item) + "\n")
    finally:
        if own_client:
            client.close()
    result = {"study_id": manifest.study_id, "attempts": attempts,
              "captured": sum(a["status"] == "captured" for a in attempts),
              "failed": sum(a["status"] == "failed" for a in attempts)}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def load_captures(directory: Path):
    result = {}
    for path in sorted((directory / "captures").glob("*.json")):
        cap = Capture.model_validate_json(path.read_text())
        if path.stem != capture_id(cap):
            raise ValueError("Capture identity mismatch")
        suffix = ".html" if cap.extraction == "beautifulsoup-html-text-v1" else ".txt"
        raw = directory / "raw" / f"{cap.document.document_id}{suffix}"
        if hashlib.sha256(raw.read_bytes()).hexdigest() != cap.raw_sha256:
            raise ValueError("Raw source bytes changed")
        extracted = extract_html(raw.read_bytes()) if suffix == ".html" else raw.read_text()
        if extracted != cap.text:
            raise ValueError("Captured extraction does not reproduce")
        result[path.stem] = cap
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(collect(Manifest.model_validate_json(args.manifest.read_text()), args.output), indent=2))
