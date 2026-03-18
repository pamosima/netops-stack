# NetBox import data (lab seed)

CSV and YAML files in this folder are **exports** used to seed or refresh a **NetBox** instance so it matches the [CML lab topology](../cml/README.md) (BGP EVPN fabric, IOS-XE devices, `198.18.170.x` management IPs).

## Device roles vs device types (different things)

| Concept | Meaning in NetBox | Files here | Example |
|---------|-------------------|------------|---------|
| **Device role** | *Function* in the design — spine, leaf, router, etc. | **`netbox_device_roles.csv`** | `Leaf`, `Border/Spine`, `Router` |
| **Device type** | *Hardware model* — manufacturer + SKU, interfaces template | **`netbox_device_types.yaml`** | `C9KV-UADP-8P`, `Catalyst 8000v` |

A single device has **one role** and **one type** (e.g. **leaf-1** = role **Leaf**, type **C9KV-UADP-8P**). **Roles** CSV ≠ **types** YAML.

## Files

| File | NetBox object | Notes |
|------|---------------|--------|
| `netbox_regions.csv` | Regions | EMEA, AMER, APAC |
| `netbox_manufacturers.csv` | Manufacturers | Cisco |
| `netbox_device_roles.csv` | **Device roles** | Border/Spine, Leaf, Router |
| `netbox_sites.csv` | Sites | Fabric Site |
| `netbox_platforms.csv` | Platforms | ios-xe |
| `netbox_device_types.yaml` | **Device types** | Models + interface/console templates (bulk import YAML) |
| `netbox_devices.csv` | Devices | Links each device to a **role** + **type** + site + IP |

## Import order (do not skip steps)

Import **one step at a time**, in this exact order. Later rows reference names/slugs created earlier.

| Step | NetBox menu | File | Must exist first |
|------|-------------|------|------------------|
| **1** | *Organization → Regions* | `netbox_regions.csv` | — |
| **2** | *Devices → Manufacturers* | `netbox_manufacturers.csv` | — |
| **3** | *Organization → Device Roles* | **`netbox_device_roles.csv`** (roles, not hardware) | — |
| **4** | *Organization → Sites* | `netbox_sites.csv` | Region **EMEA** (slug `emea`) from step 1 |
| **5** | *Devices → Platforms* | `netbox_platforms.csv` | — |
| **6** | *Devices → Device types* | **`netbox_device_types.yaml`** (hardware models, not roles) | Manufacturer **Cisco** from step 2 |
| **7** | *Devices → Devices* | `netbox_devices.csv` | Site + **role** (step 3) + **type** (step 6) + platform |

**Why this order**

- **Sites** need a **region**.
- **Device types** need a **manufacturer**.
- **Devices** need a **site**, **device role** (from *roles* CSV), and **device type** (from *types* YAML) — plus platform where set.

**How to import each CSV/YAML**

Use **Bulk import** on the matching object list (button on the top right of the list), or **Operations → Import** where your NetBox version exposes it. Select the correct **data model**, upload the file, then **Submit** before moving to the next step.

**If step 7 fails**

- Confirm device role **names** exactly match: `Border/Spine`, `Leaf`, `Router`.
- Confirm device **type** **model** names match: `C9KV-UADP-8P`, `Catalyst 8000v`.
- Confirm site name **Fabric Site** (slug `fabric-site`) exists.

## Fresh NetBox vs. existing data

- Exports include **ID** and timestamp columns from the source instance. On a **blank** NetBox, imports may fail if NetBox treats IDs as reserved or if slugs already exist.
- **Typical fixes:** remove or ignore the `ID` column on import if the UI allows mapping; or edit CSVs so slugs/names match your target org; resolve duplicate slug errors manually.

## Alignment with automation

- **Ansible / GitLab:** Inventory can be generated from NetBox (e.g. `nb_inventory.yml`) once sites and devices match this data.
- **MCP / NetOps Assistant:** Uses NetBox as source of truth for sites and devices—consistent naming with CML hostnames (`border-1`, `leaf-1`, …) improves troubleshooting flows.

## Security

- These files describe **lab** layout only. Do not place production secrets in NetBox exports committed to git.
- API tokens for NetBox belong in environment / secrets managers, not in this folder.

## See also

- [CML topology → `../cml/README.md`](../cml/README.md)
- [NetBox documentation — bulk import](https://docs.netbox.dev/en/stable/models/extras/import/)
