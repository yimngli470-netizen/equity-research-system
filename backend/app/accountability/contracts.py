"""Explicit event contracts and admissible observations. No date/basis inference."""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, AwareDatetime, model_validator

VERSION = "accountability-v2"


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EventContract(StrictRecord):
    event_key: str = Field(min_length=1, max_length=200)
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    event_family: str = Field(min_length=1)
    event_cluster: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    kind: Literal["numeric", "qualitative", "price"]
    metric: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    accounting_basis: str = Field(min_length=1)
    fiscal_period: str = Field(min_length=1)
    period_end: date
    period_source: str = Field(min_length=1)  # exact issuer calendar/provenance; not end_approx
    primary_cutoff: AwareDatetime
    occurrence_deadline: AwareDatetime
    release_window_start: AwareDatetime
    release_window_end: AwareDatetime
    adjudication_sources: tuple[str, ...] = Field(min_length=1)
    vintage_policy: Literal["first_release", "latest_in_window"]
    missing_policy: Literal["keep_pending", "expire_unscored"]
    comparison: Literal["gt", "ge", "lt", "le", "eq"] | None = None
    threshold: FiniteFloat | None = None
    equality_tolerance: FiniteFloat | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def coherent(self):
        if not (self.primary_cutoff <= self.occurrence_deadline <= self.release_window_end
                and self.primary_cutoff <= self.release_window_start
                and self.release_window_start <= self.release_window_end):
            raise ValueError("Cutoff, occurrence and release dates are inconsistent")
        if self.period_end > self.occurrence_deadline.date():
            raise ValueError("Target period ends after occurrence deadline")
        if self.kind in ("numeric", "price") and (self.comparison is None or self.threshold is None):
            raise ValueError("Numerical events require a comparison and threshold")
        if self.kind == "qualitative" and (self.comparison is not None or self.threshold is not None):
            raise ValueError("Qualitative events use evidence adjudication, not numeric thresholds")
        if (self.comparison == "eq") != (self.equality_tolerance is not None):
            raise ValueError("Equality events require an explicit absolute tolerance in the metric's units; other comparisons cannot specify one")
        if self.kind != "price" and self.accounting_basis == "market_price":
            raise ValueError("Price evidence requires a separate price event")
        if len(set(self.adjudication_sources)) != len(self.adjudication_sources):
            raise ValueError("Duplicate adjudication source")
        return self


class Observation(StrictRecord):
    observation_id: str = Field(min_length=1)
    ticker: str
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1)  # exact captured material, not a URL-only claim
    citation: str = Field(min_length=1)
    coverage: Literal["full_document", "section", "preview"]
    published_at: AwareDatetime | None = None
    published_date: date | None = None
    publication_precision: Literal["timestamp", "date", "unknown"]
    publication_timezone: str = "UTC"
    observed_at: AwareDatetime
    kind: Literal["numeric", "qualitative", "price"]
    metric: str
    unit: str
    accounting_basis: str
    fiscal_period: str
    period_end: date
    value: FiniteFloat | None = None
    is_original_release: bool

    @model_validator(mode="after")
    def source_and_clock(self):
        from zoneinfo import ZoneInfo
        ZoneInfo(self.publication_timezone)
        if hashlib.sha256(self.excerpt.encode()).hexdigest() != self.content_sha256:
            raise ValueError("Captured evidence hash does not match excerpt bytes")
        if self.publication_precision == "timestamp":
            if self.published_at is None or self.published_date is not None:
                raise ValueError("Timestamp precision needs exactly published_at")
            if self.published_at > self.observed_at:
                raise ValueError("Observation predates publication")
        elif self.publication_precision == "date":
            if self.published_date is None or self.published_at is not None:
                raise ValueError("Date precision needs exactly published_date")
            if self.published_date > self.observed_at.astimezone(ZoneInfo(self.publication_timezone)).date():
                raise ValueError("Observation predates publication date")
        elif self.published_at is not None or self.published_date is not None:
            raise ValueError("Unknown publication cannot contain a guessed date")
        if self.kind in ("numeric", "price") and self.value is None:
            raise ValueError("Numerical observation requires a value")
        return self

    def publication_bounds(self):
        """A date has a full-day uncertainty interval; no invented midnight publication."""
        from zoneinfo import ZoneInfo
        if self.publication_precision == "timestamp":
            return self.published_at, self.published_at
        if self.publication_precision == "date":
            zone = ZoneInfo(self.publication_timezone)
            start = datetime.combine(self.published_date, time.min, zone)
            end = datetime.combine(self.published_date + timedelta(days=1), time.min, zone)
            return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        return None, None


class SubmissionInput(StrictRecord):
    forecaster: str = Field(min_length=1)
    information_cutoff: AwareDatetime
    probability: FiniteFloat | None = Field(default=None, ge=0, le=1)
    abstention_reason: str | None = None
    point_estimate: FiniteFloat | None = None
    requested_model: str | None = None
    served_model: str | None = None  # unknown stays null
    prompt_version: str
    call_id: str | None = None
    baseline_id: str | None = None

    @model_validator(mode="after")
    def probability_or_abstention(self):
        if (self.probability is None) != bool(self.abstention_reason):
            raise ValueError("A missing probability requires an abstention reason; .5 is not abstention")
        return self


def exact_fiscal_end(label: str, declared_periods: dict[str, date]) -> date | None:
    """Issuer-specific exact calendar only. Fiscal labels never imply calendar quarter ends."""
    return declared_periods.get(label)
