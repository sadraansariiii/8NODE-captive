#!/usr/bin/env python3
"""
tc.py - tc (Traffic Control) Wrapper
"""
import os
import re
import subprocess
from typing import Optional, List

from . import config, logger

log = logger.get("tc")


def _ifaces() -> List[str]:
    result = []
    lan = config.get("LAN_IFACE")
    if lan:
        result.append(lan)
    wlx = config.get("WLX_IFACE")
    if wlx and wlx != lan:
        result.append(wlx)
    return result


def _classid_for(ip: str, iface: str) -> str:
    ifaces = _ifaces()
    try:
        iface_idx = ifaces.index(iface)
    except (ValueError, IndexError):
        iface_idx = 0
    last_octet = int(ip.split(".")[-1])
    base = (iface_idx * 1000) + last_octet + 100
    return f"1:{base}"


def _run(args, check=False, timeout=5) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["tc"] + args,
            capture_output=True, text=True, timeout=timeout, check=check,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", "not found")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _iface_exists(iface) -> bool:
    if not iface:
        return False
    return os.path.exists(f"/sys/class/net/{iface}")


def _iface_for_ip(ip: str) -> Optional[str]:
    ifaces = _ifaces()
    if not ifaces:
        return None
    if len(ifaces) == 1:
        return ifaces[0]
    return ifaces[0]


# ════════════════════════════════════════════════════════════
# HTB Root
# ════════════════════════════════════════════════════════════

def has_root(iface) -> bool:
    if not iface:
        return False
    r = _run(["qdisc", "show", "dev", iface])
    return "htb 1:" in (r.stdout or "")


def ensure_root(iface, total_mbit: Optional[int] = None) -> bool:
    if not _iface_exists(iface):
        return False
    if total_mbit is None:
        total_mbit = int(config.get("TOTAL_BW_MBIT", 70))
    if has_root(iface):
        return True
    _run(["qdisc", "del", "dev", iface, "root"])
    total_kbit = total_mbit * 1000
    r = _run(["qdisc", "add", "dev", iface, "root",
              "handle", "1:", "htb", "default", "999"])
    if r.returncode != 0:
        return False
    _run(["class", "add", "dev", iface, "parent", "1:", "classid", "1:1",
          "htb", "rate", f"{total_kbit}kbit", "ceil", f"{total_kbit}kbit"])
    _run(["class", "add", "dev", iface, "parent", "1:1", "classid", "1:999",
          "htb", "rate", f"{total_kbit}kbit", "ceil", f"{total_kbit}kbit"])
    return True


def remove_root(iface) -> bool:
    if not iface:
        return False
    _run(["qdisc", "del", "dev", iface, "root"])
    return True


# ════════════════════════════════════════════════════════════
# Get Bytes
# ════════════════════════════════════════════════════════════

def get_bytes(ip: str, ifaces: Optional[List[str]] = None) -> int:
    if ifaces is None:
        ifaces = _ifaces()
    total = 0
    for iface in ifaces:
        if not _iface_exists(iface):
            continue
        classid = _classid_for(ip, iface)
        r = _run(["-s", "class", "show", "dev", iface, "classid", classid])
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            m = re.search(r"Sent\s+(\d+)\s+bytes", line)
            if m:
                total += int(m.group(1))
                break
    return total


# ════════════════════════════════════════════════════════════
# Apply Bandwidth
# ════════════════════════════════════════════════════════════

def apply_bw(ip: str, rate_kbps: int, iface: Optional[str] = None) -> bool:
    if rate_kbps is None or rate_kbps <= 0:
        rate_kbps = 10000000  # unlimited
    if iface is None:
        iface = _iface_for_ip(ip)
    if not _iface_exists(iface):
        return False
    
    ensure_root(iface)
    classid = _classid_for(ip, iface)
    rate_kbit = rate_kbps * 8
    
    # ─── کلاس: change یا add ───
    r_check = _run(["class", "show", "dev", iface, "classid", classid])
    class_exists = (r_check.returncode == 0 and r_check.stdout.strip())
    
    if class_exists:
        r = _run(["class", "change", "dev", iface, "classid", classid,
                  "htb", "rate", f"{rate_kbit}kbit", "ceil", f"{rate_kbit}kbit"])
    else:
        r = _run(["class", "add", "dev", iface, "parent", "1:1",
                  "classid", classid, "htb",
                  "rate", f"{rate_kbit}kbit", "ceil", f"{rate_kbit}kbit"])
    
    if r.returncode != 0:
        log.error(f"class failed for {ip}: {r.stderr}")
        return False
    
    # ─── filters (add -exist) ───
    _run(["filter", "add", "dev", iface, "parent", "1:",
          "protocol", "ip", "prio", "1", "u32",
          "match", "ip", "dst", ip, "flowid", classid])
    
    _run(["filter", "add", "dev", iface, "parent", "1:",
          "protocol", "ip", "prio", "1", "u32",
          "match", "ip", "src", ip, "flowid", classid])
    
    log.debug(f"bw {ip} → {rate_kbps} KB/s on {iface} ({classid})")
    return True


# ════════════════════════════════════════════════════════════
# Remove
# ════════════════════════════════════════════════════════════

def remove(ip: str, ifaces: Optional[List[str]] = None) -> bool:
    if ifaces is None:
        ifaces = _ifaces()
    for iface in ifaces:
        if not _iface_exists(iface):
            continue
        classid = _classid_for(ip, iface)
        _run(["class", "del", "dev", iface, "classid", classid], check=False)
    return True


# ════════════════════════════════════════════════════════════
# Stats
# ════════════════════════════════════════════════════════════

def get_class_info(ip: str, iface: str) -> Optional[dict]:
    classid = _classid_for(ip, iface)
    r = _run(["-s", "class", "show", "dev", iface, "classid", classid])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    info = {"classid": classid}
    for line in r.stdout.splitlines():
        m = re.search(r"Sent\s+(\d+)\s+bytes\s+(\d+)\s+pkt", line)
        if m:
            info["bytes"] = int(m.group(1))
            info["packets"] = int(m.group(2))
    return info


def list_classes(iface: str) -> list:
    r = _run(["class", "show", "dev", iface])
    result = []
    for line in r.stdout.splitlines():
        m = re.search(r"class htb 1:(\d+)", line)
        if m:
            result.append(f"1:{m.group(1)}")
    return result
