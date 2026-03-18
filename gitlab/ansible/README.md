# Ansible playbooks for netops-stack orchestrator

Config collection (and later diff/apply) for the netops-stack orchestrator. In the GitLab repo this is at **ansible/** (repo root = contents of netops-stack’s **gitlab/** folder). **Inventory is NetBox only** (no static host file), aligned with the [LTROPS-2341](https://github.com/tspuhler/LTROPS-2341) pattern.

## Layout

| Path | Purpose |
|------|---------|
| `playbooks/collect_configs.yml` | Collect running config from **active** NetBox devices; write to `configs/baseline/<hostname>.txt`. |
| `inventory/nb_inventory.yml` | NetBox dynamic inventory (plugin config). |
| `group_vars/all.yml` | Default connection vars (network_cli, cisco.ios.ios, user from env). |
| `requirements.yml` | Galaxy collections: `cisco.ios`, `ansible.netcommon`, `netbox.netbox`. |

## Prerequisites

1. **Install collections** (from repo root):
   ```bash
   ansible-galaxy collection install -r ansible/requirements.yml
   ```

2. **NetBox device status:** Set devices you automate to **Active**; use **Offline** (or planned/staged) for spares, maintenance, or decommissioned gear so they are skipped. The inventory filters to `status: active`, and playbooks target the `netbox_status_active` group. Each host has `netbox_device_status` (slug, e.g. `active`, `offline`) for ad-hoc use. To include multiple statuses in inventory, adjust `query_filters` in `inventory/nb_inventory.yml` and keep playbooks on `netbox_status_active` unless you intentionally want to automate other statuses.

3. **NetBox:** Active devices need a **primary IP** (used as `ansible_host`). Set **platform** (e.g. Cisco IOS) in NetBox so the correct network OS is used, or rely on `group_vars/all.yml` default (`cisco.ios.ios`).

4. **Environment variables** (never commit):
   - **NetBox:** Plugin reads `NETBOX_URL` or `NETBOX_API` and `NETBOX_TOKEN` from the environment. Optional: `NETBOX_VERIFY_SSL=false` for self-signed.
   - **SSH:** `ANSIBLE_USER`, and either `ANSIBLE_PASSWORD` or `ANSIBLE_SSH_PRIVATE_KEY_FILE`.

## Run collect locally

Export NetBox URL and token; the inventory plugin reads them from the environment (no api_endpoint/token in the YAML file).

From repo root:

```bash
export NETBOX_API=https://your-netbox.example.com NETBOX_TOKEN=your-token   # or NETBOX_URL

ansible-inventory --list -i ansible/inventory/nb_inventory.yml
ansible-playbook ansible/playbooks/collect_configs.yml -i ansible/inventory/nb_inventory.yml

# Limit by hostname or group
ansible-playbook ansible/playbooks/collect_configs.yml -i ansible/inventory/nb_inventory.yml -l sw11-1
```

From inside `ansible/`:

```bash
cd ansible
export NETBOX_API=... NETBOX_TOKEN=...
ansible-inventory --list -i inventory/nb_inventory.yml
ansible-playbook playbooks/collect_configs.yml -i inventory/nb_inventory.yml
```

Configs are written to `configs/baseline/<hostname>.txt`.

## GitLab CI (LTROPS-2341 style)

In **netops-stack/orchestrator**, set CI/CD variables (masked): `NETBOX_URL`, `NETBOX_TOKEN`, `ANSIBLE_USER`, `ANSIBLE_PASSWORD` (or use SSH key in the runner image). Then run:

The pipeline in **.gitlab-ci.yml** (at repo root) uses `./ansible/` paths. Use a Docker image built from **Dockerfile** at repo root (or [LTROPS-2341 docker/](https://github.com/tspuhler/LTROPS-2341)). In netops-stack repo see [gitlab/README.md](../README.md) for the full design.
