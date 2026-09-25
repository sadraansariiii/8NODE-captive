#!/usr/bin/env python3
"""
l2tp_watchdog.py - نگهبان تونل L2TP
======================================
هر ۳۰ ثانیه PPP رو چک می‌کنه
- اگه IPsec نبود → up
- اگه PPP نبود → reconnect
- با ipsec قدیم کار می‌کنه (نه swanctl)
"""
import os
import sys
import time
import subprocess

sys.path.insert(0, "/opt/captive-portal")
sys.path.insert(0, "/opt/captive-portal-src")

from lib import config, logger, network, route

log = logger.get("l2tp_watchdog")

CHECK_INTERVAL = 30


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _run(args, timeout=30):
    """اجرای command"""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", "not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _has_swanctl() -> bool:
    return (os.path.exists("/usr/sbin/swanctl") or
            os.path.exists("/usr/bin/swanctl"))


def _has_ipsec() -> bool:
    return (os.path.exists("/usr/sbin/ipsec") or
            os.path.exists("/usr/bin/ipsec"))


def _ppp_exists():
    """آیا PPP داریم؟"""
    for iface in network.list_ifaces():
        if iface.startswith("ppp"):
            r = _run(["ip", "link", "show", iface])
            if "UP" in r.stdout:
                return iface
    return None


def _ipsec_established():
    """آیا IPsec SA هست؟"""
    # swanctl
    if _has_swanctl():
        r = _run(["swanctl", "--list-sas"])
        if r.returncode == 0 and "ESTABLISHED" in r.stdout:
            return True
    # ipsec
    if _has_ipsec():
        r = _run(["ipsec", "status"])
        if "ESTABLISHED" in r.stdout:
            return True
    return False


def _ipsec_child_installed():
    """آیا CHILD_SA INSTALLED هست؟"""
    if _has_swanctl():
        r = _run(["swanctl", "--list-sas"])
        if "INSTALLED" in r.stdout:
            return True
    if _has_ipsec():
        r = _run(["ipsec", "status"])
        if "INSTALLED" in r.stdout:
            return True
    return False


def _cleanup_ppp():
    """حذف PPP های مرده"""
    for iface in list(network.list_ifaces()):
        if iface.startswith("ppp"):
            r = _run(["ip", "link", "show", iface])
            if "UP" not in r.stdout:
                _run(["ip", "link", "delete", iface])
                log.info(f"deleted dead {iface}")


def _initiate_ipsec(cfg):
    """IPsec رو up کن"""
    log.info("initiating IPsec...")
    
    l2tp_server = cfg.get("L2TP_SERVER", "")
    
    if _has_swanctl():
        _run(["swanctl", "--load-all"])
        time.sleep(1)
        _run(["swanctl", "--initiate", "--child", "L2TP-PSK-child"])
    elif _has_ipsec():
        # اول down کن اگه هست
        _run(["ipsec", "down", "L2TP-PSK"])
        time.sleep(1)
        _run(["ipsec", "up", "L2TP-PSK"])
    
    time.sleep(5)


def _start_tunnel(cfg):
    """راه‌اندازی کامل تونل"""
    log.info("restarting tunnel...")
    
    # ۱. route به L2TP
    route.add_l2tp_route(cfg)
    
    # ۲. IPsec
    if not _ipsec_established() or not _ipsec_child_installed():
        _initiate_ipsec(cfg)
    
    # ۳. پاک‌سازی PPP
    _cleanup_ppp()
    _run(["pkill", "-9", "pppd"])
    time.sleep(2)
    
    # ۴. restart xl2tpd
    _run(["systemctl", "restart", "xl2tpd"])
    time.sleep(3)
    
    # ۵. connect
    lac = cfg.get("L2TP_LAC_NAME", "l2tp")
    control = "/var/run/xl2tpd/l2tp-control"
    os.makedirs(os.path.dirname(control), exist_ok=True)
    
    try:
        with open(control, "w") as f:
            f.write(f"c {lac}\n")
        log.info(f"sent 'c {lac}'")
    except Exception as e:
        log.error(f"cannot write {control}: {e}")
    
    time.sleep(12)
    
    # ۶. چک
    ppp = _ppp_exists()
    if ppp:
        log.info(f"✅ PPP up: {ppp}")
    else:
        log.warning("❌ PPP not up after reconnect")
    
    # ۷. routing
    route.setup_ppp_table(cfg)


# ════════════════════════════════════════════════════════════
# Main Loop
# ════════════════════════════════════════════════════════════

def main():
    log.info("l2tp-watchdog starting...")
    
    while True:
        try:
            config.reload()
            cfg = config.load()
            
            ppp = _ppp_exists()
            
            if not ppp:
                log.warning("PPP down, reconnecting...")
                _start_tunnel(cfg)
            else:
                # چک IPsec CHILD_SA
                if not _ipsec_child_installed():
                    log.warning("CHILD_SA missing, re-initiating IPsec...")
                    _initiate_ipsec(cfg)
                    route.setup_ppp_table(cfg)
                else:
                    log.debug(f"PPP OK: {ppp}")
        except Exception as e:
            log.error(f"watchdog error: {e}")
            import traceback
            log.error(traceback.format_exc())
        
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
