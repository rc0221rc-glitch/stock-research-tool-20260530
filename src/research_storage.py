from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


LOCAL_EVENT_LOG = Path("downloads") / "research_access_logs.jsonl"


def is_supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def create_research_job(user_id: str, target: str, quarter_count: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    job = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "target": target,
        "quarter_count": quarter_count,
        "status": "draft",
        "payload": payload or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if is_supabase_configured():
        _supabase_insert("research_jobs", job)
    _append_local_event("research_jobs", job)
    return job


def store_report_metadata(job_id: str, user_id: str, report_type: str, path: str, draft: Any) -> dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "job_id": job_id,
        "user_id": user_id,
        "report_type": report_type,
        "path": path,
        "visibility": "authorized",
        "payload": _safe_payload(draft),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if is_supabase_configured():
        _supabase_insert("research_reports", record)
    _append_local_event("research_reports", record)
    return record


def log_research_event(user_id: str, event_type: str, report_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "event_type": event_type,
        "report_id": report_id,
        "metadata": metadata or {},
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if is_supabase_configured():
        _supabase_insert("research_access_logs", event)
    _append_local_event("research_access_logs", event)
    return event


def suggested_supabase_schema() -> str:
    return """
create table if not exists research_jobs (
  id uuid primary key,
  user_id text not null,
  target text not null,
  quarter_count int not null,
  status text not null,
  payload jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists research_reports (
  id uuid primary key,
  job_id uuid references research_jobs(id),
  user_id text not null,
  report_type text not null,
  path text not null,
  visibility text not null default 'authorized',
  payload jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists research_report_permissions (
  id uuid primary key default gen_random_uuid(),
  report_id uuid references research_reports(id),
  user_id text not null,
  role text not null default 'viewer',
  created_at timestamptz not null default now()
);

create table if not exists research_access_logs (
  id uuid primary key,
  user_id text not null,
  event_type text not null,
  report_id uuid,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);
""".strip()


def _supabase_insert(table: str, record: dict[str, Any]) -> None:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    response = requests.post(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        data=json.dumps(record, ensure_ascii=False),
        timeout=10,
    )
    response.raise_for_status()


def _safe_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


def _append_local_event(table: str, record: dict[str, Any]) -> None:
    LOCAL_EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = {"table": table, "record": record}
    with LOCAL_EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
