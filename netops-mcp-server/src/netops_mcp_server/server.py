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
Combined NetOps MCP Server — single server with under 50 tools.

Domains: NetBox (DCIM/IPAM), Prometheus (metrics), ClickHouse (syslog),
GitLab (CI/CD, repo files), IOS-XE (show/config via SSH).

Tool names are prefixed: netbox_get_sites, prometheus_query_prometheus,
clickhouse_query_syslog, gitlab_trigger_gitlab_pipeline, ios_xe_show_command, etc.

Environment: load NETBOX_*, PROMETHEUS_*, CLICKHOUSE_*, GITLAB_*, IOS_XE_*
(e.g. from .env or shell). Optional: MCP_HOST, MCP_PORT (default 0.0.0.0:8010).
LOG_LEVEL=INFO (default) or DEBUG for verbose GitLab trigger logging in Docker.
"""
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

from . import clickhouse_tools, flow_resources, flow_tools, gitlab_tools, ios_xe_tools, netbox_tools, prometheus_tools

load_dotenv()

# Logging: stdout so Docker logs show trigger details (set LOG_LEVEL=DEBUG for full request/response)
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
    force=True,
)

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8010"))

mcp = FastMCP(
    name="NetOps MCP Server",
    instructions="""Combined MCP server for netops-stack: NetBox (DCIM/IPAM), Prometheus (metrics),
ClickHouse (syslog), GitLab (CI/CD, repo files), IOS-XE (show/config).

Tools are prefixed by domain:
- netbox_* : sites, devices, IPs, VLANs, search (SoT for troubleshooting/config flows)
- prometheus_* : query_prometheus, query_prometheus_range, list_metric_names, get_targets, suggest_queries
- clickhouse_* : query_syslog, query_clickhouse, get_syslog_hosts, get_severity_stats, get_recent_errors
- gitlab_* : trigger pipeline, status, job logs/artifacts, list projects/pipelines, get/update repo file
- ios_xe_* : show_command, config_command (config disabled if IOS_XE_READ_ONLY=true)
- flow_run_troubleshoot_flow : one-shot troubleshooting for a device (NetBox + Prometheus + ClickHouse + config check); use device hostname or IP
- flow_run_troubleshoot_site_flow : same for a site (e.g. "site-1"); resolves site in NetBox and runs troubleshoot for each device at that site
- flow_run_rollback_flow : trigger rollback pipeline (dry-run); rollback_verify then manual rollback_apply (optional target_host)
- flow_run_apply_flow : configuration flow — upload desired config, trigger apply dry-run (apply manual in GitLab); use when user says "configure X on device Y"
Pipeline triggers (one per pipeline; use GITLAB_TOKEN — variables sent in API request body):
- flow_trigger_compare_pipeline : compare only (drift vs repo baseline); optional commit_diffs
- flow_trigger_collect_pipeline : collect only (fetch configs → ansible/configs/baseline/*.txt); optional commit_collected → MR
- flow_trigger_apply_pipeline : apply dry-run → manual apply_config; optional target_host
- flow_trigger_rollback_pipeline : rollback_verify → manual rollback_apply; optional target_host

Resources (read for AI flows): netops://flows/troubleshoot, netops://flows/configuration (or apply_config), netops://flows/drift, netops://flows/pipelines

Configure via env: NETBOX_URL, NETBOX_TOKEN, PROMETHEUS_URL, CLICKHOUSE_URL, GITLAB_URL, GITLAB_TOKEN, IOS_XE_USERNAME, IOS_XE_PASSWORD.
"""
)

# Register all tools with domain prefix (total < 50)
for func, name in prometheus_tools.PROMETHEUS_TOOLS:
    mcp.tool(name=f"prometheus_{name}")(func)
for func, name in clickhouse_tools.CLICKHOUSE_TOOLS:
    mcp.tool(name=f"clickhouse_{name}")(func)
for func, name in gitlab_tools.GITLAB_TOOLS:
    mcp.tool(name=f"gitlab_{name}")(func)
for func, name in netbox_tools.NETBOX_TOOLS:
    mcp.tool(name=f"netbox_{name}")(func)
for func, name in ios_xe_tools.IOS_XE_TOOLS:
    if name == "config_command" and ios_xe_tools.IOS_XE_READ_ONLY:
        continue  # skip config when read-only
    mcp.tool(name=f"ios_xe_{name}")(func)

# AI flow tools (one-shot troubleshoot, rollback, apply) + pipeline triggers (one tool per pipeline)
mcp.tool(name="flow_run_troubleshoot_flow")(flow_tools.run_troubleshoot_flow)
mcp.tool(name="flow_run_troubleshoot_site_flow")(flow_tools.run_troubleshoot_site_flow)
mcp.tool(name="flow_run_rollback_flow")(flow_tools.run_rollback_flow)
mcp.tool(name="flow_run_apply_flow")(flow_tools.run_apply_flow)
mcp.tool(name="flow_trigger_compare_pipeline")(flow_tools.flow_trigger_compare_pipeline)
mcp.tool(name="flow_trigger_collect_pipeline")(flow_tools.flow_trigger_collect_pipeline)
mcp.tool(name="flow_trigger_apply_pipeline")(flow_tools.flow_trigger_apply_pipeline)
mcp.tool(name="flow_trigger_rollback_pipeline")(flow_tools.flow_trigger_rollback_pipeline)

# AI flow resources (recommended flows for the model to follow)
@mcp.resource("netops://flows/troubleshoot")
def _resource_troubleshoot() -> str:
    """Troubleshooting flow: NetBox + Prometheus + ClickHouse for a device."""
    return flow_resources.get_troubleshoot_flow()


@mcp.resource("netops://flows/apply_config")
def _resource_apply_config() -> str:
    """Apply config flow: GitLab repo file update + dry-run pipeline + manual apply."""
    return flow_resources.get_apply_config_flow()


@mcp.resource("netops://flows/configuration")
def _resource_configuration() -> str:
    """Configuration change flow: when user wants to configure something on a device (add VLAN, ACL, etc.); same as apply_config."""
    return flow_resources.get_configuration_flow()


@mcp.resource("netops://flows/drift")
def _resource_drift() -> str:
    """Drift/compare flow: collect baseline, compare, rollback or apply desired."""
    return flow_resources.get_drift_flow()


@mcp.resource("netops://flows/pipelines")
def _resource_pipelines() -> str:
    """One tool per GitLab pipeline; when to use each (trigger + optional params)."""
    return flow_resources.get_pipelines_flow()

_tool_count = (
    len(prometheus_tools.PROMETHEUS_TOOLS)
    + len(clickhouse_tools.CLICKHOUSE_TOOLS)
    + len(gitlab_tools.GITLAB_TOOLS)
    + len(netbox_tools.NETBOX_TOOLS)
    + len([t for t in ios_xe_tools.IOS_XE_TOOLS if t[1] != "config_command" or not ios_xe_tools.IOS_XE_READ_ONLY])
    + 8  # flow_run_* (4) + flow_trigger_*_pipeline (4)
)


def run() -> None:
    print(f"NetOps MCP Server — {_tool_count} tools + 5 AI flow resources (troubleshoot, configuration, apply_config, drift, pipelines)")
    print(f"Listening on http://{MCP_HOST}:{MCP_PORT}")
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    run()
