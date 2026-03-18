# NetOps MCP Server

Single combined MCP server for **netops-stack** with **under 50 tools**, **GitLab** for CI/CD, and **AI flows** (resources + one-shot flow tool).

## Domains and tool count

| Domain      | Prefix     | Tools | Purpose |
|------------|------------|-------|--------|
| NetBox     | `netbox_`  | 9     | SoT only: get_sites, get_site_by_id, get_devices, get_device_by_id, get_device_types, get_device_roles, get_ip_addresses, get_vlans, search_objects |
| Prometheus | `prometheus_` | 5  | Metrics: query_prometheus, query_prometheus_range, list_metric_names, get_targets, suggest_queries |
| ClickHouse | `clickhouse_` | 5  | Syslog: query_syslog, query_clickhouse, get_syslog_hosts, get_severity_stats, get_recent_errors |
| GitLab     | `gitlab_`  | 8    | CI/CD: trigger pipeline, status, job logs, artifacts, list projects/pipelines, get/update repo file |
| IOS-XE     | `ios_xe_`  | 1–2  | Device: show_command; config_command (disabled if `IOS_XE_READ_ONLY=true`) |
| **Flows**  | `flow_`    | 6    | **flow_run_troubleshoot_flow**, **flow_run_rollback_flow**, **flow_run_apply_flow** (configuration flow: upload desired config → dry-run). **flow_trigger_collect_pipeline**, **flow_trigger_apply_pipeline(target_host)**, **flow_trigger_rollback_pipeline(target_host)** — one tool per pipeline. |

**Total: 29–30 tools.** NetBox is trimmed to read/search only (no create/update/delete/scripts) for troubleshooting and config flows.

## AI flows (resources + tool)

The server exposes **MCP resources** the model can read to follow recommended flows:

| Resource URI | Description |
|--------------|-------------|
| `netops://flows/troubleshoot` | Troubleshooting flow: NetBox device lookup → Prometheus metrics → ClickHouse syslog → summarize |
| `netops://flows/configuration` | **Configuration change flow:** when user says "configure X on device Y" (e.g. add VLAN, ACL) → get running config → build desired config → flow_run_apply_flow → dry-run → manual apply in GitLab. Also: `netops://flows/apply_config`. |
| `netops://flows/drift` | Drift/compare flow: collect baseline, compare, rollback or apply desired |

**One-shot flow tool:** Use **flow_run_troubleshoot_flow(device, ...)** to run the full flow. By default it **triggers the GitLab collect+compare pipeline** and waits up to 3 minutes for it, then uses the pipeline diff (full). This can take **2–3 minutes**. Set **run_compare_pipeline=False** to skip triggering and use the latest existing pipeline (faster). The response includes **pipeline_triggered** (pipeline_id, status: success/failed/timeout) so you can see what happened.

**If the pipeline doesn’t run or the diff is still short:** Restart the NetOps MCP server (rebuild the Docker image if you run in Docker) so it loads the latest code. Check **pipeline_triggered** in the JSON: if `triggered: false` or `status: error`, the trigger failed (e.g. GitLab token or rate limit); if `status: timeout`, the pipeline didn’t finish in 3 min and the flow fell back to the latest pipeline.

## Environment variables

Set in `.env` or the environment. Only set the backends you use.

| Variable | Required for | Example |
|----------|--------------|---------|
| `NETBOX_URL`, `NETBOX_TOKEN` | NetBox tools | `https://netbox.example.com`, `your-token` |
| `PROMETHEUS_URL` | Prometheus tools | `http://localhost:9090` |
| `CLICKHOUSE_URL` | ClickHouse tools | `http://localhost:8123` |
| `GITLAB_URL`, `GITLAB_TOKEN` | GitLab tools | `https://gitlab.com`, `glpat-...` |
| `IOS_XE_USERNAME`, `IOS_XE_PASSWORD` | IOS-XE tools | Device SSH credentials |
| `IOS_XE_READ_ONLY` | Optional | `true` = show only, no config_command |
| `MCP_HOST`, `MCP_PORT` | Server bind | Default `0.0.0.0`, `8010` |

## Run locally

```bash
cd netops-mcp-server
pip install -e .
# Create .env with the variables above
python -m netops_mcp_server.server
```

Server listens on `http://0.0.0.0:8010`. Use transport `streamable-http` and URL `http://localhost:8010/mcp` in Cursor or other MCP clients.

## Run with Docker

The image is built from **`uv.lock`** (reproducible deps) and a digest-pinned `python:3.12-slim` base. After changing `pyproject.toml`, run **`uv lock`** and commit `uv.lock`.

```bash
docker build -t netops-mcp-server .
docker run --env-file .env -p 8010:8010 netops-mcp-server
```

## Run with Docker Compose (MCP server only)

```bash
cd netops-mcp-server
# Ensure .env exists (copy from .env.example)
docker compose up -d
```

The compose file adds `host.docker.internal:host-gateway` so from inside the container you can use `PROMETHEUS_URL=http://host.docker.internal:9090` (and similar for NetBox, ClickHouse) when those services run on the host.

## LibreChat (or other MCP client) in Docker

If LibreChat runs in Docker too, it cannot use `http://localhost:8010/mcp` (that would be inside its own container). First see which network LibreChat is on, then put both on the same network.

**LibreChat with `docker-compose.override.yaml` using `networks: ['mcp-server']`**  
This repo’s compose is already set up to join the external network `mcp-server`. Ensure the network exists, then start the MCP server:

```bash
docker network create mcp-server   # only if it doesn't exist yet (e.g. before first LibreChat up)
cd netops-mcp-server && docker compose up -d
```

In LibreChat’s MCP config use: **`http://netops-mcp-server:8010/mcp`**

**If LibreChat uses a different network name:**

**1. Find LibreChat’s network**

```bash
docker inspect <librechat-container-name> --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

**2. Use one of these**

**Option A — MCP server joins LibreChat’s network**  
Edit `docker-compose.yaml`: change the external network name from `mcp-server` to LibreChat’s network (e.g. `librechat_default`), and under the service’s `networks` replace `mcp-server` with that name. Then `docker compose up -d`.

**Option B — LibreChat joins MCP server’s network**  
If you prefer not to edit the MCP compose:

```bash
docker network connect netops-mcp-network <librechat-container-name>
```

In LibreChat’s MCP config use: `http://netops-mcp-server:8010/mcp`

**Option C — Host gateway**  
If LibreChat has `host.docker.internal` (Docker Desktop or `--add-host=host.docker.internal:host-gateway`), use:

```text
http://host.docker.internal:8010/mcp
```

**Option D — Host IP and published port**  
If the host’s IP is reachable from LibreChat’s container: `http://<host-ip>:8010/mcp`

Ensure the MCP server binds on all interfaces (`MCP_HOST=0.0.0.0` in `.env`, which is the default).

## Cursor MCP config

Add to `~/.cursor/mcp.json` (or project MCP config):

```json
{
  "mcpServers": {
    "NetOps-MCP-Server": {
      "transport": "http",
      "url": "http://localhost:8010/mcp",
      "timeout": 60000
    }
  }
}
```

## GitLab tools (CI/CD)

- **gitlab_trigger_gitlab_pipeline** — Trigger pipeline (e.g. with `ROLLBACK_PIPELINE=true`, `TARGET_HOST=sw11-1`).
- **gitlab_get_gitlab_pipeline_status** — Check pipeline status and jobs.
- **gitlab_play_gitlab_job** — Play a manual job (e.g. rollback_apply after triggering with ROLLBACK_PIPELINE=true).
- **gitlab_get_gitlab_job_logs** — Get job log (e.g. dry-run output).
- **gitlab_get_gitlab_job_artifact** — Download artifact (e.g. `ansible/ansible_dry_run_output.log`).
- **gitlab_list_gitlab_projects**, **gitlab_list_gitlab_pipelines** — List projects and pipelines.
- **gitlab_get_gitlab_repository_file** — Read file (allowed paths: ansible/, configs/, etc.).
- **gitlab_update_gitlab_repository_file** — Create/update file (e.g. `ansible/configs/desired/sw11-1.txt`), then trigger dry-run.

This fits the netops-stack apply flow: update desired config in repo via MCP, trigger pipeline with dry-run, then manual apply.

**If pipeline trigger returns 400 ("resulting pipeline would have been empty" or "workflow:rules ... did not run"):** Variables are not reaching the pipeline. (1) Ensure **GITLAB_TOKEN** is set (project or personal access token with `api` scope). (2) If logs show `variables_keys=[]`, the MCP server filtered them: in `.env` remove `GITLAB_ALLOWED_VARIABLES` or set it to include COMPARE_ONLY, PIPELINE_TYPE, ROLLBACK_PIPELINE, etc.; restart the server. (3) Confirm the project's `.gitlab-ci.yml` on the target ref has the right rules for the variables you send.

## NetBox tools (use-case focused)

Only read and search tools are exposed (no create/update/delete or custom scripts):

- **get_sites**, **get_site_by_id** — List sites / get one by ID.
- **get_devices**, **get_device_by_id** — List devices (optionally by site) / get one by ID.
- **get_device_types**, **get_device_roles** — For reference when correlating devices.
- **get_ip_addresses**, **get_vlans** — IPAM/VLAN reference.
- **search_objects(endpoint, query, limit)** — Search any NetBox endpoint (e.g. `dcim/devices`, `ipam/ip-addresses`) by query string.

Use cases: SoT for troubleshooting (which device, primary IP, site), and for apply-config flow (target hostname).

## Troubleshooting and related docs

- **Troubleshooting flows:** NetBox → Prometheus → ClickHouse → summarize; use the troubleshoot flow and resources in this README.
