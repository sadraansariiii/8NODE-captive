#!/usr/bin/env python3
"""
ipset.py - ipset Wrapper
==========================
مدیریت ipset (whitelist کاربران)
- تنها این فایل با ipset کار می‌کنه
- همه پارامترها از config
"""
import os
import re
import subprocess
from typing import Optional, Any
from . import config, logger

log = logger.get("ipset")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _name() -> str:
    return config.get("IPSET_NAME", "authorized_clients")


def _run(args, check=False, timeout=5) -> subprocess.CompletedProcess:
    """اجرای ipset"""
    try:
        return subprocess.run(
            ["ipset"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired:
        log.error(f"timeout: ipset {' '.join(args)}")
        return subprocess.CompletedProcess(args, 1, "", "timeout")
    except FileNotFoundError:
        log.error("ipset command not found")
        return subprocess.CompletedProcess(args, 127, "", "not found")


# ════════════════════════════════════════════════════════════
# Lifecycle
# ════════════════════════════════════════════════════════════

def exists_set() -> bool:
    """آیا ipset ساخته شده؟"""
    r = _run(["list", "-name"])
    if r.returncode != 0:
        return False
    return _name() in r.stdout.split()


def ensure_exists():
    """اگه ipset نبود، بساز"""
    if exists_set():
        return True
    
    name = _name()
    r = _run(["create", name, "hash:ip", "timeout", "0", "counters"])
    if r.returncode == 0:
        log.info(f"created ipset: {name}")
        return True
    else:
        log.error(f"cannot create ipset: {r.stderr}")
        return False


def destroy():
    """حذف ipset"""
    _run(["destroy", _name()])


def flush():
    """پاک کردن همه members"""
    _run(["flush", _name()])


# ════════════════════════════════════════════════════════════
# Single IP
# ════════════════════════════════════════════════════════════

def add(ip: str, timeout: Optional[int] = None) -> bool:
    """
    اضافه کردن IP
    Args:
        ip: آی‌پی
        timeout: ثانیه (None = default از config)
    """
    ensure_exists()
    
    args = ["add", _name(), ip, "-exist"]
    if timeout is not None:
        args += ["timeout", str(int(timeout))]
    
    r = _run(args)
    if r.returncode == 0:
        log.debug(f"add {ip} timeout={timeout}")
        return True
    else:
        log.warning(f"add {ip} failed: {r.stderr.strip()}")
        return False


def remove(ip: str) -> bool:
    """حذف IP"""
    r = _run(["del", _name(), ip])
    if r.returncode == 0:
        log.debug(f"remove {ip}")
        return True
    return False  # ممکنه IP نبوده


def exists(ip: str) -> bool:
    """آیا IP تو ipset هست؟"""
    r = _run(["test", _name(), ip])
    return r.returncode == 0


def timeout_left(ip: str) -> Optional[int]:
    """
    ثانیه باقی‌مونده
    None اگه:
      - IP نبود
      - timeout نداشت (0 = infinite)
      - خطا
    """
    r = _run(["list", _name()])
    if r.returncode != 0:
        return None
    
    for line in r.stdout.splitlines():
        # فرمت: "10.10.0.100 timeout 3985 packets 0 bytes 0"
        m = re.match(rf"^{re.escape(ip)}\s+timeout\s+(\d+)", line)
        if m:
            val = int(m.group(1))
            return val if val > 0 else None
    
    return None


def renew(ip: str, seconds: int) -> bool:
    """آپدیت timeout"""
    if not seconds or seconds <= 0:
        return False
    return add(ip, timeout=seconds)


# ════════════════════════════════════════════════════════════
# Bulk
# ════════════════════════════════════════════════════════════

def list_all() -> list:
    """
    همه members با اطلاعات
    Returns:
        [{"ip": "...", "timeout": int, "packets": int, "bytes": int}, ...]
    """
    r = _run(["list", _name()])
    if r.returncode != 0:
        return []
    
    members = []
    in_members = False
    for line in r.stdout.splitlines():
        if line.startswith("Members:"):
            in_members = True
            continue
        if not in_members:
            continue
        line = line.strip()
        if not line:
            continue
        
        # "10.10.0.100 timeout 3985 packets 1234 bytes 567890"
        parts = line.split()
        if not parts:
            continue
        
        entry = {"ip": parts[0], "timeout": None, "packets": 0, "bytes": 0}
        i = 1
        while i < len(parts) - 1:
            key = parts[i]
            val = parts[i + 1]
            if key == "timeout":
                entry["timeout"] = int(val) if val.isdigit() else None
            elif key == "packets":
                entry["packets"] = int(val) if val.isdigit() else 0
            elif key == "bytes":
                entry["bytes"] = int(val) if val.isdigit() else 0
            i += 2
        
        members.append(entry)
    
    return members


def list_ips() -> list:
    """فقط IP ها"""
    return [m["ip"] for m in list_all()]


def count() -> int:
    """تعداد members"""
    r = _run(["list", _name()])
    if r.returncode != 0:
        return 0
    for line in r.stdout.splitlines():
        if line.startswith("Number of entries:"):
            try:
                return int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
    return 0


# ════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════

def save(path: Optional[str] = None) -> bool:
    """
    ذخیره ipset به فایل
    (فقط خطوط add، خط create حذف می‌شه)
    """
    path = path or config.get("IPSET_BACKUP_FILE", "/etc/captive-portal-ipset.conf")
    
    r = _run(["save", _name()])
    if r.returncode != 0:
        log.error(f"save failed: {r.stderr}")
        return False
    
    # فقط خطوط add
    lines = []
    for line in r.stdout.splitlines():
        if line.startswith("add "):
            lines.append(line)
    
    content = "\n".join(lines) + "\n" if lines else ""
    
    # atomic write
    import tempfile
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    try:
        fd, tmp = tempfile.mkstemp(dir=dir_name, prefix=".ipset.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            log.debug(f"saved ipset to {path} ({len(lines)} entries)")
            return True
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError as e:
        log.error(f"save write error: {e}")
        return False


def restore(path: Optional[str] = None) -> bool:
    """
    بازگردانی از فایل
    """
    path = path or config.get("IPSET_BACKUP_FILE", "/etc/captive-portal-ipset.conf")
    
    if not os.path.exists(path):
        log.debug(f"restore: no backup file {path}")
        return False
    
    ensure_exists()
    
    try:
        with open(path) as f:
            content = f.read()
    except OSError as e:
        log.error(f"restore read error: {e}")
        return False
    
    if not content.strip():
        return True
    
    r = subprocess.run(
        ["ipset", "restore", "-exist"],
        input=content,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    if r.returncode == 0:
        log.info(f"restored ipset from {path}")
        return True
    else:
        log.error(f"restore failed: {r.stderr}")
        return False


def save_default() -> bool:
    """save با مسیر config"""
    return save()


def restore_default() -> bool:
    """restore با مسیر config"""
    return restore()
