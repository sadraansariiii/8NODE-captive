#!/usr/bin/env python3
"""
network.py - Network Utilities
================================
- ARP status
- MAC from dnsmasq leases
- Interface detection
"""
import os
import re
import subprocess
from typing import Optional, List, Dict

from . import config, logger

log = logger.get("network")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _ifaces() -> List[str]:
    """interface های LAN"""
    result = []
    lan = config.get("LAN_IFACE")
    if lan:
        result.append(lan)
    wlx = config.get("WLX_IFACE")
    if wlx and wlx != lan:
        result.append(wlx)
    return result


def _run(args, timeout=5) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["ip"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:
        log.error(f"ip error: {e}")
        return subprocess.CompletedProcess(args, 1, "", str(e))


# ════════════════════════════════════════════════════════════
# ARP
# ════════════════════════════════════════════════════════════

REACHABLE_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT", "NOARP"}


def get_arp_status(ifaces: Optional[List[str]] = None) -> Dict[str, str]:
    """{ip: state}"""
    if ifaces is None:
        ifaces = _ifaces()
    
    result = {}
    for iface in ifaces:
        if not iface or not os.path.exists(f"/sys/class/net/{iface}"):
            continue
        r = _run(["neigh", "show", "dev", iface])
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            parts = line.split()
            if parts:
                result[parts[0]] = parts[-1]
    return result


def is_reachable(state: str) -> bool:
    return state in REACHABLE_STATES


def is_failed(state: str) -> bool:
    return state == "FAILED"


def is_unknown(state: str) -> bool:
    return state in ("UNKNOWN", "INCOMPLETE", "NONE", "")


# ════════════════════════════════════════════════════════════
# MAC / Leases
# ════════════════════════════════════════════════════════════

def _lease_files() -> List[str]:
    return [
        "/var/lib/misc/dnsmasq.leases",
        "/var/lib/dnsmasq/dnsmasq.leases",
        "/var/run/dnsmasq/dnsmasq.leases",
    ]


def get_all_leases() -> List[dict]:
    result = []
    for lf in _lease_files():
        if not os.path.exists(lf):
            continue
        try:
            with open(lf) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        result.append({
                            "expires": parts[0],
                            "mac": parts[1],
                            "ip": parts[2],
                            "hostname": parts[3] if len(parts) > 3 else "",
                        })
        except Exception as e:
            log.warning(f"cannot read {lf}: {e}")
    return result


def get_all_ips() -> List[str]:
    return [l["ip"] for l in get_all_leases()]


def get_mac_from_leases(ip: str) -> Optional[str]:
    for lease in get_all_leases():
        if lease["ip"] == ip:
            return lease["mac"]
    return None


def get_ip_from_mac(mac: str) -> Optional[str]:
    for lease in get_all_leases():
        if lease["mac"].lower() == mac.lower():
            return lease["ip"]
    return None


# ════════════════════════════════════════════════════════════
# Interface
# ════════════════════════════════════════════════════════════

def iface_exists(iface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{iface}")


def get_iface_ip(iface: str) -> Optional[str]:
    if not iface_exists(iface):
        return None
    r = _run(["-o", "-4", "addr", "show", "dev", iface])
    if r.returncode != 0:
        return None
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", r.stdout)
    return m.group(1) if m else None


def get_iface_network(iface: str) -> Optional[str]:
    if not iface_exists(iface):
        return None
    r = _run(["-o", "-4", "addr", "show", "dev", iface])
    if r.returncode != 0:
        return None
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", r.stdout)
    if not m:
        return None
    ip = m.group(1)
    cidr = int(m.group(2))
    if cidr == 24:
        parts = ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    return f"{ip}/{cidr}"


def get_iface_for_ip(ip: str) -> Optional[str]:
    ifaces = _ifaces()
    for iface in ifaces:
        network = get_iface_network(iface)
        if not network:
            continue
        net_parts = network.split(".")[:3]
        ip_parts = ip.split(".")[:3]
        if net_parts == ip_parts:
            return iface
    return ifaces[0] if ifaces else None


def list_ifaces() -> List[str]:
    r = _run(["-br", "link", "show"])
    if r.returncode != 0:
        return []
    result = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] != "lo":
            result.append(parts[0])
    return result


def list_lan_ifaces() -> List[str]:
    return _ifaces()


def get_wan_iface() -> Optional[str]:
    return config.get("WAN_IFACE")


def get_wan_gateway() -> Optional[str]:
    gw = config.get("WAN_GATEWAY")
    if gw:
        return gw
    wan = get_wan_iface()
    if not wan:
        return None
    r = _run(["route", "show", "default"])
    for line in r.stdout.splitlines():
        if f"dev {wan}" in line:
            m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                return m.group(1)
    return None


# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

def get_default_route() -> Optional[dict]:
    r = _run(["route", "show", "default"])
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        m = re.search(r"default\s+via\s+(\S+)\s+dev\s+(\S+)", line)
        if m:
            return {"gateway": m.group(1), "iface": m.group(2)}
    return None


def get_route_for(ip: str) -> Optional[dict]:
    r = _run(["route", "get", ip])
    if r.returncode != 0:
        return None
    result = {}
    m = re.search(r"via\s+(\S+)", r.stdout)
    if m:
        result["gateway"] = m.group(1)
    m = re.search(r"dev\s+(\S+)", r.stdout)
    if m:
        result["iface"] = m.group(1)
    m = re.search(r"src\s+(\S+)", r.stdout)
    if m:
        result["src"] = m.group(1)
    return result if result else None


# ════════════════════════════════════════════════════════════
# Ping
# ════════════════════════════════════════════════════════════

def ping(ip: str, count: int = 1, timeout: int = 2) -> bool:
    try:
        r = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), ip],
            capture_output=True, timeout=timeout + 1,
        )
        return r.returncode == 0
    except Exception:
        return False
