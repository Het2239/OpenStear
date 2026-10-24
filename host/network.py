"""List the PC's IPv4 addresses and recognise USB tethering links."""

import ipaddress
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

LAN, TETHER, VIRTUAL = "lan", "tether", "virtual"

# Interface names/descriptions of VPNs, VMs and containers. A phone can't
# reach the PC through these.
_VIRTUAL_HINTS = (
    "docker", "veth", "br-", "virbr", "vmnet", "vmware", "virtualbox", "vbox",
    "hyper-v", "vethernet", "wsl", "tailscale", "zerotier", "wireguard", "wg",
    "tun", "tap", "warp", "cloudflare", "loopback", "npcap", "hamachi",
)
# Descriptions/drivers of phone USB tethering adapters.
_TETHER_HINTS = ("rndis", "remote ndis", "apple mobile device ethernet", "ipheth", "cdc_ncm")
# iPhone Personal Hotspot always hands out this subnet.
_IPHONE_NET = ipaddress.ip_network("172.20.10.0/28")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True)
class Iface:
    name: str
    ip: str
    kind: str
    description: str = ""

    @property
    def label(self):
        tag = {TETHER: "USB tethering", LAN: "network"}.get(self.kind, self.kind)
        return f"{self.ip}  ({self.name}, {tag})"


def _windows_descriptions():
    """Map adapter name -> description, e.g. 'Ethernet 3' -> 'Remote NDIS ...'."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetAdapter | Select-Object Name,InterfaceDescription | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000,
        ).stdout
        rows = json.loads(out or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        return {r["Name"]: r.get("InterfaceDescription") or "" for r in rows}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log.debug("Get-NetAdapter failed: %s", e)
        return {}


def _linux_description(name):
    """Kernel driver name, e.g. 'rndis_host'. Virtual interfaces have none."""
    try:
        return Path(f"/sys/class/net/{name}/device/driver").resolve().name
    except OSError:
        return ""


def classify(name, ip, description=""):
    addr = ipaddress.ip_address(ip)
    text = f"{name} {description}".lower()
    if addr in _IPHONE_NET or any(h in text for h in _TETHER_HINTS):
        return TETHER
    if addr.is_loopback or addr.is_link_local or addr in _CGNAT:
        return VIRTUAL
    if any(h in text for h in _VIRTUAL_HINTS):
        return VIRTUAL
    if sys.platform.startswith("linux") and not description:
        return VIRTUAL  # no backing device: bridge, VPN or container
    return LAN


def list_ifaces():
    descriptions = _windows_descriptions() if sys.platform == "win32" else {}
    stats = psutil.net_if_stats()
    result = []
    for name, addrs in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup:
            continue
        desc = descriptions.get(name, "")
        if sys.platform.startswith("linux"):
            desc = _linux_description(name)
        for a in addrs:
            if a.family.name != "AF_INET":
                continue
            # A /32 has no neighbours to talk to (typical for VPN tunnels).
            if a.netmask == "255.255.255.255":
                kind = VIRTUAL
            else:
                kind = classify(name, a.address, desc)
            result.append(Iface(name, a.address, kind, desc))
    return result


def candidates(mode, ifaces=None):
    """Interfaces a phone could use in `mode` ("wifi" or "tether"), best first."""
    ifaces = list_ifaces() if ifaces is None else ifaces
    if mode == "tether":
        return [i for i in ifaces if i.kind == TETHER]
    lan = [i for i in ifaces if i.kind == LAN]
    # Prefer typical home networks over other private ranges.
    lan.sort(key=lambda i: not i.ip.startswith("192.168."))
    return lan
