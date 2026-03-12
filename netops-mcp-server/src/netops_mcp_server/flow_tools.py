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
AI flow tools: run multi-source flows and return a combined result.
"""
from __future__ import annotations

import difflib
import re
import time
from typing import Any, Dict, Optional

from . import clickhouse_tools, gitlab_tools, ios_xe_tools, netbox_tools, prometheus_tools

# Strip ANSI escape sequences so log parsing works when artifact contains terminal colors
_ANSI_RE = re.compile(r"\x1b\[[\d;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text) if text else ""


def run_troubleshoot_flow(
    device: str,
    since_minutes: int = 15,
    include_metrics: bool = True,
    include_syslog: bool = True,
    include_config_check: bool = True,
    run_compare_pipeline: bool = True,
) -> Dict[str, Any]:
    """
    Run the troubleshooting flow for a device: NetBox (device lookup), Prometheus (suggested queries + up check),
    ClickHouse (recent syslog), and config check (drift vs baseline). When include_config_check and run_compare_pipeline
    are True, triggers the GitLab collect+compare pipeline and waits for it so the diff comes from the pipeline.

    IMPORTANT for config_diff_live: The diff can have multiple hunks (first hunk often NVRAM timestamp; later hunks
    may be vlan/ACL/interface changes). You MUST report every change in the diff, not only the first hunk. Do not
    say "only timestamp" or "cosmetic only" unless the entire diff contains no other + or - lines.

    Args:
        device: Hostname, IP, or partial name of the device (used for NetBox search, Prometheus instance, syslog host).
            For a site (e.g. "site-1"), use flow_run_troubleshoot_site_flow(site) instead so all devices at that site are checked.
        since_minutes: Time window for syslog (default 15).
        include_metrics: If True, call Prometheus suggest_queries and up query.
        include_syslog: If True, query ClickHouse syslog for this host.
        include_config_check: If True (default), run config compare and diff (pipeline or live).
        run_compare_pipeline: If True (default), trigger the collect+compare pipeline and wait for it; diff comes from
            pipeline. Set False to use the latest existing pipeline only (faster but may be stale).

    Returns:
        Combined summary with netbox_hits, prometheus_suggestions, prometheus_up, syslog_count, syslog_preview,
        config_compare, config_diff_live, config_diff_source ("pipeline", "repository", or "live"), pipeline_triggered,
        report_instruction (tell the user to include the full diff in the report when present), and summary.
        When config_diff_live contains a diff (lines with + or -), you MUST include that full text in your
        Configuration Status section; do not summarize it away so the user sees exactly what changed.
    """
    out: Dict[str, Any] = {
        "device": device,
        "since_minutes": since_minutes,
        "netbox_hits": [],
        "prometheus_suggestions": [],
        "prometheus_up": None,
        "syslog_count": 0,
        "syslog_preview": "",
        "config_compare": None,
        "config_diff_live": None,
        "config_diff_source": None,
        "pipeline_triggered": None,
        "report_instruction": None,
        "summary": "",
        "errors": [],
    }

    # 1) NetBox: search devices by name/IP
    try:
        nb = netbox_tools.search_objects("dcim/devices", device, limit=10)
        if nb.get("success") and nb.get("data"):
            data = nb["data"]
            out["netbox_hits"] = [
                {"id": d.get("id"), "name": d.get("name"), "primary_ip": (d.get("primary_ip") or {}).get("address") if isinstance(d.get("primary_ip"), dict) else d.get("primary_ip")}
                for d in (data if isinstance(data, list) else [data])
            ]
    except Exception as e:
        out["errors"].append(f"netbox: {e}")

    # 2) Prometheus: use primary IP from NetBox when available (gNMIc uses name=IP, source=IP)
    if include_metrics:
        try:
            prom_device = device
            if out["netbox_hits"]:
                primary_ip = (out["netbox_hits"][0].get("primary_ip") or "").split("/")[0]
                if primary_ip:
                    prom_device = primary_ip
            sug = prometheus_tools.suggest_queries(prom_device)
            if sug.get("success") and sug.get("suggestions"):
                out["prometheus_suggestions"] = [s.get("name") for s in sug["suggestions"][:5]]
            up = prometheus_tools.query_prometheus(f'gnmic_target_up{{name="{prom_device}"}}')
            if up.get("success") and up.get("raw", {}).get("data", {}).get("result"):
                out["prometheus_up"] = up.get("formatted") or str(up.get("raw"))
            else:
                out["prometheus_up"] = "No matching target or query failed."
        except Exception as e:
            out["errors"].append(f"prometheus: {e}")

    # 3) ClickHouse: recent syslog for host (use primary IP when available; syslog is stored by source IP)
    if include_syslog:
        try:
            syslog_host = device
            if out["netbox_hits"]:
                primary_ip = (out["netbox_hits"][0].get("primary_ip") or "").split("/")[0]
                if primary_ip:
                    syslog_host = primary_ip
            ch = clickhouse_tools.query_syslog(host=syslog_host, since_minutes=since_minutes, limit=50)
            if ch.get("success"):
                out["syslog_count"] = ch.get("count", 0)
                out["syslog_preview"] = ch.get("formatted", "")[:2000]
        except Exception as e:
            out["errors"].append(f"clickhouse: {e}")

    # 4) Config check: optionally trigger collect+compare pipeline, then use pipeline diff or live diff
    if not include_config_check:
        out["config_compare"] = "Skipped (include_config_check=False)."
        out["config_diff_live"] = "Skipped."
    else:
        compare_job_id = None
        collect_job_id = None
        pipeline_diff_content: Optional[str] = None
        try:
            pipeline_id_to_use: Optional[int] = None
            if run_compare_pipeline:
                # Compare-only: COMPARE_ONLY + COLLECT_PIPELINE=false + PIPELINE_TYPE=compare so CI runs only compare.
                # Baseline = repo (ansible/configs/baseline/*.txt); drift is detected and .diff is produced.
                tr = gitlab_tools.trigger_gitlab_pipeline(
                    ref="main",
                    variables={
                        "COMPARE_ONLY": "true",
                        "COLLECT_PIPELINE": "false",
                        "PIPELINE_TYPE": "compare",
                    },
                )
                if not tr.get("success"):
                    err = tr.get("error") or "unknown"
                    out["pipeline_triggered"] = {"triggered": False, "error": err}
                    if "400" in str(err) or "workflow" in str(err).lower() or "did not run" in str(err).lower():
                        out["config_compare"] = (
                            f"GitLab rejected the pipeline trigger: {err}. "
                            "This usually means workflow rules produced no jobs (e.g. trigger variables were dropped or not allowed). "
                            "Check: (1) GITLAB_TOKEN is set and GITLAB_ALLOWED_VARIABLES includes COMPARE_ONLY, PIPELINE_TYPE, COLLECT_PIPELINE (or omit to use defaults); "
                            "(2) .gitlab-ci.yml has the compare fallback rules. "
                            "Do not suggest running the collect pipeline—baseline may already exist in ansible/configs/baseline/."
                        )
                    else:
                        out["config_compare"] = f"Failed to trigger compare pipeline: {err}."
                else:
                    pid = tr.get("pipeline_id")
                    web_url = tr.get("web_url")
                    out["pipeline_triggered"] = {"pipeline_id": pid, "web_url": web_url, "status": "pending"}
                    if pid:
                        poll_interval = 10
                        timeout = 180
                        elapsed = 0
                        while elapsed < timeout:
                            st = gitlab_tools.get_gitlab_pipeline_status(pipeline_id=pid)
                            if not st.get("success"):
                                out["pipeline_triggered"]["status"] = "error"
                                break
                            status = st.get("status")
                            if status == "success":
                                pipeline_id_to_use = pid
                                out["pipeline_triggered"]["status"] = "success"
                                break
                            if status in ("failed", "canceled"):
                                out["pipeline_triggered"]["status"] = status
                                break
                            time.sleep(poll_interval)
                            elapsed += poll_interval
                        if elapsed >= timeout:
                            out["pipeline_triggered"]["status"] = "timeout"
                            out["pipeline_triggered"]["message"] = "Pipeline did not finish within 3 min; using latest pipeline for diff."
                            pl = gitlab_tools.list_gitlab_pipelines(per_page=5)
                            if pl.get("success") and pl.get("pipelines"):
                                for p in pl["pipelines"]:
                                    if p.get("status") == "success":
                                        st = gitlab_tools.get_gitlab_pipeline_status(pipeline_id=p["id"])
                                        if st.get("success") and st.get("jobs"):
                                            pipeline_id_to_use = p["id"]
                                            break

            if pipeline_id_to_use is None and not run_compare_pipeline:
                pl = gitlab_tools.list_gitlab_pipelines(per_page=10)
                if pl.get("success") and pl.get("pipelines"):
                    for p in pl["pipelines"]:
                        if p.get("status") != "success":
                            continue
                        st = gitlab_tools.get_gitlab_pipeline_status(pipeline_id=p["id"])
                        if st.get("success") and st.get("jobs"):
                            pipeline_id_to_use = p["id"]
                            break

            if pipeline_id_to_use:
                st = gitlab_tools.get_gitlab_pipeline_status(pipeline_id=pipeline_id_to_use)
                if st.get("success") and st.get("jobs"):
                    for j in st["jobs"]:
                        if j.get("name") == "compare_configs" and j.get("status") == "success":
                            compare_job_id = j.get("id")
                        if j.get("name") == "collect_configs" and j.get("status") == "success":
                            collect_job_id = j.get("id")
            elif run_compare_pipeline and out.get("pipeline_triggered"):
                if out.get("config_compare") is None:
                    out["config_compare"] = "Compare pipeline ran but did not succeed; check GitLab."
            elif out.get("config_compare") is None:
                out["config_compare"] = "No pipelines or GitLab unavailable."

            if compare_job_id:
                art = gitlab_tools.get_gitlab_job_artifact(job_id=compare_job_id, artifact_path="ansible/compare_output.log")
                if not (art.get("success") and art.get("content")):
                    art = gitlab_tools.get_gitlab_job_artifact(job_id=compare_job_id, artifact_path="compare_output.log")
                if not art.get("success") or not art.get("content"):
                    out["config_compare"] = out.get("config_compare") or "Could not fetch compare_output.log artifact."
                else:
                    content = _strip_ansi(art.get("content", ""))
                    device_escaped = re.escape(device)
                    # Drift: check first so we don't falsely match another host's "No changes."
                    match_diff = re.search(
                        rf"Config differs from baseline \({device_escaped}\)",
                        content,
                    )
                    # No-drift: require device-specific "No changes." (ok: [device] ... "No changes.")
                    match_ok = re.search(
                        rf"ok: \[{device_escaped}\][\s\S]*?\"No changes\.\"",
                        content,
                    )
                    # Task "Config matches baseline (device)" then ok: [device] then "No changes." (same device)
                    match_match_task = re.search(
                        rf"Config matches baseline \({device_escaped}\)[\s\S]*?ok: \[{device_escaped}\][\s\S]*?\"No changes\.\"",
                        content,
                    )
                    if match_diff:
                        out["config_compare"] = "Drift detected (running config differs from baseline). See drift flow or compare_output.log."
                    elif match_ok or match_match_task:
                        out["config_compare"] = "No changes (running config matches collected baseline)."
                        out["config_diff_live"] = "No diff (config matches baseline)."
                    else:
                        out["config_compare"] = f"Compare ran; device {device} not found in output or format unknown."
                # Try device name first; inventory may use primary_ip as hostname so try that next.
                # CI artifact paths: compare_output.log; .diff files under configs/baseline/ (or ansible/configs/baseline)
                primary_ip = None
                if out["netbox_hits"]:
                    primary_ip = (out["netbox_hits"][0].get("primary_ip") or "").split("/")[0] or None
                for path_prefix in ("configs/baseline", "ansible/configs/baseline"):
                    diff_art = gitlab_tools.get_gitlab_job_artifact(
                        job_id=compare_job_id, artifact_path=f"{path_prefix}/{device}.diff"
                    )
                    if diff_art.get("success") and diff_art.get("content"):
                        break
                    if primary_ip and primary_ip != device:
                        diff_art = gitlab_tools.get_gitlab_job_artifact(
                            job_id=compare_job_id, artifact_path=f"{path_prefix}/{primary_ip}.diff"
                        )
                        if diff_art.get("success") and diff_art.get("content"):
                            break
                pipeline_diff_content = diff_art.get("content") if diff_art.get("success") else None
                # Fallback: if compare job had no .diff (e.g. wrong pipeline ran), use committed diff from repo
                if not (pipeline_diff_content and pipeline_diff_content.strip()):
                    for diff_device in [device, primary_ip] if primary_ip else [device]:
                        if not diff_device:
                            continue
                        repo_diff = gitlab_tools.get_gitlab_repository_file(
                            file_path=f"ansible/configs/baseline/{diff_device}.diff", ref="main"
                        )
                        if repo_diff.get("success") and repo_diff.get("content", "").strip():
                            pipeline_diff_content = repo_diff.get("content", "").strip()
                            out["config_diff_source"] = "repository"
                            break
        except Exception as e:
            out["errors"].append(f"config_compare: {e}")
            out["config_compare"] = out.get("config_compare") or f"Error: {e}"

        # Live diff: prefer pipeline diff (compare job artifact or repo ansible/configs/baseline/*.diff); else running vs baseline via IOS-XE
        # Skip when we already determined no drift from compare_output.log (avoids "No collect_configs artifact" message)
        try:
            if out.get("config_compare") == "No changes (running config matches collected baseline).":
                pass  # config_diff_live already set above
            elif pipeline_diff_content and pipeline_diff_content.strip():
                if out.get("config_diff_source") != "repository":
                    out["config_diff_source"] = "pipeline"
                source_label = "repository (committed)" if out.get("config_diff_source") == "repository" else "GitLab compare pipeline"
                instruction = (
                    "INSTRUCTION: List every change (each hunk): timestamp, vlans, ACLs, interfaces, etc. "
                    "Do NOT say 'only timestamp' unless the diff has no other + or - lines."
                )
                out["config_diff_live"] = f"Diff from {source_label} (full). {instruction}\n\n{pipeline_diff_content.strip()}"
            else:
                out["config_diff_source"] = "live"
                host = device
                if out["netbox_hits"]:
                    primary_ip = (out["netbox_hits"][0].get("primary_ip") or "").split("/")[0]
                    if primary_ip:
                        host = primary_ip
                baseline_content = None
                if collect_job_id:
                    for path_prefix in ("ansible/configs/baseline", "configs/baseline"):
                        baseline_art = gitlab_tools.get_gitlab_job_artifact(
                            job_id=collect_job_id, artifact_path=f"{path_prefix}/{device}.txt"
                        )
                        if baseline_art.get("success") and baseline_art.get("content"):
                            baseline_content = (baseline_art.get("content") or "").strip()
                            break
                        if host != device:
                            baseline_art = gitlab_tools.get_gitlab_job_artifact(
                                job_id=collect_job_id, artifact_path=f"{path_prefix}/{host}.txt"
                            )
                            if baseline_art.get("success") and baseline_art.get("content"):
                                baseline_content = (baseline_art.get("content") or "").strip()
                                break
                    if baseline_content is None:
                        pass  # will use "Baseline file ... not in artifact" below
                if baseline_content is not None:
                    running = ios_xe_tools.show_command("show running-config", host)
                    if running.startswith("Error:"):
                        out["config_diff_live"] = running
                    else:
                        running_lines = running.strip().splitlines()
                        baseline_lines = baseline_content.splitlines()
                        diff = list(difflib.unified_diff(baseline_lines, running_lines, lineterm="", fromfile="baseline", tofile="running"))
                        if not diff:
                            out["config_diff_live"] = "Match (running config matches last collected baseline)."
                        else:
                            diff_count = sum(1 for line in diff if line and line[0] in "+-")
                            hunk_count = sum(1 for line in diff if line.startswith("@@"))
                            max_diff_lines = 120
                            diff_preview = "\n".join(diff[:max_diff_lines])
                            if len(diff) > max_diff_lines:
                                diff_preview += f"\n... ({len(diff) - max_diff_lines} more lines)"
                            instruction = (
                                "INSTRUCTION: List every change (each hunk): timestamp, vlans, ACLs, interfaces, etc. "
                                "Do NOT say 'only timestamp' unless the diff has no other + or - lines."
                            )
                            out["config_diff_live"] = f"Diff (live, {diff_count} added/removed lines, {hunk_count} hunk(s)). {instruction}\n\n{diff_preview}"
                else:
                    if not collect_job_id:
                        out["config_diff_live"] = "No collect_configs artifact; run pipeline to collect baseline first."
                    else:
                        out["config_diff_live"] = f"Baseline file ansible/configs/baseline/{device}.txt not in artifact."
        except Exception as e:
            out["errors"].append(f"config_diff_live: {e}")
            out["config_diff_live"] = f"Error: {e}"

    # Summary: lead with diff source and pipeline so it's obvious which path was used
    parts = [f"Device: {device}"]
    if out.get("config_diff_source"):
        parts.append(
            f"Config diff source: {out['config_diff_source']} "
            "(pipeline = compare job artifact; repository = committed ansible/configs/baseline/*.diff; live = device SSH)."
        )
    if out.get("pipeline_triggered"):
        pt = out["pipeline_triggered"]
        if pt.get("triggered") is False:
            parts.append(f"Pipeline: not triggered ({pt.get('error', 'unknown')}).")
        else:
            status = pt.get("status", "pending")
            parts.append(f"Pipeline: #{pt.get('pipeline_id')} status={status}. {pt.get('message', '')}")
    if out["netbox_hits"]:
        parts.append(f"NetBox: {len(out['netbox_hits'])} device(s) found.")
    if out["prometheus_up"] is not None:
        parts.append("Prometheus: up check and suggestions included.")
    if include_syslog:
        parts.append(f"Syslog: {out['syslog_count']} message(s) in last {since_minutes} min.")
    if out["config_compare"] is not None:
        parts.append(f"Config: {out['config_compare']}")
    if out.get("config_diff_live"):
        parts.append(f"Diff: {out['config_diff_live'].split(chr(10))[0]}")
    if out["errors"]:
        parts.append("Errors: " + "; ".join(out["errors"]))
    out["summary"] = " ".join(parts)

    # Tell the model to include the full diff in the user report when we have one (do not summarize away)
    diff_text = (out.get("config_diff_live") or "")
    if diff_text.strip() and ("\n-" in diff_text or "\n+" in diff_text or diff_text.strip().startswith("-") or diff_text.strip().startswith("+")):
        out["report_instruction"] = (
            "You MUST include the full content of 'config_diff_live' in your Configuration Status section, "
            "in a code block or quoted block, so the user sees exactly what changed (every line). "
            "Do not summarize or replace it with 'drift detected' or 'matches baseline' only."
        )

    return out


def run_rollback_flow(
    target_host: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Trigger the rollback pipeline (dry-run only). Runs rollback_verify (--check); actual
    rollback must be done manually in GitLab (play rollback_apply job).

    Args:
        target_host: If set, pass TARGET_HOST to the pipeline to limit to this device (e.g. sw11-1).

    Returns:
        pipeline_id, web_url, variables_sent, jobs_created, summary.
    """
    out: Dict[str, Any] = {
        "pipeline_id": None,
        "web_url": None,
        "variables_sent": None,
        "jobs_created": [],
        "summary": "",
        "errors": [],
    }
    try:
        variables: Dict[str, str] = {"ROLLBACK_PIPELINE": "true", "PIPELINE_TYPE": "rollback"}
        if target_host:
            variables["TARGET_HOST"] = target_host
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            err = tr.get("error") or "Trigger failed"
            out["errors"].append(err)
            if "400" in str(err) or "workflow" in str(err).lower() or "did not run" in str(err).lower():
                out["summary"] = (
                    f"Rollback pipeline trigger failed: {err}. "
                    "Variables (ROLLBACK_PIPELINE, PIPELINE_TYPE, TARGET_HOST) likely did not reach GitLab. "
                    "Check: (1) GITLAB_TOKEN is set; (2) MCP .env GITLAB_ALLOWED_VARIABLES includes ROLLBACK_PIPELINE, PIPELINE_TYPE, TARGET_HOST (or omit to use defaults); "
                    "(3) .gitlab-ci.yml has rollback rules (PIPELINE_TYPE=rollback)."
                )
            else:
                out["summary"] = f"Rollback pipeline trigger failed: {err}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["variables_sent"] = variables
        # Check which jobs were created so we can confirm it's the rollback pipeline
        time.sleep(3)
        st = gitlab_tools.get_gitlab_pipeline_status(pipeline_id=out["pipeline_id"])
        if st.get("success") and st.get("jobs"):
            out["jobs_created"] = [j.get("name") for j in st["jobs"]]
            if "rollback_verify" in out["jobs_created"] or "rollback_apply" in out["jobs_created"]:
                out["summary"] = f"Rollback pipeline {out['pipeline_id']} triggered. Jobs: {', '.join(out['jobs_created'])}. Review rollback_verify at {out['web_url']}; play rollback_apply manually to apply."
            else:
                out["summary"] = f"Pipeline {out['pipeline_id']} triggered but created jobs are {out['jobs_created']} (not rollback). Ensure ROLLBACK_PIPELINE=true was sent and the GitLab repo has the latest .gitlab-ci.yml so collect does not run when ROLLBACK_PIPELINE is set. Open {out['web_url']}."
        else:
            out["summary"] = f"Rollback pipeline {out['pipeline_id']} triggered. Review at {out['web_url']}; play rollback_apply manually. (Jobs list not yet available.)"
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def run_troubleshoot_site_flow(
    site: str,
    since_minutes: int = 15,
    include_metrics: bool = True,
    include_syslog: bool = True,
    include_config_check: bool = True,
    max_devices: int = 20,
) -> Dict[str, Any]:
    """
    Run the troubleshooting flow for all devices at a site. Resolves site name/slug to site_id in NetBox,
    lists devices at that site, then runs run_troubleshoot_flow for each device. Compare pipeline is
    triggered once (on first device); other devices reuse that pipeline for config diff.

    Use this when the user says e.g. "troubleshoot site-1" or "troubleshoot Building A".

    Args:
        site: Site name or slug (e.g. "site-1", "Building A"). Matched case-insensitively against NetBox site name and slug.
        since_minutes: Time window for syslog (default 15).
        include_metrics: If True, call Prometheus for each device.
        include_syslog: If True, query ClickHouse syslog per device.
        include_config_check: If True, run config compare (one pipeline for all devices).
        max_devices: Maximum number of devices to troubleshoot (default 20).

    Returns:
        site, site_id, device_count, devices (list of per-device results with name, primary_ip, summary, netbox_hits, prometheus_up, syslog_count, config_compare, config_diff_live), pipeline_triggered, errors, summary.
    """
    out: Dict[str, Any] = {
        "site": site,
        "site_id": None,
        "device_count": 0,
        "devices": [],
        "pipeline_triggered": None,
        "errors": [],
        "summary": "",
    }
    try:
        # Resolve site name/slug to site_id
        sites_resp = netbox_tools.get_sites(limit=100)
        if not sites_resp.get("success") or not sites_resp.get("data"):
            out["errors"].append("NetBox: could not list sites")
            out["summary"] = "Could not list NetBox sites."
            return out
        sites = sites_resp["data"] if isinstance(sites_resp["data"], list) else [sites_resp["data"]]
        site_lower = site.strip().lower()
        matched = None
        for s in sites:
            if not s:
                continue
            name = (s.get("name") or "").strip().lower()
            slug = (s.get("slug") or "").strip().lower()
            if name == site_lower or slug == site_lower or site_lower in name or site_lower in slug:
                matched = s
                break
        if not matched:
            out["errors"].append(f"No NetBox site matching '{site}' (tried name/slug).")
            out["summary"] = f"No site found matching '{site}'. Use a site name or slug from NetBox (e.g. netbox_get_sites)."
            return out
        site_id = matched.get("id")
        out["site_id"] = site_id

        # Get devices at site
        dev_resp = netbox_tools.get_devices(site_id=site_id, limit=max_devices)
        if not dev_resp.get("success"):
            out["errors"].append("NetBox: could not list devices at site")
            out["summary"] = "Could not list devices at site."
            return out
        dev_list = dev_resp.get("data") or []
        if not isinstance(dev_list, list):
            dev_list = [dev_list]
        if not dev_list:
            out["summary"] = f"Site '{site}' (id={site_id}) has no devices."
            return out

        out["device_count"] = len(dev_list)
        for idx, d in enumerate(dev_list):
            name = d.get("name") or d.get("id")
            if not name:
                continue
            device_name = str(name)
            run_compare = include_config_check and (idx == 0)
            one = run_troubleshoot_flow(
                device=device_name,
                since_minutes=since_minutes,
                include_metrics=include_metrics,
                include_syslog=include_syslog,
                include_config_check=include_config_check,
                run_compare_pipeline=run_compare,
            )
            if idx == 0 and one.get("pipeline_triggered"):
                out["pipeline_triggered"] = one["pipeline_triggered"]
            out["devices"].append({
                "name": device_name,
                "primary_ip": (one.get("netbox_hits") or [{}])[0].get("primary_ip") if one.get("netbox_hits") else None,
                "summary": one.get("summary", ""),
                "netbox_hits": one.get("netbox_hits", []),
                "prometheus_up": one.get("prometheus_up"),
                "syslog_count": one.get("syslog_count", 0),
                "config_compare": one.get("config_compare"),
                "config_diff_live": one.get("config_diff_live"),
            })
            out["errors"].extend(one.get("errors") or [])

        out["summary"] = f"Site '{site}' (id={site_id}): troubleshooted {len(out['devices'])} device(s). " + (
            f"Compare pipeline: {out.get('pipeline_triggered')}." if out.get("pipeline_triggered") else "No pipeline triggered."
        )
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def flow_trigger_compare_pipeline(commit_diffs: bool = False) -> Dict[str, Any]:
    """
    Trigger the compare pipeline (compare_configs only). Diffs running config vs repo baseline ansible/configs/baseline/*.txt.
    With commit_diffs=True, the job commits ansible/configs/baseline/*.diff and compare_output.log to the branch.
    Use for drift check without running troubleshoot flow, or after collect to see diffs.
    """
    variables: Dict[str, str] = {"COMPARE_ONLY": "true", "PIPELINE_TYPE": "compare"}
    if commit_diffs:
        variables["COMMIT_DIFFS"] = "true"
    out: Dict[str, Any] = {"pipeline_id": None, "web_url": None, "variables_sent": variables, "summary": "", "errors": []}
    try:
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            out["errors"].append(tr.get("error", "Trigger failed"))
            out["summary"] = f"Compare pipeline trigger failed: {tr.get('error')}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["summary"] = f"Compare pipeline {out['pipeline_id']} triggered (compare_configs only). See {out['web_url']}. With commit_diffs=True, job pushes *.diff and log to git."
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def flow_trigger_collect_pipeline(commit_collected: bool = False) -> Dict[str, Any]:
    """
    Trigger the collect pipeline (collect_configs only). Fetches running configs to ansible/configs/baseline/*.txt.
    With commit_collected=True, the job creates branch ci/collected-baseline-<pipeline_id>, commits the files,
    pushes, and creates a merge request to main. Requires GITLAB_PUSH_TOKEN (write_repository + api) in GitLab.
    """
    variables: Dict[str, str] = {"PIPELINE_TYPE": "collect"}
    if commit_collected:
        variables["COMMIT_COLLECTED"] = "true"
    out: Dict[str, Any] = {"pipeline_id": None, "web_url": None, "variables_sent": variables, "summary": "", "errors": []}
    try:
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            out["errors"].append(tr.get("error", "Trigger failed"))
            out["summary"] = f"Collect pipeline trigger failed: {tr.get('error')}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["summary"] = f"Collect pipeline {out['pipeline_id']} triggered (collect_configs only). With commit_collected=True, job creates branch and MR to main. See {out['web_url']}."
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def flow_trigger_apply_pipeline(target_host: Optional[str] = None) -> Dict[str, Any]:
    """
    Trigger the apply pipeline (apply_dry-run, then manual apply_config).
    Sets DRY_RUN_PIPELINE=true, PIPELINE_TYPE=apply, and optionally TARGET_HOST. Put desired config in ansible/configs/desired/<host>.txt first (or use flow_run_apply_flow to upload + trigger).
    """
    out: Dict[str, Any] = {"pipeline_id": None, "web_url": None, "variables_sent": None, "summary": "", "errors": []}
    try:
        variables: Dict[str, str] = {"DRY_RUN_PIPELINE": "true", "PIPELINE_TYPE": "apply"}
        if target_host:
            variables["TARGET_HOST"] = target_host
        out["variables_sent"] = variables
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            out["errors"].append(tr.get("error", "Trigger failed"))
            out["summary"] = f"Apply pipeline trigger failed: {tr.get('error')}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["summary"] = f"Apply pipeline {out['pipeline_id']} triggered (apply_dry-run → manual apply_config). See {out['web_url']}. Set TARGET_HOST in variables_sent if limited."
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def flow_trigger_rollback_pipeline(target_host: Optional[str] = None) -> Dict[str, Any]:
    """
    Trigger the rollback pipeline (rollback_verify, then manual rollback_apply).
    Sets ROLLBACK_PIPELINE=true, PIPELINE_TYPE=rollback, and optionally TARGET_HOST so only rollback jobs run (no collect).
    """
    out: Dict[str, Any] = {"pipeline_id": None, "web_url": None, "variables_sent": None, "summary": "", "errors": []}
    try:
        variables: Dict[str, str] = {"ROLLBACK_PIPELINE": "true", "PIPELINE_TYPE": "rollback"}
        if target_host:
            variables["TARGET_HOST"] = target_host
        out["variables_sent"] = variables
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            out["errors"].append(tr.get("error", "Trigger failed"))
            out["summary"] = f"Rollback pipeline trigger failed: {tr.get('error')}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["summary"] = f"Rollback pipeline {out['pipeline_id']} triggered (rollback_verify → manual rollback_apply). See {out['web_url']}."
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out


def run_apply_flow(
    target_host: str,
    config_content: str,
) -> Dict[str, Any]:
    """
    Configuration change flow: upload desired config and trigger the apply dry-run pipeline.
    Use when the user wants to configure something on a device (e.g. add VLAN, change ACL).
    Updates ansible/configs/desired/<target_host>.txt in the repo (creates file if missing) and triggers
    pipeline with DRY_RUN_PIPELINE and TARGET_HOST. Actual apply must be done manually in GitLab (play apply_config).

    Args:
        target_host: Hostname of the device (e.g. sw11-1). Used for file path and TARGET_HOST.
        config_content: Full desired IOS-XE config block to upload to ansible/configs/desired/<target_host>.txt.

    Returns:
        file_updated (bool), pipeline_id, web_url, summary.
    """
    out: Dict[str, Any] = {
        "file_updated": False,
        "pipeline_id": None,
        "web_url": None,
        "summary": "",
        "errors": [],
    }
    try:
        file_path = f"ansible/configs/desired/{target_host}.txt"
        up = gitlab_tools.update_gitlab_repository_file(
            file_path=file_path,
            content=config_content,
            branch="main",
            commit_message=f"Apply config flow: update desired config for {target_host}",
        )
        if not up.get("success"):
            out["errors"].append(up.get("error", "File update failed"))
            out["summary"] = f"Upload failed: {up.get('error')}. Check path allowlist and GitLab token."
            return out
        out["file_updated"] = True

        variables: Dict[str, str] = {"DRY_RUN_PIPELINE": "true", "TARGET_HOST": target_host}
        tr = gitlab_tools.trigger_gitlab_pipeline(ref="main", variables=variables)
        if not tr.get("success"):
            out["errors"].append(tr.get("error", "Trigger failed"))
            out["summary"] = f"Config uploaded to {file_path}; pipeline trigger failed: {tr.get('error')}"
            return out
        out["pipeline_id"] = tr.get("pipeline_id")
        out["web_url"] = tr.get("web_url")
        out["summary"] = f"Config uploaded to {file_path}. Pipeline {out['pipeline_id']} triggered (dry-run only). Review at {out['web_url']}; apply must be done manually in GitLab (play apply_config)."
    except Exception as e:
        out["errors"].append(str(e))
        out["summary"] = f"Error: {e}"
    return out
