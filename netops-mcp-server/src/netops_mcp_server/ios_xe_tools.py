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
IOS-XE tools: show commands and config (SSH via Netmiko). Credentials from env.
"""
import os
from typing import List

from dotenv import load_dotenv
from netmiko import ConnectHandler

load_dotenv()

IOS_XE_USERNAME = os.getenv("IOS_XE_USERNAME", "")
IOS_XE_PASSWORD = os.getenv("IOS_XE_PASSWORD", "")
IOS_XE_READ_ONLY = os.getenv("IOS_XE_READ_ONLY", "false").lower() in ("true", "1", "yes")


def _device(host: str) -> dict:
    return {
        "device_type": "cisco_ios",
        "host": host,
        "username": IOS_XE_USERNAME,
        "password": IOS_XE_PASSWORD,
        "timeout": 60,
        "session_timeout": 60,
    }


def _mask(pwd: str) -> str:
    if not pwd:
        return "None"
    return pwd[0] + "*" * (len(pwd) - 1) if len(pwd) > 1 else "*"


def _sanitize(msg: str) -> str:
    if IOS_XE_PASSWORD and IOS_XE_PASSWORD in msg:
        return msg.replace(IOS_XE_PASSWORD, "***REDACTED***")
    return msg


def show_command(command: str, host: str) -> str:
    """Execute a show command via SSH on an IOS-XE device. Credentials from IOS_XE_USERNAME, IOS_XE_PASSWORD."""
    if not host:
        return "Error: host parameter is required"
    if not IOS_XE_USERNAME or not IOS_XE_PASSWORD:
        return "Error: IOS_XE_USERNAME and IOS_XE_PASSWORD must be set in environment"
    try:
        with ConnectHandler(**_device(host)) as conn:
            return conn.send_command(command)
    except Exception as e:
        return _sanitize(f"Error executing command on {host}: {e}")


def config_command(commands: List[str], host: str) -> str:
    """Send configuration commands via SSH to an IOS-XE device and save. Credentials from env. Disabled if IOS_XE_READ_ONLY=true."""
    if IOS_XE_READ_ONLY:
        return "Error: config_command is disabled when IOS_XE_READ_ONLY=true"
    if not host:
        return "Error: host parameter is required"
    if not commands or not isinstance(commands, list):
        return "Error: commands must be a non-empty list"
    if not IOS_XE_USERNAME or not IOS_XE_PASSWORD:
        return "Error: IOS_XE_USERNAME and IOS_XE_PASSWORD must be set in environment"
    try:
        with ConnectHandler(**_device(host)) as conn:
            out = conn.send_config_set(commands)
            save = conn.send_command("write memory")
            return f"Configuration applied:\n{out}\n\nSave:\n{save}"
    except Exception as e:
        return _sanitize(f"Error during configuration on {host}: {e}")


# When read-only, only show_command is exposed (main server will register conditionally)
IOS_XE_TOOLS = [
    (show_command, "show_command"),
    (config_command, "config_command"),
]
