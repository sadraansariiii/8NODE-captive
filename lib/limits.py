#!/usr/bin/env python3
"""
limits.py - Check Limits
==========================
چک محدودیت‌های کاربر:
- زمان (time_left)
- ترافیک (quota_mb)
- sleep_timeout
"""
import time
from typing import Optional

from . import config, logger, sessions, tc
from . import disconnect

log = logger.get("limits")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _get_used_mb(ip: str, session: dict) -> float:
    """مصرف به MB"""
    try:
        accumulated = int(session.get("accumulated_bytes", 0) or 0)
        baseline = int(session.get("baseline_bytes", 0) or 0)
        current = tc.get_bytes(ip)
        if current < baseline:
            current = baseline
        total_bytes = accumulated + max(0, current - baseline)
        return total_bytes / (1024 * 1024)
    except Exception:
        return 0.0


# ════════════════════════════════════════════════════════════
# Checks
# ════════════════════════════════════════════════════════════

def check_time(ip: str, session: dict) -> bool:
    """
    آیا زمان تموم شده؟
    Returns: True اگه time_left <= 0
    """
    time_left = session.get("server_time_left")
    if time_left is None:
        return False
    try:
        return int(time_left) <= 0
    except (TypeError, ValueError):
        return False


def check_quota(ip: str, session: dict) -> bool:
    """
    آیا quota exceeded شده؟
    Returns: True اگه used >= quota
    """
    quota = session.get("quota_mb")
    if quota is None:
        return False
    try:
        quota_f = float(quota)
        if quota_f <= 0:
            return False
        used_mb = _get_used_mb(ip, session)
        return used_mb >= quota_f
    except (TypeError, ValueError):
        return False


def check_sleep_timeout(ip: str, session: dict, cfg: Optional[dict] = None) -> bool:
    """
    آیا sleep خیلی طول کشیده؟
    Returns: True اگه sleep_since + SLEEP_GRACE_SECONDS < now
    """
    if session.get("state") != "sleep":
        return False
    
    sleep_since = session.get("sleep_since")
    if sleep_since is None:
        return False
    
    if cfg is None:
        cfg = config.all()
    
    grace = int(cfg.get("SLEEP_GRACE_SECONDS", 3600))
    elapsed = time.time() - float(sleep_since)
    return elapsed >= grace


def check_run_timeout(ip: str, session: dict, cfg: Optional[dict] = None) -> bool:
    """
    آیا run خیلی طول کشیده (گزارش نرفته)؟
    Returns: True اگه last_run_report قدیمیه
    """
    if session.get("state") != "connect":
        return False
    
    last_run = session.get("last_run_report", 0)
    if not last_run:
        return False
    
    if cfg is None:
        cfg = config.all()
    
    interval = int(cfg.get("RUN_INTERVAL", 600))
    # اگه ۳ برابر interval گذشته و run نرفته → timeout
    return (time.time() - float(last_run)) >= (interval * 3)


# ════════════════════════════════════════════════════════════
# Main Check
# ════════════════════════════════════════════════════════════

def check(ip: str, cfg: Optional[dict] = None) -> bool:
    """
    چک همه محدودیت‌ها
    Returns:
        True: کاربر OK
        False: کاربر قطع شد
    """
    if cfg is None:
        cfg = config.all()
    
    session = sessions.get(ip)
    if not session:
        return True  # session نیست، مشکلی نیست
    
    # ─── زمان ───
    if check_time(ip, session):
        log.info(f"{ip} time expired")
        disconnect.do_disconnect(None, ip, "time_expired", cfg)
        return False
    
    # ─── quota ───
    if check_quota(ip, session):
        log.info(f"{ip} quota exceeded")
        disconnect.do_disconnect(None, ip, "quota_exceeded", cfg)
        return False
    
    # ─── sleep timeout ───
    if check_sleep_timeout(ip, session, cfg):
        log.info(f"{ip} sleep timeout")
        disconnect.do_disconnect(None, ip, "sleep_timeout", cfg)
        return False
    
    # ─── run timeout ───
    if check_run_timeout(ip, session, cfg):
        log.warning(f"{ip} run timeout (last report too old)")
        # فعلاً فقط لاگ، نه disconnect
        # disconnect.do_disconnect(None, ip, "run_timeout", cfg)
        # return False
    
    return True


# ════════════════════════════════════════════════════════════
# Check All
# ════════════════════════════════════════════════════════════

def check_all(cfg: Optional[dict] = None) -> int:
    """
    چک همه session ها
    Returns: تعداد کاربرای قطع‌شده
    """
    if cfg is None:
        cfg = config.all()
    
    count = 0
    for ip in sessions.all_ips():
        if not check(ip, cfg):
            count += 1
    return count


# ════════════════════════════════════════════════════════════
# Helpers for UI
# ════════════════════════════════════════════════════════════

def get_time_left(ip: str) -> Optional[int]:
    """time_left"""
    return sessions.get_time_left(ip)

def get_quota(ip: str) -> Optional[int]:
    """quota"""
    return sessions.get_quota(ip)

def get_used_mb(ip: str) -> float:
    """مصرف MB — از session خونده می‌شه"""
    used = sessions.get_used_bytes(ip)
    return round(used / (1024 * 1024), 2)

def get_quota_percent(ip: str) -> Optional[float]:
    """درصد مصرف از quota"""
    quota = get_quota(ip)
    if not quota or quota <= 0:
        return None
    used = get_used_mb(ip)
    return min(100.0, (used / float(quota)) * 100.0)
