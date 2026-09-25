#!/usr/bin/env python3
"""
admin.py - Admin Panel (Flask)
================================
پنل ادمین:
- dashboard
- sessions management
- settings (تغییر همه پارامترها)
- reload
"""
import os
import sys
import json
import functools
from datetime import datetime
from flask import (
    Flask, request, render_template_string,
    redirect, url_for, session as flask_session,
    jsonify
)

sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import (
    config, logger, sessions, ipset, tc,
    network, api, disconnect, limits, connect
)

log = logger.get("admin")

app = Flask(__name__)
app.secret_key = "admin-secret-change-me"


# ════════════════════════════════════════════════════════════
# Auth
# ════════════════════════════════════════════════════════════

def _get_cfg() -> dict:
    config.reload()
    return config.load()


def _check_auth(username: str, password: str) -> bool:
    cfg = _get_cfg()
    return (
        username == cfg.get("ADMIN_USERNAME", "admin") and
        password == cfg.get("ADMIN_PASSWORD", "admin")
    )


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not flask_session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ════════════════════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════════════════════

ADMIN_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
    font-family: Tahoma, 'Segoe UI', sans-serif;
    background: linear-gradient(160deg, #f3f5f9 0%, #e9edf5 100%);
    direction: rtl;
    min-height: 100vh;
    color: #1f2937;
    -webkit-font-smoothing: antialiased;
}

/* ─── Nav ─── */
.nav {
    background: #0a1f44;
    color: white;
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}
.nav h1 {
    font-size: 18px;
    font-weight: bold;
}
.nav .links {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}
.nav a {
    color: #17c3e6;
    text-decoration: none;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    transition: background .2s;
    white-space: nowrap;
}
.nav a:hover {
    background: rgba(23, 195, 230, 0.15);
}

/* ─── Container ─── */
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px 16px;
}

/* ─── Card ─── */
.card {
    background: white;
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(10, 31, 68, 0.06);
    margin-bottom: 20px;
}
.card h2 {
    color: #0a1f44;
    font-size: 18px;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid #e2e6ee;
}

/* ─── Stats Grid ─── */
.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
}
.stat {
    background: #f6f8fc;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.stat-num {
    font-size: 26px;
    font-weight: bold;
    color: #0a1f44;
    word-break: break-all;
}
.stat-label {
    font-size: 13px;
    color: #6b7280;
    margin-top: 6px;
}

/* ─── Table (ریسپانسیو) ─── */
.table-wrap {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    border-radius: 10px;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
    min-width: 700px;
}
th, td {
    padding: 10px 12px;
    text-align: right;
    border-bottom: 1px solid #e2e6ee;
    white-space: nowrap;
}
th {
    background: #f6f8fc;
    font-weight: bold;
    color: #0a1f44;
    position: sticky;
    top: 0;
}
tr:hover { background: #fafbfd; }

/* ─── Buttons ─── */
.btn {
    padding: 8px 16px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    text-decoration: none;
    display: inline-block;
    transition: opacity .2s;
    white-space: nowrap;
}
.btn:hover { opacity: 0.9; }
.btn-danger { background: #e53935; color: white; }
.btn-primary { background: #0a1f44; color: white; }
.btn-success { background: #1fa855; color: white; }

/* ─── Form ─── */
.form-group { margin-bottom: 14px; }
.form-group label {
    display: block;
    font-size: 13px;
    color: #374151;
    margin-bottom: 6px;
    font-weight: bold;
}
input, select {
    width: 100%;
    padding: 11px 14px;
    border: 1.5px solid #e2e6ee;
    border-radius: 8px;
    font-size: 14px;
    background: #fafbfd;
    transition: border-color .2s;
    font-family: inherit;
}
input:focus, select:focus {
    outline: none;
    border-color: #17c3e6;
    background: white;
}

/* ─── Grid ─── */
.grid-2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
}

/* ─── Group (Settings) ─── */
.group {
    border: 1px solid #e2e6ee;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 16px;
    background: white;
}
.group h3 {
    font-size: 15px;
    color: #0a1f44;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e2e6ee;
}

/* ─── Messages ─── */
.msg {
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 14px;
}
.msg.success { background: #e9f9ee; color: #1fa855; }
.msg.error { background: #fdecea; color: #e53935; }

/* ─── Login Page ─── */
.login-wrap {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.login-card {
    background: white;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(10, 31, 68, 0.12);
    padding: 36px 28px;
    width: 100%;
    max-width: 400px;
}
.login-card h2 {
    color: #0a1f44;
    font-size: 20px;
    text-align: center;
    margin-bottom: 8px;
}
.login-card .sub {
    text-align: center;
    color: #6b7280;
    font-size: 13px;
    margin-bottom: 24px;
}
.login-card .btn {
    width: 100%;
    padding: 13px;
    font-size: 15px;
    margin-top: 10px;
}

/* ─── Mobile (≤600px) ─── */
@media (max-width: 600px) {
    .nav {
        padding: 12px 14px;
        flex-direction: column;
        align-items: stretch;
    }
    .nav h1 {
        text-align: center;
        font-size: 16px;
    }
    .nav .links {
        justify-content: center;
    }
    .nav a {
        padding: 8px 12px;
        font-size: 12px;
    }
    .container {
        padding: 14px 10px;
    }
    .card {
        padding: 18px 14px;
        border-radius: 10px;
    }
    .card h2 {
        font-size: 16px;
    }
    .stats {
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
    }
    .stat {
        padding: 12px 8px;
    }
    .stat-num {
        font-size: 20px;
    }
    .stat-label {
        font-size: 11px;
    }
    .login-card {
        padding: 28px 20px;
    }
    .login-card h2 {
        font-size: 18px;
    }
    table {
        font-size: 12px;
        min-width: 600px;
    }
    th, td {
        padding: 8px 6px;
    }
    .group {
        padding: 12px;
    }
    .grid-2 {
        grid-template-columns: 1fr;
    }
}

/* ─── Small Mobile (≤380px) ─── */
@media (max-width: 380px) {
    .stats {
        grid-template-columns: 1fr;
    }
    .nav h1 {
        font-size: 15px;
    }
    .nav a {
        font-size: 11px;
        padding: 6px 10px;
    }
}
"""


def _render_css() -> str:
    return ADMIN_CSS


# ════════════════════════════════════════════════════════════
# Templates
# ════════════════════════════════════════════════════════════

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Admin | ورود</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="login-wrap">
<div class="login-card">
<h2>پنل ادمین</h2>
<p class="sub">برای ورود، اطلاعات خود را وارد کنید</p>
{% if error %}<div class="msg error">{{ error }}</div>{% endif %}
<form method="POST">
<div class="form-group">
<label>نام کاربری</label>
<input name="username" required autocomplete="username" autofocus>
</div>
<div class="form-group">
<label>رمز عبور</label>
<input type="password" name="password" required autocomplete="current-password">
</div>
<button type="submit" class="btn btn-primary">ورود</button>
</form>
</div>
</div>
</body>
</html>
"""


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin | Dashboard</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
<h1>{{ brand }} Admin</h1>
<div class="links">
<a href="/">داشبورد</a>
<a href="/sessions">کاربران</a>
<a href="/settings">تنظیمات</a>
<a href="/logout">خروج</a>
</div>
</div>
<div class="container">

<div class="card">
<h2>آمار کلی</h2>
<div class="stats">
<div class="stat"><div class="stat-num">{{ total_sessions }}</div><div class="stat-label">کاربران فعال</div></div>
<div class="stat"><div class="stat-num">{{ connected }}</div><div class="stat-label">وصل</div></div>
<div class="stat"><div class="stat-num">{{ sleeping }}</div><div class="stat-label">Sleep</div></div>
<div class="stat"><div class="stat-num">{{ ipset_count }}</div><div class="stat-label">IP در ipset</div></div>
</div>
</div>

<div class="card">
<h2>وضعیت شبکه</h2>
<div class="stats">
<div class="stat"><div class="stat-num">{{ lan_ip }}</div><div class="stat-label">LAN IP</div></div>
<div class="stat"><div class="stat-num">{{ wan_iface }}</div><div class="stat-label">WAN</div></div>
<div class="stat"><div class="stat-num">{{ ppp_state }}</div><div class="stat-label">PPP</div></div>
<div class="stat"><div class="stat-num">{{ api_state }}</div><div class="stat-label">API</div></div>
</div>
</div>

<div class="card">
<h2>عملیات</h2>
<div style="display:flex;gap:10px;flex-wrap:wrap;">
<a href="/reload" class="btn btn-success" onclick="return confirm('Reload کل سیستم؟')">🔄 Reload</a>
<a href="/reset" class="btn btn-danger" onclick="return confirm('Reset کامل؟')">⚠️ Reset</a>
</div>
</div>

</div>
</body>
</html>
"""


SESSIONS_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin | کاربران</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
<h1>{{ brand }} Admin</h1>
<div class="links">
<a href="/">داشبورد</a>
<a href="/sessions">کاربران</a>
<a href="/settings">تنظیمات</a>
<a href="/logout">خروج</a>
</div>
</div>
<div class="container">
<div class="card">
<h2>کاربران فعال ({{ sessions|length }})</h2>
{% if sessions %}
<div class="table-wrap">
<table>
<thead>
<tr>
<th>IP</th><th>Username</th><th>MAC</th><th>State</th>
<th>Used (MB)</th><th>Quota (MB)</th><th>Time Left</th><th>BW (KB/s)</th>
<th>عملیات</th>
</tr>
</thead>
<tbody>
{% for s in sessions %}
<tr>
<td>{{ s.ip }}</td>
<td>{{ s.username }}</td>
<td>{{ s.mac or '-' }}</td>
<td>{{ s.state }}</td>
<td>{{ s.used_mb }}</td>
<td>{{ s.quota or '∞' }}</td>
<td>{{ s.time_left_display }}</td>
<td>{{ s.bw or '∞' }}</td>
<td>
<form method="POST" action="/kill/{{ s.ip }}" style="display:inline;">
<button class="btn btn-danger" onclick="return confirm('قطع شود؟')">Kill</button>
</form>
</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% else %}
<p>هیچ کاربر فعالی نیست.</p>
{% endif %}
</div>
</div>
</body>
</html>
"""


SETTINGS_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin | تنظیمات</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
<h1>{{ brand }} Admin</h1>
<div class="links">
<a href="/">داشبورد</a>
<a href="/sessions">کاربران</a>
<a href="/settings">تنظیمات</a>
<a href="/logout">خروج</a>
</div>
</div>
<div class="container">

{% if message %}
<div class="msg {{ msg_class }}">{{ message }}</div>
{% endif %}

<form method="POST" action="/settings">

{% for group_name, keys in groups.items() %}
<div class="group">
<h3>{{ group_name }}</h3>
<div class="grid-2">
{% for key in keys %}
<div class="form-group">
<label>{{ key }}</label>
<input name="{{ key }}" value="{{ cfg.get(key, '') }}">
</div>
{% endfor %}
</div>
</div>
{% endfor %}

<div class="card">
<button type="submit" class="btn btn-success" style="padding:12px 32px;font-size:15px;width:100%;max-width:300px;">ذخیره همه</button>
</div>

</form>

</div>
</body>
</html>
"""

RELOAD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin | Reload</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
<h1>{{ brand }} Admin</h1>
<div class="links">
<a href="/">داشبورد</a>
<a href="/sessions">کاربران</a>
<a href="/settings">تنظیمات</a>
<a href="/reload">Reload</a>
<a href="/logout">خروج</a>
</div>
</div>
<div class="container">

<div class="card">
<h2>{% if success %}✅ Reload موفق{% else %}❌ Reload ناموفق{% endif %}</h2>
<pre style="background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;font-size:12px;line-height:1.6;direction:ltr;text-align:left;max-height:600px;">{{ output }}</pre>
<div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;">
<a href="/" class="btn btn-primary">بازگشت</a>
<a href="/reload" class="btn btn-success" onclick="return confirm('Reload دوباره؟')">Reload مجدد</a>
</div>
</div>

</div>
</body>
</html>
"""

RESET_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin | Reset</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
<h1>{{ brand }} Admin</h1>
<div class="links">
<a href="/">داشبورد</a>
<a href="/sessions">کاربران</a>
<a href="/settings">تنظیمات</a>
<a href="/reload">Reload</a>
<a href="/logout">خروج</a>
</div>
</div>
<div class="container">

<div class="card">
<h2>{% if success %}✅ Reset موفق{% else %}❌ Reset ناموفق{% endif %}</h2>
<pre style="background:#1e293b;color:#e2e8f0;padding:16px;border-radius:8px;overflow-x:auto;font-size:12px;line-height:1.6;direction:ltr;text-align:left;max-height:600px;">{{ output }}</pre>
<div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;">
<a href="/" class="btn btn-primary">بازگشت</a>
<a href="/reset" class="btn btn-danger" onclick="return confirm('Reset کل سیستم؟')">Reset مجدد</a>
</div>
</div>

</div>
</body>
</html>
"""




# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if _check_auth(username, password):
            flask_session["admin_logged_in"] = True
            log.info(f"admin login: {username}")
            return redirect(url_for("admin_dashboard"))
        return render_template_string(LOGIN_HTML, css=_render_css(), error="نام کاربری یا رمز اشتباه")
    
    return render_template_string(LOGIN_HTML, css=_render_css())


@app.route("/logout")
def admin_logout():
    flask_session.clear()
    return redirect(url_for("admin_login"))


@app.route("/")
@require_auth
def admin_dashboard():
    cfg = _get_cfg()
    
    sess = sessions.load()
    connected = sum(1 for s in sess.values() if s.get("state") == "connect")
    sleeping = sum(1 for s in sess.values() if s.get("state") == "sleep")
    
    # PPP state
    ppp_state = "DOWN"
    if network.iface_exists("ppp0"):
        ppp_state = "UP"
    
    # API state
    api_state = "OK" if api.is_alive() else "DOWN"
    
    return render_template_string(
        DASHBOARD_HTML,
        css=_render_css(),
        brand=cfg.get("BRAND_NAME", "Portal"),
        total_sessions=len(sess),
        connected=connected,
        sleeping=sleeping,
        ipset_count=ipset.count(),
        lan_ip=cfg.get("LAN_IP", "-"),
        wan_iface=cfg.get("WAN_IFACE", "-"),
        ppp_state=ppp_state,
        api_state=api_state,
    )


@app.route("/sessions")
@require_auth
def admin_sessions():
    cfg = _get_cfg()
    sess = sessions.load()
    
    rows = []
    for ip, s in sess.items():
        used_mb = limits.get_used_mb(ip)
        time_left = limits.get_time_left(ip)
        
        if time_left is not None:
            h = time_left // 3600
            m = (time_left % 3600) // 60
            time_display = f"{h}s {m}m" if h > 0 else f"{m}m"
        else:
            time_display = "-"
        
        rows.append({
            "ip": ip,
            "username": s.get("username", "-"),
            "mac": s.get("mac"),
            "state": s.get("state", "-"),
            "used_mb": round(used_mb, 2),
            "quota": s.get("quota_mb"),
            "time_left_display": time_display,
            "bw": s.get("bw_kbps"),
        })
    
    return render_template_string(
        SESSIONS_HTML,
        css=_render_css(),
        brand=cfg.get("BRAND_NAME", "Portal"),
        sessions=rows,
    )


@app.route("/kill/<ip>", methods=["POST"])
@require_auth
def admin_kill(ip):
    disconnect.do_disconnect(None, ip, "admin_kill")
    log.info(f"admin killed: {ip}")
    return redirect(url_for("admin_sessions"))


@app.route("/settings", methods=["GET", "POST"])
@require_auth
def admin_settings():
    cfg = _get_cfg()
    message = None
    msg_class = ""
    
    if request.method == "POST":
        updates = {}
        for key, value in request.form.items():
            if not key.startswith("_"):
                updates[key] = value
        
        try:
            config.set_many(updates)
            message = f"{len(updates)} پارامتر ذخیره شد"
            msg_class = "success"
            log.info(f"admin settings updated: {len(updates)} keys")
        except Exception as e:
            message = f"خطا: {e}"
            msg_class = "error"
        
        # reload config
        config.reload()
        cfg = config.load()
    
    return render_template_string(
        SETTINGS_HTML,
        css=_render_css(),
        brand=cfg.get("BRAND_NAME", "Portal"),
        cfg=cfg,
        groups=config.groups(),
        message=message,
        msg_class=msg_class,
    )


# ════════════════════════════════════════════════════════════
# API Endpoints (JSON)
# ════════════════════════════════════════════════════════════

@app.route("/api/sessions")
@require_auth
def api_sessions():
    sess = sessions.load()
    return jsonify(sess)


@app.route("/api/status")
@require_auth
def api_status():
    cfg = _get_cfg()
    return jsonify({
        "node_id": cfg.get("NODE_ID"),
        "sessions": sessions.count(),
        "ipset": ipset.count(),
        "api_alive": api.is_alive(),
        "ppp": network.iface_exists("ppp0"),
    })


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════



@app.route("/reset", methods=["POST", "GET"])
@require_auth
def admin_reset():
    """Reset کامل: reload + restart سرویس‌ها"""
    import subprocess
    lines = []
    
    def run(cmd, timeout=120):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            lines.append(f"$ {' '.join(cmd)}")
            lines.append(f"exit: {r.returncode}")
            if r.stdout:
                lines.append(r.stdout[:800])
            if r.stderr:
                lines.append(f"stderr: {r.stderr[:300]}")
            lines.append("")
            return r.returncode == 0
        except Exception as e:
            lines.append(f"❌ {e}")
            return False
    
    lines.append("=== RESET START ===")
    lines.append("")
    
    # ۱. cp-reload
    run(["bash", "-c", "cp-reload 2>&1"], timeout=180)
    
    # ۲. restart سرویس‌ها
    for svc in ["captive-portal", "captive-portal-admin", "session-monitor"]:
        run(["systemctl", "restart", svc], timeout=30)
    
    lines.append("=== RESET COMPLETE ===")
    
    return render_template_string(
        RESET_HTML,
        css=_render_css(),
        brand=_get_cfg().get("BRAND_NAME", "Portal"),
        output="\n".join(lines),
        success=True,
    )




@app.route("/reload", methods=["POST", "GET"])
@require_auth
def admin_reload():
    """اجرای cp-reload"""
    import subprocess
    output = ""
    success = False
    try:
        r = subprocess.run(
            ["bash", "-c", "cp-reload 2>&1"],
            capture_output=True, text=True, timeout=180
        )
        output = r.stdout
        if r.stderr:
            output += "\n\n=== STDERR ===\n" + r.stderr
        success = (r.returncode == 0)
        
        if not output.strip():
            r2 = subprocess.run(
                ["journalctl", "-u", "captive-portal-boot", "--since", "1 min ago", "--no-pager"],
                capture_output=True, text=True, timeout=10
            )
            output = r2.stdout
    except subprocess.TimeoutExpired:
        output = "⏱ Timeout (180s)"
    except Exception as e:
        output = f"❌ {e}"
    
    return render_template_string(
        RELOAD_HTML,
        css=_render_css(),
        brand=_get_cfg().get("BRAND_NAME", "Portal"),
        output=output,
        success=success,
    )


def main():
    cfg = _get_cfg()
    host = cfg.get("LAN_IP", "0.0.0.0")
    port = int(cfg.get("ADMIN_PORT", 7575))
    
    log.info(f"admin starting on {host}:{port}")
    
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
