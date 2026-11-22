"""Shared HTTP + persistence helpers for data connectors."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import DataRecord, DataSourceStatus

log = logging.getLogger("agrosphere.connectors")

try:  # Use the OS trust store (corporate proxies / antivirus TLS inspection)
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    pass


class ConnectorError(RuntimeError):
    pass


def http_get(url: str, params: dict | None = None, timeout: float | None = None) -> httpx.Response:
    s = get_settings()
    try:
        r = httpx.get(url, params=params, timeout=timeout or s.http_timeout_s,
                      headers={"User-Agent": s.http_user_agent}, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ConnectorError(f"{url}: {e}") from e
    if r.status_code == 429:
        raise ConnectorError(f"{url}: rate limited (429)")
    if r.status_code >= 400:
        raise ConnectorError(f"{url}: HTTP {r.status_code} {r.text[:200]}")
    return r


def upsert_records(db: Session, rows: list[dict]) -> int:
    """Insert or update DataRecords keyed by (dataset, indicator, entity, item, period)."""
    n = 0
    for row in rows:
        key = dict(dataset=row["dataset"], indicator=row["indicator"], entity=row["entity"],
                   item=row.get("item", ""), period=str(row["period"]))
        rec = db.scalar(select(DataRecord).filter_by(**key))
        if rec is None:
            rec = DataRecord(**key)
            db.add(rec)
        for f in ("source", "value", "unit", "quality", "source_url", "note"):
            if f in row:
                setattr(rec, f, row[f])
        rec.fetched_at = datetime.now(timezone.utc)
        n += 1
    db.commit()
    return n


def mark_status(db: Session, key: str, ok: bool, records: int = 0, message: str | None = None) -> None:
    st = db.scalar(select(DataSourceStatus).filter_by(key=key))
    if st is None:
        st = DataSourceStatus(key=key)
        db.add(st)
    now = datetime.now(timezone.utc)
    st.last_attempt = now
    if ok:
        st.last_success = now
        st.records = records
    st.message = message
    db.commit()


def series(db: Session, dataset: str, indicator: str, entity: str = "TN", item: str = "") -> list[DataRecord]:
    q = select(DataRecord).filter_by(dataset=dataset, indicator=indicator, entity=entity, item=item)
    return list(db.scalars(q.order_by(DataRecord.period)))


def point_key(lat: float, lon: float) -> str:
    return f"P{lat:.2f}_{lon:.2f}"
