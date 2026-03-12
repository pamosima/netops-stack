"""
Copyright (c) 2026 Cisco and/or its affiliates.

This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

               https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.

---
ClickHouse tools for syslog and log queries. Read-only.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx

CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _esc(s: Optional[str]) -> str:
    """Escape single quotes for SQL LIKE/literal."""
    return (s or "").replace("'", "''")


def _execute_query(sql: str) -> Dict[str, Any]:
    try:
        params = {"default_format": "JSONEachRow"}
        if CLICKHOUSE_USER:
            params["user"] = CLICKHOUSE_USER
        if CLICKHOUSE_PASSWORD:
            params["password"] = CLICKHOUSE_PASSWORD
        if CLICKHOUSE_DATABASE:
            params["database"] = CLICKHOUSE_DATABASE
        with httpx.Client(timeout=30.0) as client:
            response = client.post(CLICKHOUSE_URL, params=params, content=sql)
            response.raise_for_status()
            lines = response.text.strip().split("\n")
            rows = [json.loads(line) for line in lines if line]
            return {"success": True, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _validate_select(sql: str) -> Optional[str]:
    if FORBIDDEN_KEYWORDS.search(sql):
        return "Only SELECT queries are allowed."
    if not sql.strip().upper().startswith("SELECT"):
        return "Query must be a SELECT statement."
    return None


def _format_syslog_rows(rows: List[Dict]) -> str:
    if not rows:
        return "No syslog messages found"
    lines = [f"Found {len(rows)} messages:\n"]
    for row in rows:
        ts = row.get("timestamp", "")
        host = row.get("host", "unknown")
        severity = row.get("severity", "")
        message = (row.get("message", ""))[:200]
        lines.append(f"[{ts}] {host} {severity}: {message}")
    return "\n".join(lines)


def query_syslog(
    host: Optional[str] = None,
    since_minutes: int = 15,
    severity_filter: Optional[str] = None,
    message_contains: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Query syslog messages from ClickHouse with filters."""
    limit = min(max(1, limit), 1000)
    since_minutes = max(1, since_minutes)
    conditions = [f"timestamp >= now() - INTERVAL {since_minutes} MINUTE"]
    if host:
        conditions.append(f"host ILIKE '%{_esc(host)}%'")
    if severity_filter:
        conditions.append(f"lower(severity) = lower('{_esc(severity_filter)}')")
    if message_contains:
        conditions.append(f"message ILIKE '%{_esc(message_contains)}%'")
    where = " AND ".join(conditions)
    sql = f"SELECT timestamp, host, facility, severity, program, message FROM {CLICKHOUSE_DATABASE}.syslog WHERE {where} ORDER BY timestamp DESC LIMIT {limit}"
    result = _execute_query(sql)
    if not result["success"]:
        return result
    return {
        "success": True,
        "count": result["count"],
        "rows": result["rows"],
        "formatted": _format_syslog_rows(result["rows"]),
    }


def query_clickhouse(sql: str) -> Dict[str, Any]:
    """Execute a custom SELECT query against ClickHouse (read-only)."""
    err = _validate_select(sql)
    if err:
        return {"success": False, "error": err}
    result = _execute_query(sql)
    if not result["success"]:
        return result
    return {
        "success": True,
        "count": result["count"],
        "rows": result["rows"][:500],
        "truncated": result["count"] > 500,
    }


def get_syslog_hosts(since_minutes: int = 60) -> Dict[str, Any]:
    """List hosts that have sent syslog messages."""
    since_minutes = max(1, since_minutes)
    sql = f"SELECT host, count() as message_count, max(timestamp) as last_seen FROM {CLICKHOUSE_DATABASE}.syslog WHERE timestamp >= now() - INTERVAL {since_minutes} MINUTE GROUP BY host ORDER BY message_count DESC LIMIT 100"
    result = _execute_query(sql)
    if not result["success"]:
        return result
    return {"success": True, "since_minutes": since_minutes, "host_count": result["count"], "hosts": result["rows"]}


def get_severity_stats(host: Optional[str] = None, since_minutes: int = 60) -> Dict[str, Any]:
    """Get syslog message counts by severity."""
    since_minutes = max(1, since_minutes)
    conditions = [f"timestamp >= now() - INTERVAL {since_minutes} MINUTE"]
    if host:
        conditions.append(f"host ILIKE '%{_esc(host)}%'")
    where = " AND ".join(conditions)
    sql = f"SELECT severity, count() as count FROM {CLICKHOUSE_DATABASE}.syslog WHERE {where} GROUP BY severity ORDER BY count DESC"
    result = _execute_query(sql)
    if not result["success"]:
        return result
    total = sum(r.get("count", 0) for r in result["rows"])
    return {"success": True, "host": host, "since_minutes": since_minutes, "total_messages": total, "by_severity": result["rows"]}


def get_recent_errors(host: Optional[str] = None, since_minutes: int = 30, limit: int = 50) -> Dict[str, Any]:
    """Get recent error and critical syslog messages."""
    since_minutes = max(1, since_minutes)
    limit = min(max(1, limit), 500)
    conditions = [
        f"timestamp >= now() - INTERVAL {since_minutes} MINUTE",
        "lower(severity) IN ('error', 'err', 'critical', 'crit', 'alert', 'emerg')",
    ]
    if host:
        conditions.append(f"host ILIKE '%{_esc(host)}%'")
    where = " AND ".join(conditions)
    sql = f"SELECT timestamp, host, severity, program, message FROM {CLICKHOUSE_DATABASE}.syslog WHERE {where} ORDER BY timestamp DESC LIMIT {limit}"
    result = _execute_query(sql)
    if not result["success"]:
        return result
    return {"success": True, "count": result["count"], "rows": result["rows"], "formatted": _format_syslog_rows(result["rows"])}


CLICKHOUSE_TOOLS = [
    (query_syslog, "query_syslog"),
    (query_clickhouse, "query_clickhouse"),
    (get_syslog_hosts, "get_syslog_hosts"),
    (get_severity_stats, "get_severity_stats"),
    (get_recent_errors, "get_recent_errors"),
]
