#!/usr/bin/env python3
"""
reload.py - Reload System
===========================
اعمال کامل config.conf به سیستم
- netplan (IP)
- ipset
- L2TP (swanctl یا ipsec)
- routing
- firewall
- dnsmasq
- WiFi
- HTB
"""
import os
import sys
import time
import subprocess
import re
from datetime import datetime

sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import (
    config, logger, sessions, ipset, tc,
    network, firewall, route
)

log = logger.get("reload")


# ════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════

def _run(args, check=False, timeout=30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=check
        )
    except subprocess.TimeoutExpired:
        log.error(f"timeout: {' '.join(args)}")
        return subprocess.CompletedProcess(args, 1, "", "timeout")
    except Exception as e:
        log.error(f"error: {e}")
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _section(name: str):
    log.info(f"────── {name} ──────")


def _has_swanctl() -> bool:
    return (os.path.exists("/usr/sbin/swanctl") or
            os.path.exists("/usr/bin/swanctl"))


def _has_ipsec() -> bool:
    return (os.path.exists("/usr/sbin/ipsec") or
            os.path.exists("/usr/bin/ipsec"))


# ════════════════════════════════════════════════════════════
# Steps
# ════════════════════════════════════════════════════════════

def step_netplan(cfg: dict):
    """اعمال IP ها از config"""
    _section("netplan")
    
    iface = cfg.get("LAN_IFACE")
    ip = cfg.get("LAN_IP")
    cidr = cfg.get("LAN_CIDR", "24")
    
    if not iface or not ip:
        log.warning("LAN_IFACE or LAN_IP missing, skip")
        return
    
    if not network.iface_exists(iface):
        log.warning(f"iface {iface} not found, skip")
        return
    
    # IP
    _run(["ip", "addr", "flush", "dev", iface])
    _run(["ip", "addr", "add", f"{ip}/{cidr}", "dev", iface])
    _run(["ip", "link", "set", iface, "up"])
    
    # route
    network_lan = cfg.get("LAN_NETWORK")
    if network_lan:
        _run(["ip", "route", "replace", network_lan, "dev", iface])
    
    log.info(f"{iface}: {ip}/{cidr}")


def step_ipset(cfg: dict):
    """ipset ensure + restore"""
    _section("ipset")
    
    ipset.ensure_exists()
    
    backup = cfg.get("IPSET_BACKUP_FILE", "/etc/captive-portal-ipset.conf")
    if os.path.exists(backup):
        ipset.restore(backup)
        log.info(f"restored from {backup}")
    else:
        log.info("no backup")


def step_l2tp(cfg: dict):
    """راه‌اندازی L2TP"""
    _section("L2TP")
    
    l2tp_server = cfg.get("L2TP_SERVER")
    if not l2tp_server:
        log.warning("L2TP_SERVER missing, skip")
        return
    
    # ۱. route به L2TP
    route.add_l2tp_route(cfg)
    
    # ۲. IPsec config
    if _has_swanctl():
        _setup_swanctl(cfg)
    else:
        _setup_ipsec(cfg)
    
    # ۳. xl2tpd config
    _setup_xl2tpd(cfg)
    
    # ۴. ppp config
    _setup_ppp(cfg)
    
    # ۵. reload IPsec
    if _has_swanctl():
        _run(["swanctl", "--load-all"])
        log.info("swanctl reloaded")
    else:
        # فقط اگه فعال نیست، start کن
        r = _run(["systemctl", "is-active", "strongswan-starter"])
        if r.stdout.strip() != "active":
            _run(["systemctl", "start", "strongswan-starter"])
            time.sleep(3)
            log.info("strongswan-starter started")
        else:
            log.info("strongswan-starter already active")
    
    # ۶. ensure xl2tpd
    r = _run(["systemctl", "is-active", "xl2tpd"])
    if r.stdout.strip() != "active":
        _run(["systemctl", "start", "xl2tpd"])
        time.sleep(2)
        log.info("xl2tpd started")
    else:
        log.info("xl2tpd already active")
    
    # ۷. initiate IPsec
    if not _ipsec_established():
        log.info("initiating IPsec...")
        if _has_swanctl():
            _run(["swanctl", "--initiate", "--child", "L2TP-PSK-child"])
        elif _has_ipsec():
            _run(["ipsec", "up", "L2TP-PSK"])
        time.sleep(5)
    
    # ۸. connect L2TP
    _start_l2tp_tunnel(cfg)


def step_routing(cfg: dict):
    """policy routing"""
    _section("routing")
    route.setup_rt_tables(cfg)
    route.setup_policy_routing(cfg)
    route.setup_ppp_table(cfg)


def step_firewall(cfg: dict):
    """iptables"""
    _section("firewall")
    firewall.setup_all(cfg)


def step_dnsmasq(cfg: dict):
    """dnsmasq config"""
    _section("dnsmasq")
    _setup_dnsmasq(cfg)
    
    _run(["systemctl", "restart", "dnsmasq"])
    time.sleep(1)





def _supports_ap_mode(iface):
    """چک کن interface AP mode رو پشتیبانی می‌کنه"""
    try:
        r = _run(["iw", "list"], timeout=5)
        if "AP" not in r.stdout:
            return False
        return os.path.exists(f"/sys/class/net/{iface}")
    except Exception:
        return False


def _detect_wifi_ap_iface(cfg):
    """
    تشخیص خودکار USB WiFi adapter
    - فقط wlx* (USB) رو در نظر بگیر
    - چک کن AP mode رو پشتیبانی کنه
    """
    r = _run(["ip", "-br", "link", "show"])
    if r.returncode != 0:
        return None
    
    for line in r.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        iface = parts[0]
        
        # فقط wlx* (USB WiFi)
        if not iface.startswith("wlx"):
            continue
        
        # چک AP mode
        if _supports_ap_mode(iface):
            log.info(f"found USB WiFi AP: {iface}")
            return iface
    
    return None








def step_wifi(cfg: dict):
    """راه‌اندازی WiFi AP — همه چیز از config"""
    _section("WiFi")
    
    # ۱. WLX_IFACE
    wlx = cfg.get("WLX_IFACE")
    
    # detect خودکار اگه خالی
    if not wlx:
        wlx = _detect_wifi_ap_iface(cfg)
        if wlx:
            try:
                config.set("WLX_IFACE", wlx)
                log.info(f"auto-detected WLX_IFACE = {wlx}")
            except Exception as e:
                log.warning(f"cannot save WLX_IFACE: {e}")
    
    if not wlx:
        log.info("no WiFi AP interface found, skip")
        _run(["systemctl", "stop", "hostapd"], check=False)
        return
    
    if not network.iface_exists(wlx):
        log.warning(f"WLX iface {wlx} not found, skip")
        _run(["systemctl", "stop", "hostapd"], check=False)
        return
    
    # ۲. IP از config
    wlx_ip = cfg.get("WLX_IP")
    wlx_cidr = cfg.get("WLX_CIDR", "24")
    
    if not wlx_ip:
        log.error("WLX_IP not in config, skip")
        return
    
    # ۳. اعمال IP
    _run(["ip", "addr", "flush", "dev", wlx])
    _run(["ip", "addr", "add", f"{wlx_ip}/{wlx_cidr}", "dev", wlx])
    _run(["ip", "link", "set", wlx, "up"])
    log.info(f"{wlx}: {wlx_ip}/{wlx_cidr}")
    
    # ۴. hostapd config
    _setup_hostapd(cfg)
    
    # ۵. dnsmasq config
    _setup_wlx_dnsmasq(cfg)
    
    # ۶. restart
    _run(["systemctl", "restart", "hostapd"])
    _run(["systemctl", "restart", "dnsmasq"])
    
    log.info(f"WiFi AP ready: {wlx}")


def step_htb(cfg: dict):
    """HTB root"""
    _section("HTB")
    
    total_mbit = int(cfg.get("TOTAL_BW_MBIT", 70))
    
    for iface in network.list_lan_ifaces():
        if network.iface_exists(iface):
            tc.ensure_root(iface, total_mbit)




def step_apply_bw(cfg: dict):
    """
    اعمال bw برای همه session های connect
    - tc class + filter
    - baseline
    """
    _section("apply_bw")
    
    from lib import sessions, tc, network
    
    count = 0
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        if session.get("state") != "connect":
            log.debug(f"skip {ip} (state={session.get('state')})")
            continue
        
        # bw
        bw = session.get("bw_kbps")
        if bw is None:
            log.debug(f"skip {ip} (no bw)")
            continue
        try:
            bw_int = int(bw)
        except (TypeError, ValueError):
            log.warning(f"invalid bw for {ip}: {bw}")
            continue
        
        # iface
        iface = network.get_iface_for_ip(ip)
        if not iface:
            log.warning(f"no iface for {ip}")
            continue
        
        # apply_bw
        try:
            tc.apply_bw(ip, bw_int, iface)
            log.info(f"apply_bw {ip} → {bw_int} KB/s on {iface}")
            count += 1
        except Exception as e:
            log.error(f"apply_bw {ip} failed: {e}")
    
    log.info(f"applied bw for {count} sessions")


def step_reset_baseline(cfg: dict):
    """
    ریست baseline برای همه session های connect
    (چون tc reset شده)
    """
    _section("reset baseline")
    
    from lib import sessions, tc
    
    count = 0
    for ip in sessions.all_ips():
        session = sessions.get(ip)
        if not session:
            continue
        if session.get("state") != "connect":
            continue
        
        try:
            # baseline = tc فعلی (که 0 هست)
            baseline = tc.get_bytes(ip)
            sessions.set_field(ip, "baseline_bytes", baseline)
            # used_bytes = accumulated + (current - baseline) = 0
            sessions.set_field(ip, "used_bytes", session.get("accumulated_bytes", 0) or 0)
            count += 1
            log.info(f"reset {ip}: baseline={baseline}")
        except Exception as e:
            log.error(f"reset {ip} failed: {e}")
    
    log.info(f"reset baseline for {count} sessions")






def _get_gateway_for_iface(iface):
    """گرفتن gateway از route فعلی"""
    r = _run(["ip", "route", "show", "default"])
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if f"dev {iface}" in line:
            m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                return m.group(1)
    return None


def step_l2tp_out(cfg: dict):
    """مسیر L2TP output از WAN_IFACE (داینامیک)"""
    _section("l2tp_out")
    
    wan_iface = cfg.get("WAN_IFACE")
    l2tp_server = cfg.get("L2TP_SERVER")
    
    if not wan_iface or not l2tp_server:
        log.warning("WAN_IFACE or L2TP_SERVER missing, skip")
        return
    
    if not network.iface_exists(wan_iface):
        log.warning(f"WAN iface {wan_iface} not found, skip")
        return
    
    mark = int(cfg.get("L2TP_OUT_MARK", 200))
    table_id = int(cfg.get("L2TP_RT_TABLE", 200))
    table_name = cfg.get("L2TP_RT_TABLE_NAME", "l2tp-out")
    priority = int(cfg.get("L2TP_IP_RULE_PRIORITY", 200))
    
    # ۱. rt_tables
    rt_tables_path = cfg.get("RT_TABLES_FILE", "/etc/iproute2/rt_tables")
    try:
        with open(rt_tables_path) as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                parts = stripped.split()
                if parts and parts[0] == str(table_id):
                    continue
            new_lines.append(line)
        new_lines.append(f"{table_id}\t{table_name}\n")
        with open(rt_tables_path, "w") as f:
            f.writelines(new_lines)
        log.info(f"rt_tables: {table_id} {table_name}")
    except Exception as e:
        log.error(f"rt_tables error: {e}")
    
    # ۲. iptables MARK
    for chain, port_flag in [("OUTPUT", "--dport"), ("OUTPUT", "--sport"),
                              ("PREROUTING", "--dport"), ("PREROUTING", "--sport")]:
        _run(["iptables", "-t", "mangle", "-D", chain,
              "-p", "udp", port_flag, "1701",
              "-j", "MARK", "--set-mark", str(mark)], check=False)
    
    _run(["iptables", "-t", "mangle", "-A", "OUTPUT",
          "-p", "udp", "--dport", "1701",
          "-j", "MARK", "--set-mark", str(mark)])
    _run(["iptables", "-t", "mangle", "-A", "OUTPUT",
          "-p", "udp", "--sport", "1701",
          "-j", "MARK", "--set-mark", str(mark)])
    _run(["iptables", "-t", "mangle", "-A", "PREROUTING",
          "-p", "udp", "--dport", "1701",
          "-j", "MARK", "--set-mark", str(mark)])
    
    log.info(f"iptables MARK: UDP 1701 → {mark}")
    
    # ۳. ip rule
    while True:
        r = _run(["ip", "rule", "del", "fwmark", str(mark)])
        if r.returncode != 0:
            break
    while True:
        r = _run(["ip", "rule", "del", "priority", str(priority)])
        if r.returncode != 0:
            break
    
    _run(["ip", "rule", "add", "fwmark", str(mark),
          "lookup", str(table_id), "priority", str(priority)])
    log.info(f"ip rule: fwmark {mark} → table {table_id}")
    
    # ۴. route table
    _run(["ip", "route", "flush", "table", str(table_id)])
    
    wan_gateway = _get_gateway_for_iface(wan_iface)
    
    if wan_gateway:
        _run(["ip", "route", "replace", f"{l2tp_server}/32",
              "via", wan_gateway, "dev", wan_iface, "table", str(table_id)])
        log.info(f"table {table_id}: {l2tp_server} via {wan_gateway} dev {wan_iface}")
    else:
        _run(["ip", "route", "replace", f"{l2tp_server}/32",
              "dev", wan_iface, "table", str(table_id)])
        log.info(f"table {table_id}: {l2tp_server} dev {wan_iface}")




def step_api_route(cfg: dict):
    """route به API از WAN اصلی"""
    _section("api_route")
    
    api_host = cfg.get("API_HOST", "coreapi.linenet.online")
    wan_iface = cfg.get("WAN_IFACE")
    
    if not api_host or not wan_iface:
        log.warning("API_HOST or WAN_IFACE missing")
        return
    
    import socket
    try:
        api_ips = socket.getaddrinfo(api_host, 443, socket.AF_INET)
        api_ip = api_ips[0][4][0] if api_ips else None
    except Exception as e:
        log.warning(f"cannot resolve {api_host}: {e}")
        return
    
    if not api_ip:
        log.warning(f"no IP for {api_host}")
        return
    
    wan_gateway = _get_gateway_for_iface(wan_iface)
    
    if wan_gateway:
        _run(["ip", "route", "replace", f"{api_ip}/32",
              "via", wan_gateway, "dev", wan_iface])
        log.info(f"API route: {api_ip} via {wan_gateway} dev {wan_iface}")
    else:
        _run(["ip", "route", "replace", f"{api_ip}/32",
              "dev", wan_iface])
        log.info(f"API route: {api_ip} dev {wan_iface}")


def step_save(cfg: dict):
    """save ipset"""
    _section("save")
    
    backup = cfg.get("IPSET_BACKUP_FILE", "/etc/captive-portal-ipset.conf")
    ipset.save(backup)
    log.info(f"saved ipset to {backup}")


# ════════════════════════════════════════════════════════════
# Config Generators
# ════════════════════════════════════════════════════════════

def _setup_swanctl(cfg: dict):
    """ساخت /etc/swanctl/conf.d/l2tp.conf"""
    path = cfg.get("SWANCTL_CONF", "/etc/swanctl/conf.d/l2tp.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    l2tp_server = cfg.get("L2TP_SERVER")
    psk = cfg.get("IPSEC_PSK", "")
    
    content = f"""connections {{
    L2TP-PSK {{
        version = 1
        local_addrs = %any
        remote_addrs = {l2tp_server}
        local {{ auth = psk; id = %any }}
        remote {{ auth = psk; id = {l2tp_server} }}
        proposals = aes256-sha256-modp2048,aes128-sha256-modp2048,aes256-sha1-modp2048,aes128-sha1-modp2048
        children {{
            L2TP-PSK-child {{
                local_ts = dynamic[udp/l2f]
                remote_ts = dynamic[udp/l2f]
                mode = transport
                esp_proposals = aes128-sha1,aes256-sha1,aes128-sha256,aes256-sha256
                start_action = trap
            }}
        }}
    }}
}}
secrets {{
    ike-L2TP-PSK {{
        id = {l2tp_server}
        secret = "{psk}"
    }}
}}
"""
    
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o600)
    log.info(f"wrote {path}")





def _setup_ipsec(cfg: dict):
    """ساخت /etc/ipsec.conf — با left = IP WAN_IFACE"""
    l2tp_server = cfg.get("L2TP_SERVER")
    psk = cfg.get("IPSEC_PSK", "")
    wan_iface = cfg.get("WAN_IFACE")
    
    if not l2tp_server:
        log.error("L2TP_SERVER missing")
        return
    
    # ─── left = IP of WAN_IFACE ───
    left_ip = "%any"
    if wan_iface and network.iface_exists(wan_iface):
        ip = network.get_iface_ip(wan_iface)
        if ip:
            left_ip = ip
    
    log.info(f"IPsec left={left_ip} (WAN={wan_iface})")
    
    # /etc/ipsec.conf
    conf = f"""config setup
    charondebug="ike 1, knl 1, cfg 0"
    uniqueids=no

conn L2TP-PSK
    authby=secret
    keyexchange=ikev1
    type=transport
    left={left_ip}
    leftprotoport=17/1701
    right={l2tp_server}
    rightprotoport=17/1701
    auto=add
    ike=aes256-sha256-modp2048,aes128-sha256-modp2048,aes256-sha1-modp2048,aes128-sha1-modp2048
    esp=aes128-sha1,aes256-sha1,aes128-sha256,aes256-sha256
    dpdaction=restart
    dpddelay=30s
    dpdtimeout=120s
    rekey=yes
    ikelifetime=8h
    keylife=1h
"""
    with open("/etc/ipsec.conf", "w") as f:
        f.write(conf)
    
    # /etc/ipsec.secrets
    secrets = f'%any {l2tp_server} : PSK "{psk}"\n'
    with open("/etc/ipsec.secrets", "w") as f:
        f.write(secrets)
    os.chmod("/etc/ipsec.secrets", 0o600)
    
    log.info("wrote /etc/ipsec.conf and /etc/ipsec.secrets")


def _setup_xl2tpd(cfg: dict):
    """ساخت /etc/xl2tpd/xl2tpd.conf"""
    path = cfg.get("XL2TPD_CONF", "/etc/xl2tpd/xl2tpd.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    l2tp_server = cfg.get("L2TP_SERVER")
    l2tp_user = cfg.get("L2TP_USERNAME")
    lac_name = cfg.get("L2TP_LAC_NAME", "l2tp")
    ppp_options = cfg.get("PPP_OPTIONS_FILE", "/etc/ppp/options.l2tpd.client")
    
    content = f"""[global]
port = 1701
access control = no
debug tunnel = no
debug avp = no
debug network = no
debug state = no

[lac {lac_name}]
lns = {l2tp_server}
redial = yes
redial timeout = 5
max redials = 10
require chap = yes
refuse pap = yes
require authentication = yes
name = {l2tp_user}
ppp debug = no
pppoptfile = {ppp_options}
length bit = yes
"""
    
    with open(path, "w") as f:
        f.write(content)
    log.info(f"wrote {path}")


def _setup_ppp(cfg: dict):
    """ساخت /etc/ppp/options.l2tpd.client"""
    path = cfg.get("PPP_OPTIONS_FILE", "/etc/ppp/options.l2tpd.client")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    mtu = cfg.get("L2TP_MTU", 1280)
    mru = cfg.get("L2TP_MRU", 1280)
    user = cfg.get("L2TP_USERNAME")
    password = cfg.get("L2TP_PASSWORD")
    
    content = f"""ipcp-accept-local
ipcp-accept-remote
refuse-eap
require-mschap-v2
noccp
noauth
idle 1800
mtu {mtu}
mru {mru}
defaultroute
replacedefaultroute
usepeerdns
connect-delay 5000
name {user}
password {password}
"""
    
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o600)
    log.info(f"wrote {path}")


def _ipsec_established() -> bool:
    """چک IPsec SA (swanctl یا ipsec)"""
    if _has_swanctl():
        r = _run(["swanctl", "--list-sas"])
        if r.returncode == 0 and "ESTABLISHED" in r.stdout:
            return True
    if _has_ipsec():
        r = _run(["ipsec", "status"])
        if "ESTABLISHED" in r.stdout:
            return True
    return False





def _start_l2tp_tunnel(cfg: dict):
    """اتصال L2TP — با retry loop"""
    lac_name = cfg.get("L2TP_LAC_NAME", "l2tp")
    control = "/var/run/xl2tpd/l2tp-control"
    
    os.makedirs(os.path.dirname(control), exist_ok=True)
    _cleanup_ppp()
    
    try:
        with open(control, "w") as f:
            f.write(f"c {lac_name}\n")
        log.info(f"sent 'c {lac_name}' to xl2tpd")
    except Exception as e:
        log.error(f"cannot write {control}: {e}")
        return
    
    # retry loop (تا 30s)
    for i in range(10):
        time.sleep(3)
        if _ppp_exists():
            log.info(f"PPP interface up after {(i+1)*3}s")
            return
        log.debug(f"waiting for PPP... ({(i+1)*3}s)")
    
    log.warning("PPP interface not up after 30s")


def _cleanup_ppp():
    """حذف PPP های مرده"""
    r = _run(["ip", "-br", "link", "show"])
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            parts = line.split()
            if parts and parts[0].startswith("ppp"):
                iface = parts[0]
                if "UP" not in line:
                    _run(["ip", "link", "delete", iface])
                    log.info(f"deleted dead {iface}")


def _ppp_exists() -> bool:
    """آیا ppp داریم؟"""
    r = _run(["ip", "-br", "link", "show"])
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        parts = line.split()
        if parts and parts[0].startswith("ppp"):
            return True
    return False


def _setup_dnsmasq(cfg: dict):
    """ساخت /etc/dnsmasq.d/captive-lan.conf"""
    path = cfg.get("DNSMASQ_LAN_CONF", "/etc/dnsmasq.d/captive-lan.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    iface = cfg.get("LAN_IFACE")
    range_start = cfg.get("DHCP_RANGE_START")
    range_end = cfg.get("DHCP_RANGE_END")
    lease = cfg.get("DHCP_LEASE", "12h")
    lan_ip = cfg.get("LAN_IP")
    dns1 = cfg.get("DNS_PRIMARY", "8.8.8.8")
    dns2 = cfg.get("DNS_SECONDARY", "1.1.1.1")
    
    if not iface or not range_start:
        log.warning("LAN_IFACE or DHCP_RANGE missing")
        return
    
    content = f"""interface={iface}
bind-interfaces
dhcp-range={range_start},{range_end},255.255.255.0,{lease}
dhcp-option=3,{lan_ip}
dhcp-option=6,{lan_ip}

domain-needed
bogus-priv
no-resolv
server={dns1}
server={dns2}
cache-size=1000
except-interface=lo
no-hosts
"""
    
    with open(path, "w") as f:
        f.write(content)
    log.info(f"wrote {path}")







def _setup_wlx_dnsmasq(cfg: dict):
    """dnsmasq برای WLX — همه چیز از config"""
    path = cfg.get("DNSMASQ_WLX_CONF", "/etc/dnsmasq.d/captive-wlx.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    wlx = cfg.get("WLX_IFACE")
    wlx_ip = cfg.get("WLX_IP")
    range_start = cfg.get("WLX_DHCP_START")
    range_end = cfg.get("WLX_DHCP_END")
    
    if not wlx or not wlx_ip or not range_start or not range_end:
        log.warning("WLX config incomplete, skip dnsmasq")
        return
    
    content = f"""interface={wlx}
bind-interfaces
dhcp-range={range_start},{range_end},255.255.255.0,12h
dhcp-option=3,{wlx_ip}
dhcp-option=6,{wlx_ip}
"""
    
    with open(path, "w") as f:
        f.write(content)
    log.info(f"wrote {path}")


def _setup_hostapd(cfg: dict):
    """ساخت /etc/hostapd/hostapd.conf — صحیح"""
    path = cfg.get("HOSTAPD_CONF", "/etc/hostapd/hostapd.conf")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    wlx = cfg.get("WLX_IFACE")
    ssid = cfg.get("WLX_SSID", "WiFi")
    password = cfg.get("WLX_PASSWORD", "")
    channel = str(cfg.get("WLX_CHANNEL", "6"))
    hw_mode = cfg.get("WLX_HW_MODE", "g")
    
    lines = [
        f"interface={wlx}",
        "driver=nl80211",
        f"ssid={ssid}",
        f"hw_mode={hw_mode}",
        f"channel={channel}",
        "wmm_enabled=1",
        "macaddr_acl=0",
        "auth_algs=1",
        "ignore_broadcast_ssid=0",
    ]
    
    if password:
        # WPA2
        lines.append("wpa=2")
        lines.append(f"wpa_passphrase={password}")
        lines.append("wpa_key_mgmt=WPA-PSK")
        lines.append("wpa_pairwise=TKIP")
        lines.append("rsn_pairwise=CCMP")
    else:
        lines.append("wpa=0")
    
    content = "\n".join(lines) + "\n"
    
    with open(path, "w") as f:
        f.write(content)
    log.info(f"wrote {path}")



def main():
    log.info("═══════════════════════════════════")
    log.info("  RELOAD START")
    log.info("═══════════════════════════════════")
    
    config.reload()
    cfg = config.load()
    
    log.info(f"node: {cfg.get('NODE_ID')}")
    log.info(f"LAN: {cfg.get('LAN_IFACE')} ({cfg.get('LAN_IP')})")
    log.info(f"WAN: {cfg.get('WAN_IFACE')}")
    log.info(f"WLX: {cfg.get('WLX_IFACE') or 'none'}")
    
    try:
        step_netplan(cfg)
        step_ipset(cfg)
        step_l2tp(cfg)
        step_routing(cfg)
        step_firewall(cfg)
        step_l2tp_out(cfg)
        step_dnsmasq(cfg)
        step_wifi(cfg)
        step_htb(cfg)
        step_apply_bw(cfg)
        step_reset_baseline(cfg)
        step_save(cfg)
    except Exception as e:
        log.error(f"reload failed: {e}")
        import traceback
        log.error(traceback.format_exc())
        return 1
    
    log.info("═══════════════════════════════════")
    log.info("  RELOAD COMPLETE")
    log.info("═══════════════════════════════════")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
