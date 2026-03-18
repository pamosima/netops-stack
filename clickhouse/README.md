# ClickHouse (ClickStack)

netops-stack uses **ClickStack** as the single ClickHouse instance: [ClickStack](https://clickhouse.com/docs/use-cases/observability/clickstack) provides HyperDX UI, OpenTelemetry collector, and ClickHouse for logs, traces, and metrics. Syslog (from [Vector](../vector/README.md)) and Prometheus remote_write use this service.

## Ports

| Port  | Service           | Note                          |
|-------|-------------------|-------------------------------|
| 8080  | HyperDX UI        | Open http://\<host\>:8080     |
| 8123  | ClickHouse HTTP   | Default; syslog, queries      |
| 9363  | ClickHouse Prometheus | /metrics, /write, /read   |
| 4317  | OTLP gRPC         | Traces/logs/metrics ingest   |
| 4318  | OTLP HTTP         | Traces/logs/metrics ingest   |
| 24225 | Fluentd           | Log ingest                    |

## Deploy

From repo root (with base stack):

```bash
docker compose -f compose.yaml -f compose-clickstack.yaml up -d
```

With syslog and full stack:

```bash
docker compose -f compose.yaml -f compose-ipfix.yaml \
  -f compose-clickstack.yaml -f compose-syslog.yaml up -d
```

## First use

1. Open **http://\<host\>:8080**. Create a user (username + password) on first use.
2. HyperDX creates data sources for the local ClickHouse (logs, traces, metrics).
3. Send OTLP to **\<host\>:4317** (gRPC) or **\<host\>:4318** (HTTP) if needed.

**Login redirect to localhost:** If the UI redirects to `http://localhost:8080` when you use an IP, use an SSH tunnel (e.g. `ssh -L 8080:127.0.0.1:8080 user@host`) and open http://localhost:8080 in the browser.

## Syslog table

When using `compose-syslog.yaml`, Vector writes to `default.syslog`. The table can be created by the init container or manually. Example schema (see `clickhouse/init/` for the exact SQL used):

- `timestamp`, `host`, `facility`, `severity`, `program`, `message`, `raw`, `received_at`
- Engine: MergeTree, order by `(host, timestamp)`; optional TTL (e.g. 30 days).

Query from HyperDX or any ClickHouse client (port 8123):

```sql
SELECT host, severity, message, timestamp
FROM default.syslog
ORDER BY timestamp DESC
LIMIT 20;
```

The [NetOps MCP Server](../netops-mcp-server/README.md) ClickHouse tools query this table for AI troubleshooting.
