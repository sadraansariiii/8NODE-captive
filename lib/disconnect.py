#!/usr/bin/env python3
"""
disconnect.py - Disconnect Logic
==================================
قلب سیستم: disconnect کاربر
"""
import os
import time
from datetime import datetime
from typing import Optional

from . import config, logger, sessions, ipset, tc, api

log = logger.get("disconnect")


# ════════════════════════════════════════════════════════════
# Usage Log
# ════════════════════════════════════════════════════════════

def _log_usage(username: str, ip: str, total_bytes: int, tag: str):
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
# Helpers
# ════════════════════════════════════════════════════════════

def _get_used(ip: str, session: dict) -> int:
    """مصرف از session خونده می‌شه"""
    try:
        return int(session.get("used_bytes", 0) or 0)
    except Exception:
        return 0


def _cleanup(ip: str):
    """پاک‌سازی ipset و tc"""
    try:
        ipset.remove(ip)
    except Exception as e:
        log.warning(f"ipset.remove({ip}) failed: {e}")
    try:
        tc.remove(ip)
    except Exception as e:
        log.warning(f"tc.remove({ip}) failed: {e}")


# ════════════════════════════════════════════════════════════
# Disconnect
# ════════════════════════════════════════════════════════════

def do_disconnect(sess: Optional[dict], ip: str, reason: str = "normal",
                   cfg: Optional[dict] = None) -> bool:
    """قطع کامل کاربر"""
    if cfg is None:
        cfg = config.all()
    
    # session
    if sess is None:
        sess = sessions.load()
    
    session = sess.get(ip)
    if not session:
        log.debug(f"disconnect: no session for {ip}")
        _cleanup(ip)
        return False
    
    username = session.get("username", "unknown")
    
    # مصرف
    total_used = _get_used(ip, session)
    
    # API disconnect
    try:
        api.disconnect(username, ip, down=total_used, up=0)
    except Exception as e:
        log.error(f"API disconnect failed for {ip}: {e}")
    
    # لاگ
    _log_usage(username, ip, total_used, f"disconnect:{reason}")
    
    # پاک‌سازی
    _cleanup(ip)
    
    # حذف session
    if ip in sess:
        del sess[ip]
        sessions.save(sess)
    
    log.info(f"DISCONNECT {ip} user={username} reason={reason} used={total_used}")
    return True


# ════════════════════════════════════════════════════════════
# Sleep
# ════════════════════════════════════════════════════════════

def do_sleep(sess: dict, ip: str, cfg: Optional[dict] = None) -> bool:
    """قطع موقت — فقط time_left و quota"""
    if cfg is None:
        cfg = config.all()
    
    session = sess.get(ip)
    if not session:
        return False
    
    username = session.get("username", "unknown")
    total_used = _get_used(ip, session)
    
    try:
        time_left, quota, bw = api.sleep(username, ip, down=total_used, up=0)
    except Exception as e:
        log.error(f"API sleep failed for {ip}: {e}")
        time_left, quota, bw = None, None, None
    
    _log_usage(username, ip, total_used, "sleep")
    
    session["state"] = "sleep"
    session["sleep_since"] = time.time()
    
    if time_left is not None:
        try:
            session["server_time_left"] = int(time_left)
        except (TypeError, ValueError):
            pass
    
    if quota is not None:
        session["quota_mb"] = quota
    
    sessions.save(sess)
    
    log.info(f"SLEEP {ip} user={username} used={total_used}")
    return True


def disconnect_by_username(username: str, reason: str = "normal") -> bool:
    sess = sessions.load()
    for ip, s in list(sess.items()):
        if s.get("username") == username:
            return do_disconnect(sess, ip, reason)
    return False


def disconnect_all(reason: str = "normal") -> int:
    sess = sessions.load()
    count = 0
    for ip in list(sess.keys()):
        if do_disconnect(sess, ip, reason):
            count += 1
    return count
