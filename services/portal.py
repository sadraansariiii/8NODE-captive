#!/usr/bin/env python3
"""
portal.py - Captive Portal (Flask)
====================================
پورتال کاربر:
- login
- register
- otp
- status
- disconnect
"""
import os
import sys
import json
from datetime import datetime
from flask import (
    Flask, request, render_template_string,
    redirect, url_for, session as flask_session
)

# اضافه کردن مسیر library
sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import (
    config, logger, sessions, ipset, tc,
    network, api, disconnect, limits
)

log = logger.get("portal")

app = Flask(__name__)
app.secret_key = "captive-portal-secret-change-me"


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _get_cfg() -> dict:
    config.reload()
    return config.load()


def _client_ip() -> str:
    """IP کاربر"""
    return request.remote_addr


def _brand() -> dict:
    cfg = _get_cfg()
    return {
        "name": cfg.get("BRAND_NAME", "Captive Portal"),
        "color_primary": cfg.get("BRAND_COLOR_PRIMARY", "#0a1f44"),
        "color_accent": cfg.get("BRAND_COLOR_ACCENT", "#17c3e6"),
        "portal_title": cfg.get("PORTAL_TITLE", "ورود به اینترنت"),
    }


def _mac_for_ip(ip: str) -> str:
    """MAC کاربر"""
    return network.get_mac_from_leases(ip) or ""


# ════════════════════════════════════════════════════════════
# Templates
# ════════════════════════════════════════════════════════════

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: Tahoma, 'Segoe UI', sans-serif;
    background: linear-gradient(160deg, #f3f5f9 0%, #e9edf5 100%);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    direction: rtl;
}
.wrap { width: 100%; max-width: 400px; }
.card {
    background: white;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(10,31,68,0.12);
    padding: 32px 26px;
}
h2 {
    color: var(--primary);
    font-size: 20px;
    text-align: center;
    margin-bottom: 8px;
}
.sub {
    text-align: center;
    color: #6b7280;
    font-size: 13px;
    margin-bottom: 20px;
}
.brand {
    text-align: center;
    font-size: 24px;
    font-weight: bold;
    color: var(--primary);
    margin-bottom: 22px;
}
input {
    width: 100%;
    padding: 13px 14px;
    margin: 7px 0;
    border: 1.5px solid #e2e6ee;
    border-radius: 10px;
    font-size: 15px;
    background: #fafbfd;
}
input:focus {
    outline: none;
    border-color: var(--accent);
    background: white;
}
button, .btn {
    width: 100%;
    padding: 13px;
    margin-top: 10px;
    background: var(--primary);
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 15px;
    font-weight: bold;
    cursor: pointer;
    text-decoration: none;
    display: block;
    text-align: center;
}
button:hover, .btn:hover { opacity: 0.9; }
.btn-danger { background: #e53935; }
.msg {
    text-align: center;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 13.5px;
    margin-bottom: 14px;
}
.msg.error { background: #fdecea; color: #e53935; }
.msg.success { background: #e9f9ee; color: #1fa855; }
.links {
    text-align: center;
    margin-top: 16px;
    font-size: 13px;
}
.links a { color: var(--accent); text-decoration: none; font-weight: bold; }
.stat {
    background: #f6f8fc;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
}
.stat-label { color: #6b7280; font-size: 13px; }
.stat-value { color: var(--primary); font-weight: bold; }
"""


def _render_css() -> str:
    brand = _brand()
    return f"""
    :root {{
        --primary: {brand['color_primary']};
        --accent: {brand['color_accent']};
    }}
    {BASE_CSS}
    """


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ brand }} | ورود</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
<div class="brand">{{ brand }}</div>
<div class="card">
<h2>{{ title }}</h2>
<p class="sub">برای دسترسی به اینترنت وارد شوید</p>
{% if message %}<div class="msg {{ msg_class }}">{{ message }}</div>{% endif %}
<form method="POST" action="/login">
<input type="text" name="username" placeholder="نام کاربری" required>
<input type="password" name="password" placeholder="رمز عبور" required>
<button type="submit">ورود</button>
</form>
<div class="links"><a href="/register">حساب کاربری ندارید؟ ثبت‌نام کنید</a></div>
</div>
</div>
</body>
</html>
"""


REGISTER_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ brand }} | ثبت‌نام</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
<div class="brand">{{ brand }}</div>
<div class="card">
<h2>ساخت حساب کاربری</h2>
<p class="sub">اطلاعات زیر را کامل کنید</p>
{% if message %}<div class="msg {{ msg_class }}">{{ message }}</div>{% endif %}
<form method="POST" action="/register">
<input type="text" name="username" placeholder="نام کاربری" required>
<input type="password" name="password" placeholder="رمز عبور" required>
<input type="tel" name="mobile" placeholder="شماره موبایل" required>
<button type="submit">ثبت‌نام</button>
</form>
<div class="links"><a href="/">قبلاً ثبت‌نام کردید؟ وارد شوید</a></div>
</div>
</div>
</body>
</html>
"""


OTP_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ brand }} | تایید</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
<div class="brand">{{ brand }}</div>
<div class="card">
<h2>تایید شماره موبایل</h2>
<p class="sub">کد ارسال‌شده به {{ identifier }} را وارد کنید</p>
{% if message %}<div class="msg {{ msg_class }}">{{ message }}</div>{% endif %}
<form method="POST" action="/otp">
<input type="hidden" name="identifier" value="{{ identifier }}">
<input type="text" name="otp" placeholder="کد تایید" required>
<button type="submit">تایید</button>
</form>
</div>
</div>
</body>
</html>
"""


STATUS_HTML = """
<!DOCTYPE html>
<html lang="fa">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="15">
<title>{{ brand }} | وضعیت</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
<div class="brand">{{ brand }}</div>
<div class="card">
<h2>وضعیت اتصال</h2>
<p class="sub">{{ username }}</p>

<div class="stat">
<span class="stat-label">مصرف تا این لحظه</span>
<span class="stat-value">{{ used_mb }} MB</span>
</div>
<div class="stat">
<span class="stat-label">سقف ترافیک</span>
<span class="stat-value">{{ quota_display }}</span>
</div>
<div class="stat">
<span class="stat-label">زمان باقی‌مانده</span>
<span class="stat-value">{{ time_left }}</span>
</div>

<form method="POST" action="/disconnect">
<button type="submit" class="btn-danger">قطع اتصال</button>
</form>
</div>
</div>
</body>
</html>
"""


# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """صفحه login"""
    cfg = _get_cfg()
    msg = None
    msg_class = ""
    if request.args.get("registered") == "1":
        msg = "ثبت‌نام موفق! حالا وارد شوید."
        msg_class = "success"
    return render_template_string(
        LOGIN_HTML,
        css=_render_css(),
        brand=_brand()["name"],
        title=_brand()["portal_title"],
        message=msg,
        msg_class=msg_class,
    )


@app.route("/login", methods=["POST"])
def login():
    """login کاربر"""
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ip = _client_ip()
    cfg = _get_cfg()
    
    # API login
    result = api.login(username, password, ip)
    
    if not result["ok"]:
        return render_template_string(
            LOGIN_HTML,
            css=_render_css(),
            brand=_brand()["name"],
            title=_brand()["portal_title"],
            message=result["error"] or "نام کاربری یا رمز عبور اشتباه است",
            msg_class="error",
        )
    
    # login OK → session جدید (pending)
    mac = _mac_for_ip(ip)
    
    # اگه session قبلی از همین IP هست، حذف
    sessions.delete(ip)
    
    # ساخت session pending
    sessions.create(ip, username, mac=mac, state="pending")
    
    # ipset موقت (تا session_monitor do_connect بزنه)
    default_timeout = int(cfg.get("SESSION_SECONDS", 86400))
    ipset.add(ip, timeout=default_timeout)
    
    log.info(f"login OK: {username}@{ip}")
    return redirect(url_for("status"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """ثبت‌نام"""
    if request.method == "GET":
        return render_template_string(
            REGISTER_HTML,
            css=_render_css(),
            brand=_brand()["name"],
        )
    
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    mobile = request.form.get("mobile", "")
    
    result = api.register(mobile, username, password, name=username)
    
    if not result["ok"]:
        return render_template_string(
            REGISTER_HTML,
            css=_render_css(),
            brand=_brand()["name"],
            message=result["error"] or "ثبت‌نام ناموفق",
            msg_class="error",
        )
    
    # برو به OTP
    return redirect(url_for("otp_page", identifier=mobile))


@app.route("/otp", methods=["GET", "POST"])
def otp_page():
    """تایید OTP"""
    identifier = request.args.get("identifier") or request.form.get("identifier", "")
    
    if request.method == "GET":
        return render_template_string(
            OTP_HTML,
            css=_render_css(),
            brand=_brand()["name"],
            identifier=identifier,
        )
    
    code = request.form.get("otp", "")
    result = api.otp(identifier, code)
    
    if not result["ok"]:
        return render_template_string(
            OTP_HTML,
            css=_render_css(),
            brand=_brand()["name"],
            identifier=identifier,
            message=result["error"] or "کد نادرست",
            msg_class="error",
        )
    
    return redirect(url_for("index", registered="1"))


@app.route("/status")
def status():
    """وضعیت کاربر"""
    ip = _client_ip()
    session = sessions.get(ip)
    
    if not session:
        return redirect("/")
    
    username = session.get("username", "-")
    used_mb = limits.get_used_mb(ip)
    quota = limits.get_quota(ip)
    time_left = limits.get_time_left(ip)
    
    # نمایش
    quota_display = f"{quota} MB" if quota else "نامحدود"
    
    if time_left is not None:
        h = time_left // 3600
        m = (time_left % 3600) // 60
        if h > 0:
            time_left_display = f"{h} ساعت و {m} دقیقه"
        else:
            time_left_display = f"{m} دقیقه"
    else:
        time_left_display = "نامشخص"
    
    return render_template_string(
        STATUS_HTML,
        css=_render_css(),
        brand=_brand()["name"],
        username=username,
        used_mb=round(used_mb, 2),
        quota_display=quota_display,
        time_left=time_left_display,
    )


@app.route("/disconnect", methods=["POST"])
def disconnect_route():
    """قطع اتصال توسط کاربر"""
    ip = _client_ip()
    
    disconnect.do_disconnect(None, ip, "user_logout")
    
    return render_template_string(
        LOGIN_HTML,
        css=_render_css(),
        brand=_brand()["name"],
        title=_brand()["portal_title"],
        message="با موفقیت قطع شدید",
        msg_class="success",
    )


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    cfg = _get_cfg()
    host = cfg.get("LAN_IP", "0.0.0.0")
    port = int(cfg.get("PORTAL_PORT", 8080))
    
    log.info(f"portal starting on {host}:{port}")
    
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
