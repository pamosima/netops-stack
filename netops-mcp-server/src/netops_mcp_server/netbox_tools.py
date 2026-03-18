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
NetBox DCIM/IPAM tools (read + search only for netops use cases).
"""
import logging
import os
from typing import Any, Dict, List, Optional, Union

_log = logging.getLogger(__name__)

import requests

NETBOX_URL = os.getenv("NETBOX_URL", "").rstrip("/")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN", "")
NETBOX_VERIFY_SSL = os.getenv("NETBOX_VERIFY_SSL", "true").lower() in ("true", "1", "yes")


class NetBoxClient:
    def __init__(self, url: str, token: str, verify: bool = True):
        self.api = f"{url.rstrip('/')}/api"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {token}", "Content-Type": "application/json", "Accept": "application/json"})
        self.verify = verify

    def _url(self, endpoint: str, id: Optional[int] = None) -> str:
        e = endpoint.strip("/")
        return f"{self.api}/{e}/{id}/" if id is not None else f"{self.api}/{e}/"

    def get(self, endpoint: str, id: Optional[int] = None, params: Optional[Dict] = None) -> Union[Dict, List]:
        r = self.session.get(self._url(endpoint, id), params=params, verify=self.verify)
        r.raise_for_status()
        d = r.json()
        return d.get("results", d) if id is None and isinstance(d, dict) and "results" in d else d

    def create(self, endpoint: str, data: Dict) -> Dict:
        r = self.session.post(self._url(endpoint), json=data, verify=self.verify)
        r.raise_for_status()
        return r.json()

    def update(self, endpoint: str, id: int, data: Dict) -> Dict:
        r = self.session.patch(self._url(endpoint, id), json=data, verify=self.verify)
        r.raise_for_status()
        return r.json()

    def delete(self, endpoint: str, id: int) -> bool:
        r = self.session.delete(self._url(endpoint, id), verify=self.verify)
        return r.status_code == 204


_client: Optional[NetBoxClient] = None


def _nb() -> NetBoxClient:
    global _client
    if _client is None:
        if not NETBOX_URL or not NETBOX_TOKEN:
            raise RuntimeError("NETBOX_URL and NETBOX_TOKEN must be set")
        _client = NetBoxClient(NETBOX_URL, NETBOX_TOKEN, NETBOX_VERIFY_SSL)
    return _client


def _wrap(f, *a, **k):
    try:
        return {"success": True, "data": f(*a, **k)}
    except Exception as e:
        _log.debug("NetBox tool error: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


def get_sites(limit: int = 50, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get sites from NetBox DCIM."""
    q = {"limit": limit}
    if params:
        q.update(params)
    return _wrap(_nb().get, "dcim/sites", params=q)


def get_site_by_id(site_id: int) -> Dict[str, Any]:
    """Get a site by ID."""
    return _wrap(_nb().get, "dcim/sites", id=site_id)


def get_devices(limit: int = 50, site_id: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get devices from NetBox DCIM."""
    q = {"limit": limit}
    if site_id:
        q["site_id"] = site_id
    if params:
        q.update(params)
    return _wrap(_nb().get, "dcim/devices", params=q)


def get_device_by_id(device_id: int) -> Dict[str, Any]:
    """Get a device by ID."""
    return _wrap(_nb().get, "dcim/devices", id=device_id)


def get_device_types(limit: int = 50, manufacturer_id: Optional[int] = None) -> Dict[str, Any]:
    """Get device types from NetBox."""
    q = {"limit": limit}
    if manufacturer_id:
        q["manufacturer_id"] = manufacturer_id
    return _wrap(_nb().get, "dcim/device-types", params=q)


def get_device_roles(limit: int = 50) -> Dict[str, Any]:
    """Get device roles from NetBox."""
    return _wrap(_nb().get, "dcim/device-roles", params={"limit": limit})


def get_ip_addresses(limit: int = 50, vrf_id: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get IP addresses from NetBox IPAM."""
    q = {"limit": limit}
    if vrf_id:
        q["vrf_id"] = vrf_id
    if params:
        q.update(params)
    return _wrap(_nb().get, "ipam/ip-addresses", params=q)


def get_vlans(limit: int = 50, site_id: Optional[int] = None) -> Dict[str, Any]:
    """Get VLANs from NetBox IPAM."""
    q = {"limit": limit}
    if site_id:
        q["site_id"] = site_id
    return _wrap(_nb().get, "ipam/vlans", params=q)


def search_objects(endpoint: str, query: str, limit: int = 25) -> Dict[str, Any]:
    """Search NetBox objects with q parameter (e.g. dcim/devices, ipam/ip-addresses)."""
    return _wrap(_nb().get, endpoint, params={"q": query, "limit": limit})


# Use-case focused: SoT for troubleshooting and config flows only (no create/update/delete/scripts).
NETBOX_TOOLS = [
    (get_sites, "get_sites"),
    (get_site_by_id, "get_site_by_id"),
    (get_devices, "get_devices"),
    (get_device_by_id, "get_device_by_id"),
    (get_device_types, "get_device_types"),
    (get_device_roles, "get_device_roles"),
    (get_ip_addresses, "get_ip_addresses"),
    (get_vlans, "get_vlans"),
    (search_objects, "search_objects"),
]
