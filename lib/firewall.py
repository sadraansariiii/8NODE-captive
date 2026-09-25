#!/usr/bin/env python3
"""
firewall.py - iptables Manager
================================
همه iptables rules از اینجا.
"""
import os
import subprocess
from typing import Optional, List

from . import config, logger, network

log = logger.get("firewall")


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
    except FileNotFoundError:
        log.error(f"command not found: {args[0]}")
        return subprocess.CompletedProcess(args, 127, "", "not found")
    except Exception as e:
        log.error(f"error: {e}")
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _iptables(table: str, *args, check: bool = False) -> subprocess.CompletedProcess:
    """اجرای iptables -t <table> <args>"""
    return _run(["iptables", "-t", table] + list(args), check=check)


def _flush_chain(table: str, chain: str):
    """flush یه chain"""
    _iptables(table, "-F", chain)


def _delete_chain(table: str, chain: str):
    """حذف chain (اگه خالیه)"""
    _iptables(table, "-X", chain)


def _set_policy(table: str, chain: str, policy: str):
    """policy پیش‌فرض"""
    _iptables(table, "-P", chain, policy)


def _ifaces_lan() -> List[str]:
    """interface های LAN"""
    result = []
    lan = config.get("LAN_IFACE")
    if lan:
        result.append(lan)
    wlx = config.get("WLX_IFACE")
    if wlx and wlx != lan:
        result.append(wlx)
    return result


def _get_iface_network(iface: str) -> Optional[str]:
    """subnet یه interface"""
    return network.get_iface_network(iface)


# ════════════════════════════════════════════════════════════
# Flush
# ════════════════════════════════════════════════════════════

def flush_all():
    """پاک‌سازی همه rules"""
    for table in ("filter", "nat", "mangle", "raw", "security"):
        try:
            _iptables(table, "-F")
            _iptables(table, "-X")
        except Exception:
            pass
    
    # policy ها
    for table, chain in [
        ("filter", "INPUT"),
        ("filter", "FORWARD"),
        ("filter", "OUTPUT"),
        ("nat", "PREROUTING"),
        ("nat", "POSTROUTING"),
        ("nat", "OUTPUT"),
        ("mangle", "PREROUTING"),
        ("mangle", "FORWARD"),
        ("mangle", "OUTPUT"),
        ("mangle", "POSTROUTING"),
    ]:
        _iptables(table, "-P", chain, "ACCEPT")
    
    log.info("all iptables rules flushed")


# ════════════════════════════════════════════════════════════
# Filter (FORWARD + INPUT)
# ════════════════════════════════════════════════════════════

def setup_filter(cfg: dict):
    """filter table: FORWARD + INPUT"""
    _flush_chain("filter", "FORWARD")
    _flush_chain("filter", "INPUT")
    
    _set_policy("filter", "FORWARD", "DROP")
    _set_policy("filter", "INPUT", "DROP")
    _set_policy("filter", "OUTPUT", "ACCEPT")
    
    wan = cfg.get("WAN_IFACE")
    portal_port = cfg.get("PORTAL_PORT", 8080)
    admin_port = cfg.get("ADMIN_PORT", 7575)
    admin_enabled = cfg.get("ADMIN_ENABLED", True)
    ipset_name = cfg.get("IPSET_NAME", "authorized_clients")
    
    # ─── INPUT ───
    _iptables("filter", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT")
    _iptables("filter", "-A", "INPUT", "-m", "state", "--state",
              "RELATED,ESTABLISHED", "-j", "ACCEPT")
    
    # SSH (از LAN و WAN)
    _iptables("filter", "-A", "INPUT", "-p", "tcp", "--dport", "22", "-j", "ACCEPT")
    
    # WAN — L2TP/IPsec
    if wan:
        for port in ("500", "4500", "1701"):
            _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "udp",
                      "--dport", port, "-j", "ACCEPT")
        # ICMP از WAN
        _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "icmp", "-j", "ACCEPT")
    
    # PPP — IPsec
    for port in ("500", "4500"):
        _iptables("filter", "-A", "INPUT", "-i", "ppp+", "-p", "udp",
                  "--dport", port, "-j", "ACCEPT")
    
    # ─── EXTRA_PORTS (از config) ───
    extra = cfg.get("EXTRA_PORTS", "")
    if extra:
        for port in str(extra).split(","):
            port = port.strip()
            if not port:
                continue
            if wan:
                _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "tcp",
                          "--dport", port, "-j", "ACCEPT")
                _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "udp",
                          "--dport", port, "-j", "ACCEPT")
            for iface in _ifaces_lan():
                if not network.iface_exists(iface):
                    continue
                _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                          "--dport", port, "-j", "ACCEPT")
                _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "udp",
                          "--dport", port, "-j", "ACCEPT")
        log.info(f"extra ports: {extra}")
    
    # ─── EXTRA_PORTS (از config) ───
    extra = cfg.get("EXTRA_PORTS", "")
    if extra:
        for port in str(extra).split(","):
            port = port.strip()
            if not port:
                continue
            # WAN
            if wan:
                _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "tcp",
                          "--dport", port, "-j", "ACCEPT")
                _iptables("filter", "-A", "INPUT", "-i", wan, "-p", "udp",
                          "--dport", port, "-j", "ACCEPT")
            # LAN
            for iface in _ifaces_lan():
                if not network.iface_exists(iface):
                    continue
                _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                          "--dport", port, "-j", "ACCEPT")
                _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "udp",
                          "--dport", port, "-j", "ACCEPT")
        log.info(f"extra ports: {extra}")
    
    # LAN interfaces
    for iface in _ifaces_lan():
        if not network.iface_exists(iface):
            continue
        
        # DHCP
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "udp",
                  "--dport", "67", "-j", "ACCEPT")
        # DNS
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "udp",
                  "--dport", "53", "-j", "ACCEPT")
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                  "--dport", "53", "-j", "ACCEPT")
        # Portal
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                  "--dport", str(portal_port), "-j", "ACCEPT")
        # HTTP (redirect از nat)
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                  "--dport", "80", "-j", "ACCEPT")
        # Admin
        if admin_enabled:
            _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "tcp",
                      "--dport", str(admin_port), "-j", "ACCEPT")
        # ICMP
        _iptables("filter", "-A", "INPUT", "-i", iface, "-p", "icmp", "-j", "ACCEPT")
    
    # ─── FORWARD ───
    for iface in _ifaces_lan():
        if not network.iface_exists(iface):
            continue
        
        # کاربر مجاز → ppp
        _iptables("filter", "-A", "FORWARD", "-i", iface, "-o", "ppp+",
                  "-m", "set", "--match-set", ipset_name, "src", "-j", "ACCEPT")
        # برگشت
        _iptables("filter", "-A", "FORWARD", "-i", "ppp+", "-o", iface,
                  "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT")
    
    # ─── final DROP ───
    _iptables("filter", "-A", "INPUT", "-j", "DROP")
    _iptables("filter", "-A", "FORWARD", "-j", "DROP")
    
    log.info("filter table configured")


# ════════════════════════════════════════════════════════════
# NAT (PREROUTING + POSTROUTING)
# ════════════════════════════════════════════════════════════

def setup_nat(cfg: dict):
    """nat table: PREROUTING + POSTROUTING"""
    _flush_chain("nat", "PREROUTING")
    _flush_chain("nat", "POSTROUTING")
    
    portal_port = cfg.get("PORTAL_PORT", 8080)
    ipset_name = cfg.get("IPSET_NAME", "authorized_clients")
    masquerade = cfg.get("MASQUERADE_ENABLED", True)
    
    # ─── PREROUTING: redirect به پورتال ───
    for iface in _ifaces_lan():
        if not network.iface_exists(iface):
            continue
        
        # HTTP → portal (اگه IP تو ipset نباشه)
        _iptables("nat", "-A", "PREROUTING", "-i", iface, "-p", "tcp",
                  "--dport", "80",
                  "-m", "set", "!", "--match-set", ipset_name, "src",
                  "-j", "REDIRECT", "--to-port", str(portal_port))
    
    # ─── POSTROUTING: MASQUERADE ───
    if masquerade:
        _iptables("nat", "-A", "POSTROUTING", "-o", "ppp+", "-j", "MASQUERADE")
    
    log.info("nat table configured")


# ════════════════════════════════════════════════════════════
# Mangle (mark برای policy routing)
# ════════════════════════════════════════════════════════════

def setup_mangle(cfg: dict):
    """mangle table: mark برای policy routing"""
    _flush_chain("mangle", "PREROUTING")
    _flush_chain("mangle", "OUTPUT")
    _flush_chain("mangle", "FORWARD")
    
    mark = int(cfg.get("FW_MARK", 100))
    
    # ─── PREROUTING: mark ترافیک LAN ───
    for iface in _ifaces_lan():
        if not network.iface_exists(iface):
            continue
        
        net = _get_iface_network(iface)
        if net:
            # ترافیک از LAN به غیر LAN → mark
            _iptables("mangle", "-A", "PREROUTING", "-i", iface,
                      "-s", net, "!", "-d", net,
                      "-j", "MARK", "--set-mark", str(mark))
        
        # DNS → mark
        _iptables("mangle", "-A", "PREROUTING", "-i", iface, "-p", "udp",
                  "--dport", "53", "-j", "MARK", "--set-mark", str(mark))
        _iptables("mangle", "-A", "PREROUTING", "-i", iface, "-p", "tcp",
                  "--dport", "53", "-j", "MARK", "--set-mark", str(mark))
    
    # ─── OUTPUT: mark DNS خود سرور ───
    _iptables("mangle", "-A", "OUTPUT", "-m", "owner",
              "--uid-owner", "dnsmasq", "-p", "udp", "--dport", "53",
              "-j", "MARK", "--set-mark", str(mark))
    _iptables("mangle", "-A", "OUTPUT", "-m", "owner",
              "--uid-owner", "dnsmasq", "-p", "tcp", "--dport", "53",
              "-j", "MARK", "--set-mark", str(mark))
    
    log.info("mangle table configured")


# ════════════════════════════════════════════════════════════
# MSS Clamping
# ════════════════════════════════════════════════════════════

def setup_mss_clamping(cfg: dict):
    """TCPMSS clamp برای ppp"""
    # حذف قبلی
    _iptables("mangle", "-D", "FORWARD", "-o", "ppp+", "-p", "tcp",
              "--tcp-flags", "SYN,RST", "SYN",
              "-j", "TCPMSS", "--clamp-mss-to-pmtu")
    _iptables("mangle", "-D", "FORWARD", "-i", "ppp+", "-p", "tcp",
              "--tcp-flags", "SYN,RST", "SYN",
              "-j", "TCPMSS", "--clamp-mss-to-pmtu")
    
    # اضافه
    _iptables("mangle", "-A", "FORWARD", "-o", "ppp+", "-p", "tcp",
              "--tcp-flags", "SYN,RST", "SYN",
              "-j", "TCPMSS", "--clamp-mss-to-pmtu")
    _iptables("mangle", "-A", "FORWARD", "-i", "ppp+", "-p", "tcp",
              "--tcp-flags", "SYN,RST", "SYN",
              "-j", "TCPMSS", "--clamp-mss-to-pmtu")
    
    log.info("MSS clamping configured")


# ════════════════════════════════════════════════════════════
# Setup All
# ════════════════════════════════════════════════════════════

def setup_all(cfg: Optional[dict] = None) -> bool:
    """راه‌اندازی کامل iptables"""
    if cfg is None:
        cfg = config.all()
    
    log.info("setting up firewall...")
    
    try:
        flush_all()
        setup_filter(cfg)
        setup_nat(cfg)
        setup_mangle(cfg)
        setup_mss_clamping(cfg)
        save(cfg)
        log.info("firewall setup complete")
        return True
    except Exception as e:
        log.error(f"firewall setup failed: {e}")
        return False


# ════════════════════════════════════════════════════════════
# Save / Restore
# ════════════════════════════════════════════════════════════

def save(cfg: Optional[dict] = None):
    """iptables-save > file"""
    if cfg is None:
        cfg = config.all()
    
    path = cfg.get("IPTABLES_RULES_FILE", "/etc/iptables/rules.v4")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    r = _run(["iptables-save"])
    if r.returncode == 0:
        with open(path, "w") as f:
            f.write(r.stdout)
        log.info(f"saved iptables to {path}")
        return True
    return False


def restore(cfg: Optional[dict] = None) -> bool:
    """iptables-restore < file"""
    if cfg is None:
        cfg = config.all()
    
    path = cfg.get("IPTABLES_RULES_FILE", "/etc/iptables/rules.v4")
    if not os.path.exists(path):
        return False
    
    with open(path) as f:
        r = _run(["iptables-restore"], timeout=10)
        # stdin
        r = subprocess.run(
            ["iptables-restore"],
            stdin=f,
            capture_output=True, text=True, timeout=10,
        )
    
    if r.returncode == 0:
        log.info(f"restored iptables from {path}")
        return True
    return False
