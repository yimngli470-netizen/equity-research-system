"""Per-ticker IR source registry, backed by sources.yaml."""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent / "sources.yaml"
_lock = threading.Lock()
_cache: dict[str, "IRSource"] | None = None


StrategyType = Literal["link_regex", "css_selector", "url_template"]
ArtifactType = Literal["transcript", "prepared_remarks", "press_release", "slides"]


@dataclass
class DiscoveryStrategy:
    type: StrategyType
    pattern: str

    def to_dict(self) -> dict:
        return {"type": self.type, "pattern": self.pattern}


@dataclass
class IRSource:
    ticker: str
    ir_url: str
    strategy: DiscoveryStrategy
    artifact_type: ArtifactType
    notes: str | None = None


def _parse(ticker: str, raw: dict) -> IRSource:
    strat_raw = raw["strategy"]
    return IRSource(
        ticker=ticker,
        ir_url=raw["ir_url"],
        strategy=DiscoveryStrategy(type=strat_raw["type"], pattern=strat_raw["pattern"]),
        artifact_type=raw.get("artifact_type", "transcript"),
        notes=raw.get("notes"),
    )


def _load() -> dict[str, IRSource]:
    if not _REGISTRY_PATH.exists():
        return {}
    with open(_REGISTRY_PATH) as f:
        raw = yaml.safe_load(f) or {}
    return {ticker: _parse(ticker, entry) for ticker, entry in raw.items()}


def get_source(ticker: str) -> IRSource | None:
    """Return the IR config for a ticker, or None if not configured."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return _cache.get(ticker.upper())


def add_source(source: IRSource, overwrite: bool = False) -> bool:
    """Write a NEW IR source entry to sources.yaml (used by auto-discovery bootstrap).

    Returns True if written, False if an entry already exists and overwrite=False.
    """
    global _cache
    with _lock:
        raw = {}
        if _REGISTRY_PATH.exists():
            with open(_REGISTRY_PATH) as f:
                raw = yaml.safe_load(f) or {}
        key = source.ticker.upper()
        if key in raw and not overwrite:
            return False
        raw[key] = {
            "ir_url": source.ir_url,
            "strategy": source.strategy.to_dict(),
            "artifact_type": source.artifact_type,
            "notes": source.notes or "",
        }
        with open(_REGISTRY_PATH, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False)
        _cache = None
        logger.info("Added IR source for %s: %s", key, source.ir_url)
        return True


def update_strategy(ticker: str, new_strategy: DiscoveryStrategy) -> None:
    """Persist a repaired discovery strategy back to sources.yaml.

    Called by repair.py after the LLM finds a working pattern, so the next
    run doesn't pay the LLM cost again.
    """
    global _cache
    with _lock:
        if not _REGISTRY_PATH.exists():
            logger.warning("Cannot update strategy: %s does not exist", _REGISTRY_PATH)
            return
        with open(_REGISTRY_PATH) as f:
            raw = yaml.safe_load(f) or {}
        ticker_key = ticker.upper()
        if ticker_key not in raw:
            logger.warning("Cannot update strategy: %s not in registry", ticker_key)
            return
        raw[ticker_key]["strategy"] = new_strategy.to_dict()
        with open(_REGISTRY_PATH, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False)
        _cache = None
        logger.info("Persisted new strategy for %s: %s", ticker_key, new_strategy.to_dict())
