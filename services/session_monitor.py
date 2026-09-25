#!/usr/bin/env python3
"""
session_monitor.py - Session Monitor Service
==============================================
حلقه اصلی:
- چک ARP
- limits
- connect/sleep
- run
- renew ipset
"""
import os
import sys
import time
from datetime import datetime

# اضافه کردن مسیر library
sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import (
    config, logger, sessions, ipset, tc,
    network, api, connect, disconnect, limits
)

log = logger.get("session_monitor")


# ════════════════════════════════════════════════════════════
# Config Helpers
# ════════════════════════════════════════════════════════════

def _get_cfg() -> dict:
    """گرفتن config (reload هر بار)"""
    config.reload()
    return config.load()


def _get_check_interval(cfg: dict) -> int:
    return int(cfg.get("CHECK_INTERVAL", 15))


def _get_run_interval(cfg: dict) -> int:
    return int(cfg.get("RUN_INTERVAL", 600))


def _get_ips_renew_threshold(cfg: dict) -> int:
    return int(cfg.get("IPSET_RENEW_THRESHOLD", 120))


# ════════════════════════════════════════════════════════════
# MAC Tracking
# ════════════════════════════════════════════════════════════

def track_mac_changes(cfg: dict):
    """
    اگه MAC یه کاربر IP جدید گرفته، session رو منتقل کن
    """
    sess = sessions.load()
    leases = {l["ip"]: l["mac"] for l in network.get_all_leases()}
    
    # ip → mac از leases
    mac_to_ip = {mac: ip for ip, mac in leases.items()}
    
    for ip in list(sess.keys()):
        session = sess.get(ip)
        if not session:
            continue
        
        mac = session.get("mac")
        if not mac:
            continue
        
        # اگه IP فعلی تو leases نیست، ولی MAC هست
        if ip not in leases:
            new_ip = mac_to_ip.get(mac)
            if new_ip and new_ip != ip:
                log.info(f"MAC track: {mac} {ip} → {new_ip}")
                sessions.on_ip_change(
                    session.get("username", "unknown"),
                    ip, new_ip
                )


# ════════════════════════════════════════════════════════════
# ARP Processing
# ════════════════════════════════════════════════════════════

def process_arp(ip: str, arp_state: str, cfg: dict):
    """
    پردازش ARP state برای یه IP
    """
    session = sessions.get(ip)
    if not session:
        return
    
    state = session.get("state", "unknown")
    username = session.get("username", "unknown")
    
    # ─── REACHABLE ───
    if network.is_reachable(arp_state):
        if state != "connect":
            log.info(f"{ip} ARP={arp_state} state={state} → connect")
            connect.do_connect(ip, username, mac=session.get("mac"), cfg=cfg)
    
    # ─── FAILED ───
    elif network.is_failed(arp_state):
        if state == "connect":
            log.info(f"{ip} ARP=FAILED state={state} → sleep")
            connect.do_sleep(ip, cfg=cfg)


# ════════════════════════════════════════════════════════════
# Run Reports
# ════════════════════════════════════════════════════════════

def process_runs(cfg: dict):
    """
    ارسال run برای session هایی که زمانش رسیده
    """
    run_interval = _get_run_interval(cfg)
    now = time.time()
    
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        
        if session.get("state") != "connect":
            continue
        
        last_run = session.get("last_run_report", 0)
        if not last_run:
            continue
        
        if now - float(last_run) >= run_interval:
            try:
                connect.do_run(ip, cfg=cfg)
            except Exception as e:
                log.error(f"run failed for {ip}: {e}")


# ════════════════════════════════════════════════════════════
# ipset Renew
# ════════════════════════════════════════════════════════════

def process_ipset_renew(cfg: dict):
    """
    renew ipset برای کاربرایی که timeout کم دارن
    """
    threshold = _get_ips_renew_threshold(cfg)
    
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        
        if session.get("state") != "connect":
            continue
        
        timeout_left = ipset.timeout_left(ip)
        
        # اگه timeout کمتر از threshold شد، renew کن
        if timeout_left is not None and timeout_left < threshold:
            server_time = session.get("server_time_left")
            if server_time and int(server_time) > 0:
                log.debug(f"renew ipset {ip} ({timeout_left} → {server_time})")
                ipset.renew(ip, int(server_time))
            else:
                # fallback: default
                default = int(cfg.get("IPSET_TIMEOUT_DEFAULT", 86400))
                ipset.renew(ip, default)


# ════════════════════════════════════════════════════════════
# Decrement Time
# ════════════════════════════════════════════════════════════

def process_time_decrement(cfg: dict):
    """
    کم کردن time_left برای session های connect
    """
    check_interval = _get_check_interval(cfg)
    
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        
        if session.get("state") != "connect":
            continue
        
        time_left = session.get("server_time_left")
        if time_left is None:
            continue
        
        try:
            new_val = max(0, int(time_left) - check_interval)
            sessions.set_field(ip, "server_time_left", new_val)
        except (TypeError, ValueError):
            pass


# ════════════════════════════════════════════════════════════
# Limits Check
# ════════════════════════════════════════════════════════════

def process_limits(cfg: dict):
    """
    چک محدودیت‌های کاربرا
    """
    for ip in list(sessions.all_ips()):
        try:
            limits.check(ip, cfg=cfg)
        except Exception as e:
            log.error(f"limits check failed for {ip}: {e}")




# ════════════════════════════════════════════════════════════
# Used Bytes Update
# ════════════════════════════════════════════════════════════

def process_used_bytes(cfg: dict):
    """هر loop: used_bytes رو از tc محاسبه کن و تو session ذخیره کن"""
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        if session.get("state") != "connect":
            continue
        try:
            sessions.update_used_bytes(ip)
        except Exception as e:
            log.error(f"update_used_bytes failed for {ip}: {e}")




def process_orphans(cfg: dict):
    """پاک‌سازی IP هایی که تو ipset هستن ولی session ندارن"""
    from lib import ipset, tc
    
    session_ips = set(sessions.all_ips())
    ipset_ips = set(ipset.list_ips())
    
    orphans = ipset_ips - session_ips
    for ip in orphans:
        log.warning(f"orphan in ipset: {ip}, cleaning...")
        ipset.remove(ip)
        tc.remove(ip)


# ════════════════════════════════════════════════════════════
# Main Loop
# ════════════════════════════════════════════════════════════

def run_once(cfg: dict):
    """یه دور کامل loop"""
    # ۱. MAC tracking
    try:
        track_mac_changes(cfg)
    except Exception as e:
        log.error(f"mac track failed: {e}")
    
    # ۲. limits
    process_limits(cfg)
    
    # ۳. ipset renew
    process_ipset_renew(cfg)
    
    # ۴. time decrement
    process_time_decrement(cfg)
    
    # ۵. ARP check
    try:
        lan_ifaces = []
        if cfg.get("LAN_IFACE"):
            lan_ifaces.append(cfg["LAN_IFACE"])
        if cfg.get("WLX_IFACE"):
            lan_ifaces.append(cfg["WLX_IFACE"])
        
        arp = network.get_arp_status(lan_ifaces)
        
        for ip in sessions.all_ips():
            state = arp.get(ip, "UNKNOWN")
            process_arp(ip, state, cfg)
    except Exception as e:
        log.error(f"arp processing failed: {e}")
    
    # ۶. used_bytes (از tc)
    try:
        process_used_bytes(cfg)
    except Exception as e:
        log.error(f"used_bytes processing failed: {e}")
    
    # ۷. run reports
    try:
        process_runs(cfg)
    except Exception as e:
        log.error(f"run processing failed: {e}")


def main():
    """حلقه اصلی"""
    log.info("session-monitor starting...")
    
    cfg = _get_cfg()
    interval = _get_check_interval(cfg)
    
    log.info(f"check_interval={interval}s")
    log.info(f"run_interval={_get_run_interval(cfg)}s")
    log.info(f"LAN_IFACE={cfg.get('LAN_IFACE')}")
    log.info(f"WLX_IFACE={cfg.get('WLX_IFACE')}")
    
    while True:
        try:
            cfg = _get_cfg()  # reload هر بار
            run_once(cfg)
        except Exception as e:
            log.error(f"loop error: {e}")
            import traceback
            log.error(traceback.format_exc())
        
        time.sleep(interval)


if __name__ == "__main__":
    main()
