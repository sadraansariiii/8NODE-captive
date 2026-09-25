#!/usr/bin/env python3
"""config.py - Config Manager"""
import os
import shutil
import tempfile
import threading
from typing import Any, Optional
from datetime import datetime

_LOCK = threading.RLock()
_CONFIG = None
_COMPUTED = None
_CONFIG_PATH = None


def _default_path():
    return os.environ.get("CP_CONFIG", "/opt/captive-portal/config.conf")


def _coerce(value):
    if not isinstance(value, str):
        return value
    low = value.lower()
    if low in ("yes", "true", "on"):
        return True
    if low in ("no", "false", "off"):
        return False
    if value and (value.isdigit() or (value[0] in "+-" and value[1:].isdigit())):
        try:
            return int(value)
        except ValueError:
            pass
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    return value


def _uncoerce(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return ""
    return str(value)


def _parse_file(path):
    if not os.path.exists(path):
        return {}
    result = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[key] = _coerce(value)
    return result


def _compute(cfg):
    api_base = str(cfg.get("API_BASE", "")).rstrip("/")
    lan_ifaces = []
    if cfg.get("LAN_IFACE"):
        lan_ifaces.append(cfg["LAN_IFACE"])
    if cfg.get("WLX_IFACE"):
        lan_ifaces.append(cfg["WLX_IFACE"])
    lan_ip = cfg.get("LAN_IP", "10.10.0.1")
    portal_port = cfg.get("PORTAL_PORT", 8080)
    return {
        "LOGIN_URL":    f"{api_base}{cfg.get('API_LOGIN_PATH', '/login')}",
        "REGISTER_URL": f"{api_base}{cfg.get('API_REGISTER_PATH', '/register')}",
        "OTP_URL":      f"{api_base}{cfg.get('API_OTP_PATH', '/otp')}",
        "USERSET_URL":  f"{api_base}{cfg.get('API_USERSET_PATH', '/userset')}",
        "LAN_IFACES":   lan_ifaces,
        "HAS_WIFI":     bool(cfg.get("WLX_IFACE")),
        "HAS_LAN":      bool(cfg.get("LAN_IFACE")),
        "FW_MARK":          int(cfg.get("FW_MARK", 100)),
        "RT_TABLE_ID":      int(cfg.get("RT_TABLE_ID", 100)),
        "IP_RULE_PRIORITY": int(cfg.get("IP_RULE_PRIORITY", 219)),
        "PORTAL_URL": f"http://{lan_ip}:{portal_port}",
        "ADMIN_URL":  f"http://{lan_ip}:{cfg.get('ADMIN_PORT', 7575)}",
        "IS_TUNNEL_CONFIGURED": bool(cfg.get("L2TP_SERVER") and cfg.get("L2TP_USERNAME")),
        "IS_API_CONFIGURED":    bool(api_base and cfg.get("API_TOKEN")),
    }


def load(path=None, force=False):
    global _CONFIG, _COMPUTED, _CONFIG_PATH
    with _LOCK:
        if _CONFIG is not None and not force:
            return _CONFIG
        path = path or _default_path()
        _CONFIG = _parse_file(path)
        _COMPUTED = _compute(_CONFIG)
        _CONFIG_PATH = path
        return _CONFIG


def get(key, default=None):
    return load().get(key, default)


def require(key):
    cfg = load()
    if key not in cfg:
        raise KeyError(f"required config key missing: {key}")
    return cfg[key]


def has(key):
    return key in load()


def computed():
    load()
    return dict(_COMPUTED or {})


def get_computed(key, default=None):
    return computed().get(key, default)


def all():
    return dict(load())


def path():
    load()
    return _CONFIG_PATH or _default_path()


def is_loaded():
    return _CONFIG is not None


def set(key, value, save=True):
    global _CONFIG, _COMPUTED
    with _LOCK:
        load()
        _CONFIG[key] = value
        _CONFIG["LAST_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _COMPUTED = _compute(_CONFIG)
        if save:
            _save_file()
        return True


def set_many(updates, save=True):
    global _CONFIG, _COMPUTED
    with _LOCK:
        load()
        _CONFIG.update(updates)
        _CONFIG["LAST_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _COMPUTED = _compute(_CONFIG)
        if save:
            _save_file()
        return True


def unset(key, save=True):
    global _CONFIG, _COMPUTED
    with _LOCK:
        load()
        if key in _CONFIG:
            del _CONFIG[key]
            _COMPUTED = _compute(_CONFIG)
            if save:
                _save_file()
            return True
        return False


def _save_file():
    global _CONFIG
    path = _CONFIG_PATH or _default_path()
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    lines = []
    lines.append("# ============================================================")
    lines.append("# Captive Portal - Config")
    lines.append("# ============================================================")
    lines.append(f"# Last updated: {_CONFIG.get('LAST_UPDATED', '')}")
    lines.append("")
    for key, value in sorted(_CONFIG.items()):
        if key.startswith("_"):
            continue
        lines.append(f'{key}="{_uncoerce(value)}"')
    content = "\n".join(lines) + "\n"
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save():
    with _LOCK:
        load()
        _save_file()


def reload():
    global _CONFIG, _COMPUTED
    with _LOCK:
        _CONFIG = None
        _COMPUTED = None


def dump():
    return {
        "config":   dict(load()),
        "computed": computed(),
        "path":     path(),
    }


def validate():
    errors = []
    cfg = load()
    for k in ("NODE_ID", "LAN_IFACE", "WAN_IFACE", "LAN_IP", "PORTAL_PORT"):
        if not cfg.get(k):
            errors.append(f"missing: {k}")
    if not cfg.get("API_BASE"):
        errors.append("API_BASE empty")
    if cfg.get("L2TP_SERVER"):
        for k in ("L2TP_USERNAME", "L2TP_PASSWORD", "IPSEC_PSK"):
            if not cfg.get(k):
                errors.append(f"L2TP_SERVER set but {k} empty")
    return errors


def groups():
    return {
        "Meta":       ["LAST_UPDATED", "UPDATED_BY"],
        "Node":       ["NODE_ID", "NODE_NAME", "NODE_VERSION"],
        "API":        ["API_BASE", "API_TOKEN", "APP_ID", "WIFINODE",
                       "API_LOGIN_PATH", "API_REGISTER_PATH",
                       "API_OTP_PATH", "API_USERSET_PATH", "API_TIMEOUT"],
        "Interfaces": ["LAN_IFACE", "WAN_IFACE", "WAN_GATEWAY",
                       "WLX_IFACE", "TUNNEL_IFACE", "TUNNEL_TYPE"],
        "LAN":        ["LAN_IP", "LAN_CIDR", "LAN_NETWORK", "LAN_NETMASK"],
        "DHCP/DNS":   ["DHCP_RANGE_START", "DHCP_RANGE_END", "DHCP_LEASE",
                       "DNS_PRIMARY", "DNS_SECONDARY"],
        "Portal":     ["PORTAL_PORT", "PORTAL_TITLE"],
        "Admin":      ["ADMIN_ENABLED", "ADMIN_PORT",
                       "ADMIN_USERNAME", "ADMIN_PASSWORD"],
        "Brand":      ["BRAND_NAME", "BRAND_COLOR_PRIMARY", "BRAND_COLOR_ACCENT"],
        "Session":    ["CHECK_INTERVAL", "RUN_INTERVAL", "SLEEP_GRACE_SECONDS",
                       "SESSION_SECONDS", "IPSET_TIMEOUT_DEFAULT",
                       "IPSET_RENEW_THRESHOLD"],
        "L2TP":       ["L2TP_SERVER", "L2TP_USERNAME", "L2TP_PASSWORD",
                       "L2TP_LAC_NAME", "L2TP_MTU", "L2TP_MRU", "IPSEC_PSK"],
        "Bandwidth":  ["DEFAULT_BW_KBPS", "TOTAL_BW_MBIT"],
        "WiFi":       ["WLX_SSID", "WLX_PASSWORD", "WLX_CHANNEL",
                       "WLX_IP", "WLX_CIDR", "WLX_NETWORK",
                       "WLX_DHCP_START", "WLX_DHCP_END"],
        "Paths":      ["INSTALL_DIR", "DATA_DIR", "LOG_DIR",
                       "USAGE_LOG_DIR", "RUN_DIR", "SESSIONS_FILE"],
        "Routing":    ["RT_TABLE_ID", "RT_TABLE_NAME", "FW_MARK",
                       "IP_RULE_PRIORITY", "IPSET_NAME"],
        "Logging":    ["LOG_LEVEL", "LOG_MAX_DAYS"],
        "Behavior":   ["IP_FORWARDING", "MASQUERADE_ENABLED"],
    }
