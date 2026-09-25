#!/usr/bin/env python3
"""
portal_watchdog.py - نگهبان پورتال
=====================================
هر ۲ دقیقه سلامت سیستم رو چک می‌کنه
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import config, logger, network, ipset, api

log = logger.get("portal_watchdog")

CHECK_INTERVAL = 120


def _run(args, timeout=10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _check_ipset():
    """ipset سالمه؟"""
    if not ipset.exists_set():
        return False, "ipset not exists"
    return True, ""


def _check_route():
    """route table 100 سالمه؟"""
    cfg = config.all()
    table_id = cfg.get("RT_TABLE_ID", 100)
    r = _run(["ip", "route", "show", "table", str(table_id)])
    if r and "default" in r.stdout:
        return True, ""
    return False, "table 100 empty"


def _check_services():
    """سرویس‌ها فعالن؟"""
    services = ["captive-portal", "session-monitor", "dnsmasq"]
    issues = []
    for svc in services:
        r = _run(["systemctl", "is-active", svc])
        if r is None:
            continue
        if r.stdout.strip() != "active":
            issues.append(svc)
    return issues


def _check_api():
    """API جواب می‌ده؟"""
    return api.is_alive()


def check_all():
    """چک همه چیز"""
    issues = []
    
    ok, msg = _check_ipset()
    if not ok:
        issues.append(f"ipset: {msg}")
    
    ok, msg = _check_route()
    if not ok:
        issues.append(f"route: {msg}")
    
    svc_issues = _check_services()
    for s in svc_issues:
        issues.append(f"service {s} not active")
    
    if not _check_api():
        issues.append("API not responding")
    
    return issues


def main():
    log.info("portal-watchdog starting...")
    
    fail_count = 0
    
    while True:
        try:
            issues = check_all()
            
            if issues:
                fail_count += 1
                log.warning(f"issues found ({fail_count}): {'; '.join(issues)}")
                
                # بعد از ۲ بار پشت سر هم، reload کن
                if fail_count >= 2:
                    log.warning("running reload...")
                    r = _run(["cp-reload"], timeout=120)
                    if r:
                        log.info(f"reload exit code: {r.returncode}")
                    fail_count = 0
            else:
                if fail_count > 0:
                    log.info("all OK now")
                fail_count = 0
                log.debug("all OK")
        except Exception as e:
            log.error(f"watchdog error: {e}")
        
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
