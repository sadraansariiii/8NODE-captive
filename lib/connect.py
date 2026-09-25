#!/usr/bin/env python3
"""
connect.py - Connect Logic
============================
منطق connect کاربر:
- حل username conflict
- API connect
- ipset/tc اعمال
"""
import time
from typing import Optional, Tuple

from . import config, logger, sessions, ipset, tc, api, network
from . import disconnect

log = logger.get("connect")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _get_used(ip: str, session: dict) -> int:
    """مصرف = accumulated + (current - baseline)"""
    try:
        accumulated = int(session.get("accumulated_bytes", 0) or 0)
        baseline = int(session.get("baseline_bytes", 0) or 0)
        current = tc.get_bytes(ip)
        if current < baseline:
            current = baseline
        return accumulated + max(0, current - baseline)
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════
# Connect
# ════════════════════════════════════════════════════════════

def do_connect(ip: str, username: str,
                mac: Optional[str] = None,
                cfg: Optional[dict] = None) -> bool:
    """
    connect کاربر
    """
    if cfg is None:
        cfg = config.all()
    
    iface = network.get_iface_for_ip(ip)
    
    # ─── ۱. حل username conflict ───
    old_ip = sessions.find_by_username(username, exclude_ip=ip)
    if old_ip:
        log.info(f"username conflict: {username} {old_ip} → {ip}")
        disconnect.do_disconnect(None, old_ip, "username_replaced", cfg)
    
    # ─── ۲. tc.remove پیش‌دستانه ───
    try:
        tc.remove(ip)
    except Exception as e:
        log.warning(f"tc.remove({ip}) failed: {e}")
    
    # ─── ۳. API connect ───
    time_left, quota, bw = api.connect(username, ip)
    
    # ─── ۴. session (self load/save) ───
    sessions.on_connect(
        ip, username,
        mac=mac,
        iface=iface,
        time_left=time_left,
        quota=quota,
        bw=bw,
    )
    
    # ─── ۵. ipset ───
    if time_left is not None and int(time_left) > 0:
        ipset.add(ip, timeout=int(time_left))
    else:
        default = int(cfg.get("IPSET_TIMEOUT_DEFAULT", 86400))
        ipset.add(ip, timeout=default)
    
    # ─── ۶. tc.apply_bw ───
    if bw is not None and int(bw) > 0:
        try:
            tc.apply_bw(ip, int(bw), iface)
        except Exception as e:
            log.warning(f"tc.apply_bw({ip}) failed: {e}")
    
    log.info(f"CONNECT {ip} user={username} time={time_left} quota={quota} bw={bw}")
    return True


# ════════════════════════════════════════════════════════════
# Run
# ════════════════════════════════════════════════════════════

def do_run(ip: str, cfg: Optional[dict] = None) -> bool:
    """ارسال run event — فقط time_left و quota"""
    if cfg is None:
        cfg = config.all()
    
    session = sessions.get(ip)
    if not session:
        return False
    
    username = session.get("username", "unknown")
    sessions.update_used_bytes(ip)
    total_used = sessions.get_used_bytes(ip)
    
    time_left, quota, bw = api.run(username, ip, down=total_used, up=0)
    
    updates = {"last_run_report": time.time()}
    
    if time_left is not None:
        updates["server_time_left"] = int(time_left)
        try:
            ipset.renew(ip, int(time_left))
        except Exception:
            pass
    
    if quota is not None:
        updates["quota_mb"] = quota
    
    sessions.update(ip, **updates)
    
    log.debug(f"RUN {ip} used={total_used} time={time_left} quota={quota}")
    return True


def do_sleep(ip: str, cfg: Optional[dict] = None) -> bool:
    """قطع موقت (sleep)"""
    if cfg is None:
        cfg = config.all()
    
    session = sessions.get(ip)
    if not session:
        return False
    
    username = session.get("username", "unknown")
    total_used = _get_used(ip, session)
    
    try:
        api.sleep(username, ip, down=total_used, up=0)
    except Exception as e:
        log.error(f"API sleep failed for {ip}: {e}")
    
    # لاگ
    _log_usage(username, ip, total_used, "sleep")
    
    sessions.update(ip,
                    state="sleep",
                    sleep_since=time.time())
    
    log.info(f"SLEEP {ip} user={username} used={total_used}")
    return True


def _log_usage(username: str, ip: str, total_bytes: int, tag: str):
    from datetime import datetime
    import os
    log_dir = config.get("USAGE_LOG_DIR", "/var/log/captive-usage")
    os.makedirs(log_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    logfile = os.path.join(log_dir, f"usage-{today}.txt")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(logfile, "a") as f:
            f.write(f"{ts} | IP={ip} | user={username} | bytes={total_bytes} | event={tag}\n")
    except Exception as e:
        log.warning(f"cannot write usage log: {e}")


# ════════════════════════════════════════════════════════════
# High-level
# ════════════════════════════════════════════════════════════

def handle_connect_request(ip: str, username: str,
                             mac: Optional[str] = None,
                             cfg: Optional[dict] = None) -> bool:
    """نقطه ورود از session_monitor"""
    return do_connect(ip, username, mac=mac, cfg=cfg)
