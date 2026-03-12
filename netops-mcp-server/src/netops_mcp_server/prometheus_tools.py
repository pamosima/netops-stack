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
Prometheus tools for netops-stack metrics. Read-only PromQL.
"""
import os
import re
import time as time_module
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
DANGEROUS_PATTERNS = re.compile(
    r"\b(delete|drop|truncate|insert|update|alter)\b", re.IGNORECASE
)


def _make_request(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{PROMETHEUS_URL}/api/v1/{endpoint}"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _validate_query(query: str) -> Optional[str]:
    if DANGEROUS_PATTERNS.search(query):
        return "Query contains forbidden keywords."
    return None


def _format_instant_result(data: Dict[str, Any]) -> str:
    if data.get("status") != "success":
        return f"Error: {data.get('error', 'Unknown error')}"
    result = data.get("data", {})
    results = result.get("result", [])
    if not results:
        return "No data returned"
    lines = [f"Count: {len(results)}", ""]
    for r in results[:20]:
        metric = r.get("metric", {})
        value = r.get("value", [])
        labels = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        if len(value) >= 2:
            ts_str = datetime.fromtimestamp(value[0]).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"{{{labels}}} => {value[1]} @ {ts_str}")
        else:
            lines.append(f"{{{labels}}} => {value}")
    if len(results) > 20:
        lines.append(f"... and {len(results) - 20} more")
    return "\n".join(lines)


def _format_range_result(data: Dict[str, Any]) -> str:
    if data.get("status") != "success":
        return f"Error: {data.get('error', 'Unknown error')}"
    results = data.get("data", {}).get("result", [])
    if not results:
        return "No data returned"
    lines = [f"Time series count: {len(results)}", ""]
    for r in results[:10]:
        metric = r.get("metric", {})
        values = r.get("values", [])
        labels = ", ".join(f'{k}="{v}"' for k, v in metric.items())
        lines.append(f"Series: {{{labels}}}, Points: {len(values)}")
    if len(results) > 10:
        lines.append(f"... and {len(results) - 10} more series")
    return "\n".join(lines)


def query_prometheus(query: str, time: Optional[str] = None) -> Dict[str, Any]:
    """Execute an instant PromQL query against Prometheus."""
    err = _validate_query(query)
    if err:
        return {"success": False, "error": err}
    params = {"query": query}
    if time:
        params["time"] = time
    result = _make_request("query", params)
    return {
        "success": result.get("status") == "success",
        "raw": result,
        "formatted": _format_instant_result(result),
    }


def query_prometheus_range(
    query: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    step: str = "15s",
) -> Dict[str, Any]:
    """Execute a range PromQL query against Prometheus."""
    err = _validate_query(query)
    if err:
        return {"success": False, "error": err}
    now = time_module.time()
    params = {
        "query": query,
        "start": start or str(int(now - 3600)),
        "end": end or str(int(now)),
        "step": step,
    }
    result = _make_request("query_range", params)
    return {
        "success": result.get("status") == "success",
        "raw": result,
        "formatted": _format_range_result(result),
    }


def list_metric_names(filter_pattern: Optional[str] = None) -> Dict[str, Any]:
    """List available metric names in Prometheus."""
    result = _make_request("label/__name__/values", {})
    if result.get("status") != "success":
        return {"success": False, "error": result.get("error", "Failed to fetch")}
    names = result.get("data", [])
    if filter_pattern:
        try:
            pattern = re.compile(filter_pattern, re.IGNORECASE)
            names = [n for n in names if pattern.search(n)]
        except re.error as e:
            return {"success": False, "error": str(e)}
    return {"success": True, "count": len(names), "metrics": names[:100], "truncated": len(names) > 100}


def get_targets() -> Dict[str, Any]:
    """Get list of monitored targets from Prometheus."""
    result = _make_request("targets", {})
    if result.get("status") != "success":
        return {"success": False, "error": result.get("error", "Failed to fetch")}
    data = result.get("data", {})
    active = data.get("activeTargets", [])
    active_summary = [
        {
            "instance": t.get("labels", {}).get("instance", "unknown"),
            "job": t.get("labels", {}).get("job", "unknown"),
            "health": t.get("health", "unknown"),
        }
        for t in active
    ]
    return {"success": True, "active_count": len(active), "active_targets": active_summary}


def suggest_queries(device: str) -> Dict[str, Any]:
    """Suggest useful PromQL queries for a device.
    For netops-stack gNMIc/IOS-XE: use primary IP from NetBox when device is a hostname.
    Target up uses label 'name'; interface metrics use label 'source'."""
    # Escape dots if device looks like an IP for exact match
    device_re = device.replace(".", r"\.") if device.replace(".", "").isdigit() else device
    suggestions = [
        {"name": "Target up (gNMIc)", "query": f'gnmic_target_up{{name=~".*{device_re}.*"}}'},
        {"name": "Interface traffic in", "query": f'rate(interfaces_interface_state_counters_in_octets{{source=~".*{device_re}.*"}}[5m])'},
        {"name": "Interface traffic out", "query": f'rate(interfaces_interface_state_counters_out_octets{{source=~".*{device_re}.*"}}[5m])'},
        {"name": "Interface errors in", "query": f'increase(interfaces_interface_state_counters_in_errors{{source=~".*{device_re}.*"}}[1h])'},
        {"name": "Interface errors out", "query": f'increase(interfaces_interface_state_counters_out_errors{{source=~".*{device_re}.*"}}[1h])'},
    ]
    return {"success": True, "device": device, "suggestions": suggestions}


# (function, tool_name) for registration with prefix "prometheus_"
PROMETHEUS_TOOLS = [
    (query_prometheus, "query_prometheus"),
    (query_prometheus_range, "query_prometheus_range"),
    (list_metric_names, "list_metric_names"),
    (get_targets, "get_targets"),
    (suggest_queries, "suggest_queries"),
]
