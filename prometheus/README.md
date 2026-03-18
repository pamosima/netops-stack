# Prometheus

Prometheus in netops-stack stores and serves **metrics** from gNMIc (and optional IPFIX). It is scraped by the pipeline and can remote_write to ClickHouse when using ClickStack.

## Config

- **Scrape configs:** `prometheus/prometheus.yaml` — targets for gNMIc exporter, IPFIX (when overlay is used), and other jobs.
- **Port:** 9090 (default). Queried by Grafana and by the [NetOps MCP Server](../netops-mcp-server/README.md) Prometheus tools for AI troubleshooting.

## Deploy

Started with the base compose; add overlays (e.g. `compose-clickstack.yaml`) as needed. Prometheus runs as part of the stack and does not require a separate README beyond this.

## Related

- [Grafana](../grafana/README.md) — Dashboards.
- [NetOps MCP Server](../netops-mcp-server/README.md) — Prometheus query tools for MCP.
