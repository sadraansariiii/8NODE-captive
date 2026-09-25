#!/usr/bin/env python3
"""
api.py - API Client
====================
ارتباط با سرور مرکزی
- login/register/otp
- connect/run/sleep/disconnect
"""
import json
import re
import requests
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from . import config, logger

log = logger.get("api")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _base_payload() -> dict:
    """payload پایه برای همه درخواست‌ها"""
    return {
        "token": config.get("API_TOKEN", ""),
        "appId": config.get("APP_ID", ""),
        "wifinode": config.get("WIFINODE", ""),
    }


def _timeout() -> int:
    return int(config.get("API_TIMEOUT", 10))


def _parse_response(text: str) -> dict:
    """
    پاسخ سرور ممکنه چند JSON پشت سر هم + متن اضافی داشته باشه.
    آخرین JSON معتبر رو برگردون.
    """
    if not text:
        return {}
    
    # سعی کن همه JSON ها رو پیدا کنی
    matches = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
    for m in reversed(matches):
        try:
            obj = json.loads(m)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    
    # fallback: کل متن
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _post(url: str, payload: dict) -> Tuple[bool, dict]:
    """
    POST به API
    Returns: (success, data)
    """
    import json as _json
    
    # ─── Log Request ───
    try:
        req_str = _json.dumps(payload, ensure_ascii=False)
    except Exception:
        req_str = str(payload)
    
    log.debug(f"→ POST {url}")
    log.debug(f"  REQ: {req_str}")
    
    try:
        r = requests.post(
            url,
            json=payload,
            timeout=_timeout(),
            headers={"Content-Type": "application/json"},
        )
        
        # ─── Log Response ───
        log.debug(f"← {r.status_code} {url}")
        log.debug(f"  RES: {r.text[:500]}")
        
        data = _parse_response(r.text)
        return r.status_code == 200, data
    except requests.exceptions.Timeout:
        log.error(f"⏱ timeout: {url}")
        return False, {}
    except requests.exceptions.ConnectionError as e:
        log.error(f"✗ connection error: {url}: {e}")
        return False, {}
    except Exception as e:
        log.error(f"✗ api error: {url}: {e}")
        return False, {}


def _is_ok(data: dict) -> bool:
    """آیا پاسخ موفق بوده؟"""
    if not data:
        return False
    if data.get("done") is True:
        return True
    inner = data.get("data") or {}
    if isinstance(inner, dict) and inner.get("result") == "success":
        return True
    return False


def _get_error(data: dict) -> str:
    """پیام خطا از پاسخ"""
    err = data.get("errors")
    if not err:
        err = data.get("error")
    if isinstance(err, dict):
        # اولین value
        for v in err.values():
            return str(v)
    if err:
        return str(err)
    return "unknown error"


# ════════════════════════════════════════════════════════════
# Auth
# ════════════════════════════════════════════════════════════

def login(identifier: str, password: str, ip: str = "") -> dict:
    """
    ورود کاربر
    Returns: {"ok": bool, "data": dict, "error": str}
    """
    url = config.get_computed("LOGIN_URL")
    if not url:
        return {"ok": False, "data": {}, "error": "LOGIN_URL not configured"}
    
    payload = _base_payload()
    payload.update({
        "identifier": identifier,
        "password": password,
        "ippublic": ip,
        "ipserver": config.get("SERVER_PUBLIC_IP", ""),
    })
    
    success, data = _post(url, payload)
    ok = success and _is_ok(data)
    
    result = {
        "ok": ok,
        "data": data,
        "error": "" if ok else _get_error(data),
    }
    
    if ok:
        log.info(f"login OK: {identifier}")
    else:
        log.warning(f"login failed: {identifier}: {result['error']}")
    
    return result


def register(identifier: str, username: str, password: str,
             name: str = "") -> dict:
    """ثبت‌نام کاربر"""
    url = config.get_computed("REGISTER_URL")
    if not url:
        return {"ok": False, "data": {}, "error": "REGISTER_URL not configured"}
    
    payload = _base_payload()
    payload.update({
        "identifier": identifier,
        "username": username,
        "name": name or username,
        "password": password,
    })
    
    success, data = _post(url, payload)
    ok = success and _is_ok(data)
    
    result = {
        "ok": ok,
        "data": data,
        "error": "" if ok else _get_error(data),
    }
    
    log.info(f"register {'OK' if ok else 'FAILED'}: {username}")
    return result


def otp(identifier: str, code: str) -> dict:
    """تایید OTP"""
    url = config.get_computed("OTP_URL")
    if not url:
        return {"ok": False, "data": {}, "error": "OTP_URL not configured"}
    
    payload = _base_payload()
    payload.update({
        "identifier": identifier,
        "otp": code,
    })
    
    success, data = _post(url, payload)
    ok = success and _is_ok(data)
    
    result = {
        "ok": ok,
        "data": data,
        "error": "" if ok else _get_error(data),
    }
    
    log.info(f"otp {'OK' if ok else 'FAILED'}: {identifier}")
    return result


# ════════════════════════════════════════════════════════════
# Events
# ════════════════════════════════════════════════════════════

def _event_payload(event: str, username: str, ip: str,
                    down: int = 0, up: int = 0) -> dict:
    """payload برای event"""
    payload = _base_payload()
    payload.update({
        "event": event,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": username,
        "ipmas": ip,
        "ippublic": ip,
        "nodewifi": config.get("NODE_ID", ""),
    })
    if event in ("run", "sleep", "disconnect"):
        payload["down"] = int(down)
        payload["up"] = int(up)
    return payload


def _send_event(event: str, username: str, ip: str,
                 down: int = 0, up: int = 0) -> dict:
    """ارسال event"""
    url = config.get_computed("USERSET_URL")
    if not url:
        log.error("USERSET_URL not configured")
        return {}
    
    payload = _event_payload(event, username, ip, down, up)
    success, data = _post(url, payload)
    
    if not success:
        return {}
    return data


def _parse_event_response(data: dict) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    استخراج time/quota/bw از پاسخ
    Returns: (time, quota, bw) — هر کدوم ممکنه None باشه
    """
    if not data:
        return None, None, None
    
    inner = data.get("data") or {}
    if not isinstance(inner, dict):
        inner = data
    
    time_left = inner.get("time")
    quota = inner.get("trafic") or inner.get("traffic") or inner.get("quota")
    bw = inner.get("bw")
    
    # تبدیل به int
    def to_int(v):
        if v is None:
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    
    return to_int(time_left), to_int(quota), to_int(bw)


def connect(username: str, ip: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    رویداد connect
    Returns: (time_left, quota_mb, bw_kbps)
    """
    data = _send_event("connect", username, ip)
    result = _parse_event_response(data)
    log.info(f"connect: {username}@{ip} → time={result[0]} quota={result[1]} bw={result[2]}")
    return result


def run(username: str, ip: str, down: int = 0, up: int = 0) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """رویداد run (هر RUN_INTERVAL)"""
    data = _send_event("run", username, ip, down, up)
    result = _parse_event_response(data)
    log.debug(f"run: {username}@{ip} down={down} → time={result[0]}")
    return result


def sleep(username: str, ip: str, down: int = 0, up: int = 0) -> bool:
    """رویداد sleep (کاربر موقتاً قطع)"""
    data = _send_event("sleep", username, ip, down, up)
    ok = bool(data)
    log.info(f"sleep: {username}@{ip} down={down} → {'OK' if ok else 'FAILED'}")
    return ok


def disconnect(username: str, ip: str, down: int = 0, up: int = 0) -> bool:
    """رویداد disconnect"""
    data = _send_event("disconnect", username, ip, down, up)
    ok = bool(data)
    log.info(f"disconnect: {username}@{ip} down={down} → {'OK' if ok else 'FAILED'}")
    return ok


# ════════════════════════════════════════════════════════════
# Health
# ════════════════════════════════════════════════════════════

def is_alive() -> bool:
    """
    چک اتصال به API (base URL)
    """
    base = config.get("API_BASE", "")
    if not base:
        return False
    try:
        r = requests.head(base, timeout=5)
        return r.status_code < 500
    except Exception:
        return False
