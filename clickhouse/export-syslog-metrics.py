#!/usr/bin/env python3
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
ClickHouse → Prometheus: query default.syslog and expose event counts as metrics.
Scrape endpoint: :9099/metrics
"""
import os
import threading
import time
import urllib.parse
import urllib.request

from prometheus_client import REGISTRY, Gauge, start_http_server

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://netops-stack-clickstack:8123")
SCRAPE_PORT = int(os.environ.get("SCRAPE_PORT", "9099"))
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "30"))

# Single gauge: event counts in last 5m; labels host and severity (use "total" for host-only)
syslog_events_5m = Gauge(
    "clickhouse_syslog_events_last_5m",
    "Syslog events in last 5 minutes from default.syslog",
    ["host", "severity"],
)


def query_clickhouse(sql: str) -> list[tuple]:
    """Run SQL via HTTP, return list of rows (tuples)."""
    url = f"{CLICKHOUSE_URL}/?query={urllib.parse.quote(sql)}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        lines = resp.read().decode().strip().split("\n")
    if not lines:
        return []
    rows = []
    for line in lines[1:]:
        rows.append(tuple(line.split("\t")))
    return rows


def update_metrics():
    try:
        rows = query_clickhouse(
            "SELECT host, count() FROM default.syslog "
            "WHERE timestamp > now() - 300 GROUP BY host"
        )
        for host, cnt in rows:
            syslog_events_5m.labels(host=host or "unknown", severity="total").set(int(cnt))

        rows = query_clickhouse(
            "SELECT host, severity, count() FROM default.syslog "
            "WHERE timestamp > now() - 300 GROUP BY host, severity"
        )
        for host, severity, cnt in rows:
            syslog_events_5m.labels(
                host=host or "unknown", severity=severity or "unknown"
            ).set(int(cnt))
    except Exception as e:
        print(f"ClickHouse query error: {e}", flush=True)


def background_scraper():
    while True:
        update_metrics()
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    REGISTRY.register(syslog_events_5m)
    update_metrics()
    t = threading.Thread(target=background_scraper, daemon=True)
    t.start()
    start_http_server(SCRAPE_PORT)
    print(f"Serving /metrics on :{SCRAPE_PORT}", flush=True)
    t.join()
