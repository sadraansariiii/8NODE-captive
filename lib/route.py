#!/usr/bin/env python3
"""
route.py - Routing Manager
============================
مدیریت ip route و ip rule
- policy routing (mark → table 100)
- route به L2TP server
- default route در table 100 → ppp
"""
import os
import re
import subprocess
from typing import Optional, List

from . import config, logger, network

log = logger.get("route")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _run(args, check=False, timeout=10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=check
        )
    except subprocess.TimeoutExpired:
        log.error(f"timeout: {' '.join(args)}")
        return subprocess.CompletedProcess(args, 1, "", "timeout")
    except Exception as e:
        log.error(f"error: {e}")
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _ip(*args) -> subprocess.CompletedProcess:
    """اجرای ip <args>"""
    return _run(["ip"] + list(args))


# ════════════════════════════════════════════════════════════
# rt_tables
# ════════════════════════════════════════════════════════════

def setup_rt_tables(cfg: Optional[dict] = None) -> bool:
    """
    اضافه کردن خط <id> <name> به /etc/iproute2/rt_tables
    """
    if cfg is None:
        cfg = config.all()
    
    table_id = str(cfg.get("RT_TABLE_ID", 100))
    table_name = cfg.get("RT_TABLE_NAME", "ppp")
    path = cfg.get("RT_TABLES_FILE", "/etc/iproute2/rt_tables")
    
    if not os.path.exists(path):
        log.warning(f"{path} not found")
        return False
    
    try:
        with open(path) as f:
            lines = f.readlines()
    except Exception as e:
        log.error(f"cannot read {path}: {e}")
        return False
    
    # حذف خط قبلی با این id
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        parts = stripped.split()
        if parts and parts[0] == table_id:
            continue  # حذف
        new_lines.append(line)
    
    # اضافه
    new_lines.append(f"{table_id}\t{table_name}\n")
    
    try:
        with open(path, "w") as f:
            f.writelines(new_lines)
        log.info(f"rt_tables: {table_id} {table_name}")
        return True
    except Exception as e:
        log.error(f"cannot write {path}: {e}")
        return False


# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

def add_l2tp_route(cfg: Optional[dict] = None) -> bool:
    """
    route به L2TP server از طریق WAN
    """
    if cfg is None:
        cfg = config.all()
    
    l2tp_server = cfg.get("L2TP_SERVER")
    wan_iface = cfg.get("WAN_IFACE")
    wan_gateway = cfg.get("WAN_GATEWAY") or network.get_wan_gateway()
    
    if not l2tp_server or not wan_iface:
        log.warning("L2TP_SERVER or WAN_IFACE missing")
        return False
    
    if wan_gateway:
        r = _ip("route", "replace", f"{l2tp_server}/32",
                "via", wan_gateway, "dev", wan_iface)
    else:
        r = _ip("route", "replace", f"{l2tp_server}/32", "dev", wan_iface)
    
    if r.returncode == 0:
        log.info(f"route {l2tp_server} via {wan_gateway or wan_iface}")
        return True
    else:
        log.error(f"add route failed: {r.stderr}")
        return False


def remove_l2tp_route(cfg: Optional[dict] = None) -> bool:
    """حذف route به L2TP"""
    if cfg is None:
        cfg = config.all()
    l2tp_server = cfg.get("L2TP_SERVER")
    if not l2tp_server:
        return False
    _ip("route", "del", f"{l2tp_server}/32")
    return True


# ════════════════════════════════════════════════════════════
# Policy Routing
# ════════════════════════════════════════════════════════════

def _delete_rule_by_fwmark(mark: int):
    """حذف ip rule با fwmark"""
    while True:
        r = _ip("rule", "del", "fwmark", str(mark))
        if r.returncode != 0:
            break


def _delete_rule_by_priority(priority: int):
    """حذف ip rule با priority"""
    r = _ip("rule", "del", "priority", str(priority))
    return r.returncode == 0


def setup_policy_routing(cfg: Optional[dict] = None) -> bool:
    """
    ip rule: fwmark 100 → table 100
    """
    if cfg is None:
        cfg = config.all()
    
    mark = int(cfg.get("FW_MARK", 100))
    table_id = int(cfg.get("RT_TABLE_ID", 100))
    priority = int(cfg.get("IP_RULE_PRIORITY", 219))
    
    # حذف قبلی
    _delete_rule_by_fwmark(mark)
    _delete_rule_by_priority(priority)
    
    # اضافه
    r = _ip("rule", "add", "fwmark", str(mark),
            "lookup", str(table_id), "priority", str(priority))
    
    if r.returncode == 0:
        log.info(f"ip rule: fwmark {mark} → table {table_id} (prio {priority})")
        return True
    else:
        log.error(f"ip rule failed: {r.stderr}")
        return False


def remove_policy_routing(cfg: Optional[dict] = None) -> bool:
    """حذف ip rule"""
    if cfg is None:
        cfg = config.all()
    mark = int(cfg.get("FW_MARK", 100))
    priority = int(cfg.get("IP_RULE_PRIORITY", 219))
    _delete_rule_by_fwmark(mark)
    _delete_rule_by_priority(priority)
    return True


# ════════════════════════════════════════════════════════════
# Table 100
# ════════════════════════════════════════════════════════════

def setup_ppp_table(cfg: Optional[dict] = None,
                     ppp_iface: Optional[str] = None) -> bool:
    """
    default route در table 100 → ppp
    """
    if cfg is None:
        cfg = config.all()
    
    table_id = str(cfg.get("RT_TABLE_ID", 100))
    tunnel_iface = ppp_iface or cfg.get("TUNNEL_IFACE", "ppp0")
    
    # flush قبلی
    _ip("route", "flush", "table", table_id)
    
    # چک اگه ppp وجود داره
    if not network.iface_exists(tunnel_iface):
        # سعی کن ppp دیگه پیدا کنی
        r = _ip("-br", "link", "show")
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split()
                if parts and parts[0].startswith("ppp"):
                    tunnel_iface = parts[0]
                    break
    
    if not network.iface_exists(tunnel_iface):
        log.warning(f"no PPP interface found (expected {tunnel_iface})")
        return False
    
    # default route در table
    r = _ip("route", "replace", "default", "dev", tunnel_iface,
            "table", table_id)
    
    if r.returncode == 0:
        log.info(f"table {table_id}: default dev {tunnel_iface}")
        # MTU
        mtu = cfg.get("L2TP_MTU", 1280)
        _ip("link", "set", tunnel_iface, "mtu", str(mtu))
        return True
    else:
        log.error(f"table {table_id} failed: {r.stderr}")
        return False


def flush_ppp_table(cfg: Optional[dict] = None) -> bool:
    """پاک کردن table 100"""
    if cfg is None:
        cfg = config.all()
    table_id = str(cfg.get("RT_TABLE_ID", 100))
    _ip("route", "flush", "table", table_id)
    return True


# ════════════════════════════════════════════════════════════
# Setup All
# ════════════════════════════════════════════════════════════

def setup_all(cfg: Optional[dict] = None) -> bool:
    """راه‌اندازی کامل routing"""
    if cfg is None:
        cfg = config.all()
    
    log.info("setting up routing...")
    
    setup_rt_tables(cfg)
    add_l2tp_route(cfg)
    setup_policy_routing(cfg)
    setup_ppp_table(cfg)
    
    log.info("routing setup complete")
    return True


def remove_all(cfg: Optional[dict] = None) -> bool:
    """حذف همه routing"""
    if cfg is None:
        cfg = config.all()
    
    remove_policy_routing(cfg)
    flush_ppp_table(cfg)
    remove_l2tp_route(cfg)
    return True


# ════════════════════════════════════════════════════════════
# Info
# ════════════════════════════════════════════════════════════

def show_rules() -> str:
    """ip rule show"""
    r = _ip("rule", "show")
    return r.stdout

def show_table(table_id: Optional[int] = None) -> str:
    """ip route show table X"""
    if table_id is None:
        table_id = int(config.get("RT_TABLE_ID", 100))
    r = _ip("route", "show", "table", str(table_id))
    return r.stdout
