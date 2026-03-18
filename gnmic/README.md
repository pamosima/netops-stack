# gNMIc (gNMI collector)

gNMIc collects **gNMI streaming telemetry** from network devices (e.g. Cisco IOS-XE Catalyst 9k) and publishes to NATS for Prometheus and other consumers.

## Role in netops-stack

- **Collector** (NAF): reads from the network via gNMI; normalizes OpenConfig-style paths.
- **Targets:** Configured in `gnmic-ingestor.yaml` with device IPs, gNMI port (typically 57400), and subscriptions (interfaces, system, BGP, etc.).
- **Output:** NATS; Prometheus scrapes or remote-writes from the pipeline as defined in the compose and [Prometheus](../prometheus/README.md) config.

## Prerequisites

- **gNMI enabled on devices:** On Cisco IOS-XE (C9k), enable `gnmi-yang` or `gnxi`. Port 57400 by default.
- **Reachability:** The host running gNMIc must reach device management IPs and gNMI port.
- **Credentials:** Username/password (or certs) in gNMIc config; use env or secrets in production (do not commit real credentials).

## Config files

- **Ingestor:** `gnmic-ingestor.yaml` — targets (device IP:port), subscriptions (e.g. `iosxe-if-state-sample`, `iosxe-if-stats`, `iosxe-system`).
- **Emitter:** Consumes from NATS and exposes to Prometheus or writes to ClickHouse depending on stack design.

Adjust targets for your CML or lab (management IP and gNMI port 57400). Some C8000V images do not support gNMI server; uncomment core targets when your image supports it.

## Deploy

From repo root, base compose includes the IOS-XE ingestor and emitter:

```bash
docker compose -f compose.yaml up -d
```

(Add `compose-clickstack.yaml`, `compose-syslog.yaml`, etc. as needed.)

## IOS-XE telemetry examples

- **Subscription names** in the YAML (e.g. `iosxe-if-state-sample`) refer to subscription configs in the same file or included configs — define the gNMI paths (e.g. interface state, counters) per Cisco IOS-XE telemetry docs.
- **Metrics:** Prometheus scrapes the exporter that gNMIc (or the pipeline) exposes; see [Prometheus](../prometheus/README.md) and Grafana dashboards for interface and system metrics.
- **CML / lab:** For Cisco Modeling Labs, ensure nodes run an IOS-XE image with gNMI support and that the gNMIc container can reach the node management IPs (NAT or direct depending on topology).

## Related

- Root [README](../README.md) — Architecture and compose overlays.
- [Prometheus](../prometheus/README.md) — Scrape config and metrics.
