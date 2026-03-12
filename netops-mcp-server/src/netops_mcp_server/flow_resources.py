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
AI flow definitions exposed as MCP resources. Read these to follow recommended flows.
"""

FLOW_TROUBLESHOOT = """# Troubleshooting flow (NetBox + Prometheus + ClickHouse)

**Goal:** Correlate topology (NetBox), metrics (Prometheus), and logs (ClickHouse) for a device.

## Steps

1. **Identify the device (NetBox)**
   - Use `netbox_search_objects` with endpoint `dcim/devices` and query = hostname or IP.
   - Or `netbox_get_devices` and filter by name/site.
   - **Note primary IP** — Prometheus uses device IP: label **name** for target up, **source** for interface metrics (gNMIc/IOS-XE).

2. **Check metrics (Prometheus)**
   - Use **primary IP** (from NetBox) for Prometheus when device is a hostname.
   - `prometheus_suggest_queries(device)` returns PromQL for gNMIc: target up (`gnmic_target_up{name="<ip>"}`), interface traffic/errors (`...{source="<ip>"}`).
   - Run `prometheus_query_prometheus` with e.g. `gnmic_target_up{name="198.18.170.201"}` or `rate(interfaces_interface_state_counters_in_octets{source="198.18.170.201"}[5m])`.

3. **Check logs (ClickHouse)**
   - Use **primary IP** (from NetBox) for syslog when device is a hostname—syslog is stored by source IP. `clickhouse_query_syslog(host=<primary_ip or device>, since_minutes=15)`.
   - Optionally `clickhouse_get_recent_errors(host=<device>, since_minutes=30)` for errors/critical only.

4. **Check config drift (always included in one-shot)**
   - The one-shot tool **always** runs config check unless you pass **include_config_check=False**.
   - It triggers a **compare-only** pipeline (COMPARE_ONLY=true, no collect) so baseline = repo `ansible/configs/baseline/*.txt`; drift and the `.diff` come from the compare job or from the committed `ansible/configs/baseline/<device>.diff` in the repo.
   - When the tool returns **config_diff_live** with actual diff lines (+/-), you **MUST** include that full text in your Configuration Status section (e.g. in a code block) so the user sees exactly what changed. Do not summarize it away. Obey **report_instruction** if present.

5. **Summarize**
   - Combine: device/site from NetBox, target up and interface metrics from Prometheus, recent events from ClickHouse, and config drift + **full diff** (if present).
   - **Config diff:** The diff can have multiple hunks (e.g. timestamp, then vlan/ACL/interface changes). Include the **entire** config_diff_live content when present. Do not say "cosmetic only" unless the diff has no other + or - lines.
   - Suggest next steps (e.g. run show commands, or run collect/apply flow if drift detected).

## One-shot tools

- **Device:** Use **flow_run_troubleshoot_flow(device, ...)** with a device hostname or IP (e.g. sw11-1, 198.18.170.201). By default it triggers a compare-only pipeline and returns drift vs repo baseline; include **config_diff_live** in full in your report; obey **report_instruction**.
- **Site:** If the user says e.g. "troubleshoot site-1" or "troubleshoot Building A", use **flow_run_troubleshoot_site_flow(site)** instead. It resolves the site in NetBox, lists devices at that site, and runs the same troubleshoot flow for each device (compare pipeline triggered once, shared for config diffs).

**Note (server version):** The one-shot flow uses **primary IP from NetBox** for the Prometheus up query and for IOS-XE when comparing running config to the backup. Rebuild and restart the MCP server after code changes; then **flow_run_troubleshoot_flow(device="sw11-1")** gives the full picture (NetBox + Prometheus up + syslog + config compare + live diff) in one call.
"""

FLOW_APPLY_CONFIG = """# Configuration change flow (GitLab pipeline)

**Goal:** When the user wants to **configure** something on a device (e.g. "add VLAN 999 name TEST on sw11-1", "add ACL", "change interface"), use this flow. You produce the desired full config and trigger the apply pipeline (dry-run → manual apply in GitLab).

## When to use

User says: "configure X on device Y", "add VLAN 999 on sw11-1", "set hostname to core-01", etc. This is the **configuration** flow; the backend is the apply pipeline (flow_run_apply_flow).

## Steps for the AI

1. **Resolve target device** — If user gives a hostname (e.g. sw11-1), get primary IP from NetBox (**netbox_search_objects** endpoint `dcim/devices`, query hostname) for SSH/gNMI. Use hostname as **target_host** for the flow (file path and pipeline use hostname).

2. **Get current running config** — **ios_xe_show_command("show running-config", host=primary_ip_or_hostname)** so you have the full config to merge the change into. Optionally run a focused show (e.g. **show vlan brief**) first; if the requested change is already present, inform the user and skip the apply flow.

3. **Build desired config** — Apply the user’s change to the running config (e.g. add `vlan 999` / `name TEST` after the existing vlan block). Produce the **full** desired IOS-XE config (the pipeline expects a complete file). Avoid sending only a snippet unless the pipeline supports it.

4. **Upload and trigger dry-run** — **flow_run_apply_flow(target_host, config_content)** uploads to `ansible/configs/desired/<target_host>.txt` (creates file if missing) and triggers the apply pipeline with dry-run only. Actual apply is manual in GitLab (play **apply_config** job).

5. **Tell the user** — Dry-run is at the pipeline URL; they must review and play **apply_config** in GitLab to apply. After apply, they can run troubleshoot or collect to refresh baseline.

## One-shot tool

**flow_run_apply_flow(target_host, config_content)** — Uploads desired config and triggers dry-run. Use after you have built **config_content** (full running config + the requested change). Actual apply: manual in GitLab (play **apply_config**).

## Manual alternative

- **gitlab_update_gitlab_repository_file** to create/update `ansible/configs/desired/<hostname>.txt`, then **gitlab_trigger_gitlab_pipeline** with `DRY_RUN_PIPELINE=true`, `PIPELINE_TYPE=apply`, `TARGET_HOST=<hostname>`.
"""

FLOW_DRIFT_COMPARE = """# Drift / compare flow (GitLab pipeline + NetBox)

**Goal:** See if running config matches the collected baseline or desired state.

## Steps

1. **Collect baseline (separate pipeline)**
   - **flow_trigger_collect_pipeline(commit_collected=True)** or trigger with `PIPELINE_TYPE=collect` and `COMMIT_COLLECTED=true`: runs **collect_configs** only, then creates branch `ci/collected-baseline-<pipeline_id>`, commits `ansible/configs/baseline/*.txt`, pushes, and creates a **merge request** to main. Requires **GITLAB_PUSH_TOKEN** (write_repository + api) in GitLab.

2. **Compare (separate pipeline)**
   - **flow_trigger_compare_pipeline(commit_diffs=False)** runs **compare_configs** only; baseline = repo `ansible/configs/baseline/*.txt`. Set commit_diffs=True to push `*.diff` and compare_output.log to git.
   - Or use **flow_run_troubleshoot_flow(device)** for full troubleshoot (NetBox + Prometheus + syslog + compare). Or **rollback_verify** (dry-run) to see what would be reverted to baseline.

3. **Act**
   - If drift is desired: update `ansible/configs/desired/<hostname>.txt` and use **Apply config flow** or **flow_trigger_apply_pipeline(target_host)**.
   - If drift is unwanted: use **flow_trigger_rollback_pipeline(target_host=None)** or **flow_run_rollback_flow** (rollback_verify → manual rollback_apply in GitLab).
   - To refresh baseline in repo: use **flow_trigger_collect_pipeline(commit_collected=True)**.
"""

FLOW_PIPELINES = """# Pipeline trigger tools (one per pipeline)

Each GitLab pipeline has a dedicated flow tool that triggers it with the correct variables (uses GITLAB_TOKEN; POST projects/:id/pipeline with variables in JSON body).

| Pipeline   | Tool                              | Purpose |
|-----------|------------------------------------|---------|
| **Compare**  | flow_trigger_compare_pipeline(commit_diffs=False) | Drift: diff running config vs repo baseline ansible/configs/baseline/*.txt. Optional: commit_diffs=True to push *.diff to git. |
| **Collect**  | flow_trigger_collect_pipeline(commit_collected=False) | Fetch running configs → ansible/configs/baseline/*.txt. Optional: commit_collected=True → branch + MR to main (needs GITLAB_PUSH_TOKEN). |
| **Apply / Config** | flow_trigger_apply_pipeline(target_host=None) | Configuration change: dry-run then manual apply_config. Put desired config in ansible/configs/desired/<host>.txt first, or use flow_run_apply_flow to upload + trigger. See netops://flows/apply_config or netops://flows/configuration. |
| **Rollback** | flow_trigger_rollback_pipeline(target_host=None) | Rollback_verify (dry-run) then manual rollback_apply. Optional target_host to limit to one device. |

**Flows that use these pipelines:**
- **flow_run_troubleshoot_flow(device)** — runs NetBox + Prometheus + ClickHouse + **compare** pipeline (and waits for diff).
- **flow_run_rollback_flow(target_host)** — same as flow_trigger_rollback_pipeline + job list check.
- **flow_run_apply_flow(target_host, config_content)** — configuration flow: uploads desired config to `ansible/configs/desired/<host>.txt` then triggers **apply** pipeline (dry-run; apply manual in GitLab).
"""


def get_troubleshoot_flow() -> str:
    return FLOW_TROUBLESHOOT


def get_apply_config_flow() -> str:
    return FLOW_APPLY_CONFIG


def get_configuration_flow() -> str:
    """Same as apply_config flow; exposed as 'configuration' for intent-based discovery."""
    return FLOW_APPLY_CONFIG


def get_drift_flow() -> str:
    return FLOW_DRIFT_COMPARE


def get_pipelines_flow() -> str:
    return FLOW_PIPELINES
