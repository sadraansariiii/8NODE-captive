#!/usr/bin/env python3
"""
sessions.py - SessionManager
==============================
تنها منبع حقیقت برای session کاربران.
- تنها این فایل sessions.json رو می‌خونه/می‌نویسه
- flock + atomic write
"""
import os
import json
import time
import fcntl
import tempfile
from typing import Optional, Any
from datetime import datetime

from . import config, logger

log = logger.get("sessions")


# ════════════════════════════════════════════════════════════
# File I/O
# ════════════════════════════════════════════════════════════

def _path() -> str:
    return config.get("SESSIONS_FILE", "/var/lib/captive-portal/sessions.json")


def _read() -> dict:
    path = _path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"read error: {e}")
        return {}


def _write(data: dict):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    dir_name = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, prefix=".sess.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════

def load() -> dict:
    return _read()

def save(data: dict):
    _write(data)

def reload() -> dict:
    return load()


# ════════════════════════════════════════════════════════════
# Getters
# ════════════════════════════════════════════════════════════

def get(ip: str) -> Optional[dict]:
    return load().get(ip)

def get_field(ip: str, key: str, default: Any = None) -> Any:
    s = get(ip)
    return s.get(key, default) if s else default

def get_username(ip: str, default: str = "unknown") -> str:
    return get_field(ip, "username", default)

def get_state(ip: str, default: str = "unknown") -> str:
    return get_field(ip, "state", default)

def get_mac(ip: str) -> Optional[str]:
    return get_field(ip, "mac")

def get_iface(ip: str) -> Optional[str]:
    return get_field(ip, "iface")

def get_baseline(ip: str) -> int:
    return int(get_field(ip, "baseline_bytes", 0) or 0)

def get_accumulated(ip: str) -> int:
    return int(get_field(ip, "accumulated_bytes", 0) or 0)

def get_quota(ip: str) -> Optional[int]:
    v = get_field(ip, "quota_mb")
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None

def get_bw(ip: str) -> Optional[int]:
    v = get_field(ip, "bw_kbps")
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None

def get_time_left(ip: str) -> Optional[int]:
    v = get_field(ip, "server_time_left")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def get_used_bytes(ip: str) -> int:
    """مصرف از session خونده می‌شه (نه از tc)"""
    return int(get_field(ip, "used_bytes", 0) or 0)


def set_used_bytes(ip: str, used: int):
    """ذخیره used_bytes تو session"""
    set_field(ip, "used_bytes", int(used))


def update_used_bytes(ip: str) -> int:
    """
    محاسبه مصرف از tc و ذخیره تو session
    فقط session-monitor این رو صدا می‌زنه
    """
    from . import tc
    
    session = get(ip)
    if not session:
        return 0
    
    accumulated = int(session.get("accumulated_bytes", 0) or 0)
    baseline = int(session.get("baseline_bytes", 0) or 0)
    current = tc.get_bytes(ip)
    if current < baseline:
        current = baseline
    
    used = accumulated + max(0, current - baseline)
    set_field(ip, "used_bytes", used)
    return used



def get_used_mb(ip: str) -> float:
    used = get_used_bytes(ip)
    return round(used / (1024 * 1024), 2)


def all() -> dict:
    return load()

def all_ips() -> list:
    return list(load().keys())

def count() -> int:
    return len(load())

def count_by_state(state: str) -> int:
    return sum(1 for s in load().values() if s.get("state") == state)

def exists(ip: str) -> bool:
    return ip in load()

def exists_username(username: str) -> bool:
    return find_by_username(username) is not None


def find_by_username(username: str, exclude_ip: Optional[str] = None) -> Optional[str]:
    if not username or username == "unknown":
        return None
    for ip, s in load().items():
        if exclude_ip and ip == exclude_ip:
            continue
        if s.get("username") == username:
            return ip
    return None


def find_by_mac(mac: str, exclude_ip: Optional[str] = None) -> Optional[str]:
    if not mac:
        return None
    for ip, s in load().items():
        if exclude_ip and ip == exclude_ip:
            continue
        if s.get("mac") == mac:
            return ip
    return None


# ════════════════════════════════════════════════════════════
# Setters
# ════════════════════════════════════════════════════════════

def create(ip: str, username: str, mac: Optional[str] = None,
           iface: Optional[str] = None, state: str = "pending") -> dict:
    data = load()
    now = time.time()
    session = {
        "username": username,
        "mac": mac,
        "ip": ip,
        "iface": iface,
        "state": state,
        "login_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "created_at": now,
        "last_seen": now,
        "sleep_since": None,
        "baseline_bytes": 0,
        "accumulated_bytes": 0,
        "quota_mb": None,
        "bw_kbps": None,
        "server_time_left": None,
        "last_run_report": now,
    }
    data[ip] = session
    save(data)
    log.info(f"created: {ip} user={username}")
    return session


def update(ip: str, **fields):
    data = load()
    if ip not in data:
        log.warning(f"update missing: {ip}")
        return
    data[ip].update(fields)
    save(data)


def set_field(ip: str, key: str, value: Any):
    data = load()
    if ip not in data:
        return
    data[ip][key] = value
    save(data)


def delete(ip: str) -> bool:
    data = load()
    if ip not in data:
        return False
    del data[ip]
    save(data)
    log.info(f"deleted: {ip}")
    return True


def touch(ip: str):
    data = load()
    if ip in data:
        data[ip]["last_seen"] = time.time()
        save(data)


# ════════════════════════════════════════════════════════════
# Lifecycle
# ════════════════════════════════════════════════════════════

def on_connect(ip: str, username: str,
               mac: Optional[str] = None,
               iface: Optional[str] = None,
               time_left: Optional[int] = None,
               quota: Optional[int] = None,
               bw: Optional[int] = None) -> dict:
    from . import tc
    data = load()
    now = time.time()
    
    if ip not in data:
        data[ip] = {
            "username": username,
            "mac": mac,
            "ip": ip,
            "iface": iface,
            "login_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "created_at": now,
            "accumulated_bytes": 0,
        }
    
    s = data[ip]
    s["state"] = "connect"
    s["username"] = username
    if mac: s["mac"] = mac
    if iface: s["iface"] = iface
    s["last_seen"] = now
    s["sleep_since"] = None
    s["last_run_report"] = now
    s["baseline_bytes"] = tc.get_bytes(ip)
    s["used_bytes"] = 0
    
    if time_left is not None:
        s["server_time_left"] = int(time_left)
    if quota is not None:
        s["quota_mb"] = quota
    if bw is not None:
        s["bw_kbps"] = bw
    
    save(data)
    log.info(f"on_connect: {ip} user={username}")
    return s


def on_sleep(ip: str):
    data = load()
    if ip not in data:
        return
    data[ip]["state"] = "sleep"
    data[ip]["sleep_since"] = time.time()
    save(data)
    log.info(f"on_sleep: {ip}")


def on_disconnect(ip: str, reason: str = "normal"):
    data = load()
    if ip in data:
        user = data[ip].get("username", "?")
        del data[ip]
        save(data)
        log.info(f"on_disconnect: {ip} user={user} reason={reason}")


def on_ip_change(username: str, old_ip: str, new_ip: str) -> bool:
    from . import tc
    data = load()
    if old_ip not in data:
        return False
    
    old = data.pop(old_ip)
    old_used = max(0, tc.get_bytes(old_ip) - old.get("baseline_bytes", 0))
    
    old["ip"] = new_ip
    old["iface"] = None
    old["accumulated_bytes"] = old.get("accumulated_bytes", 0) + old_used
    old["baseline_bytes"] = 0
    old["last_seen"] = time.time()
    
    data[new_ip] = old
    save(data)
    log.info(f"ip_change: {username} {old_ip}→{new_ip}")
    return True


def on_renew(ip: str, time_left: int):
    data = load()
    if ip not in data:
        return
    data[ip]["server_time_left"] = int(time_left)
    data[ip]["last_seen"] = time.time()
    save(data)


def decrement_time(ip: str, amount: int) -> Optional[int]:
    data = load()
    if ip not in data:
        return None
    cur = data[ip].get("server_time_left")
    if cur is None:
        return None
    new_val = max(0, int(cur) - amount)
    data[ip]["server_time_left"] = new_val
    save(data)
    return new_val
