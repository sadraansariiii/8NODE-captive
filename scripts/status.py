#!/usr/bin/env python3
"""
status.py - System Status CLI
"""
import os
import sys
import subprocess
import argparse

sys.path.insert(0, "/opt/captive-portal-src")
sys.path.insert(0, "/opt/captive-portal")

from lib import config
config.reload()
config.load()

from lib import sessions, ipset, tc, network, api, limits

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def ok(s): return f"{GREEN}✅ {s}{RESET}"
def fail(s): return f"{RED}❌ {s}{RESET}"
def warn(s): return f"{YELLOW}⚠️  {s}{RESET}"
def info(s): return f"{CYAN}ℹ️  {s}{RESET}"

def header(text):
    print(f"\n{BOLD}{'═' * 50}{RESET}")
    print(f"{BOLD}  {text}{RESET}")
    print(f"{BOLD}{'═' * 50}{RESET}")

def section(text):
    print(f"\n{BOLD}▶ {text}{RESET}")
    print("─" * 50)


def _run(args, timeout=5):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 127:
            return None
        return r
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _check_ipsec():
    """چک IPsec (swanctl یا ipsec قدیم)"""
    r = _run(["swanctl", "--list-sas"])
    if r is not None and r.returncode == 0:
        return ("ESTABLISHED" in r.stdout), "swanctl"
    r = _run(["ipsec", "status"])
    if r is not None:
        return ("ESTABLISHED" in r.stdout), "ipsec"
    return None, "no ipsec/swanctl"


def show_identity():
    section("Identity")
    print(f"  NODE_ID:    {config.get('NODE_ID', '-')}")
    print(f"  NODE_NAME:  {config.get('NODE_NAME', '-')}")
    print(f"  VERSION:    {config.get('NODE_VERSION', '-')}")


def show_network():
    section("Network")
    
    for label, key in [("LAN", "LAN_IFACE"), ("WAN", "WAN_IFACE"), ("WLX", "WLX_IFACE")]:
        iface = config.get(key)
        if not iface:
            if key == "WLX_IFACE":
                print(f"  {label}:  {info('disabled')}")
            continue
        
        exists = network.iface_exists(iface)
        ip = network.get_iface_ip(iface) if exists else None
        
        if exists and ip:
            print(f"  {label}:  {ok(f'{iface} → {ip}')}")
        elif exists:
            print(f"  {label}:  {warn(f'{iface} (no IP)')}")
        else:
            print(f"  {label}:  {fail(f'{iface} (not found)')}")
    
    route = network.get_default_route()
    if route:
        print(f"  GW:   {ok(route.get('gateway'))} dev {route.get('iface')}")
    else:
        print(f"  GW:   {fail('no default route')}")


def show_tunnel():
    section("Tunnel (L2TP)")
    
    ppp = None
    for iface in network.list_ifaces():
        if iface.startswith("ppp"):
            ppp = iface
            break
    
    if ppp:
        ip = network.get_iface_ip(ppp)
        print(f"  PPP:  {ok(ppp)} → {ip or '-'}")
    else:
        print(f"  PPP:  {fail('no PPP interface')}")
    
    established, method = _check_ipsec()
    if established is True:
        print(f"  IPsec: {ok(f'established ({method})')}")
    elif established is False:
        print(f"  IPsec: {fail(f'not established ({method})')}")
    else:
        print(f"  IPsec: {warn(method)}")


def show_routing():
    section("Routing")
    
    mark = config.get("FW_MARK", 100)
    table_id = config.get("RT_TABLE_ID", 100)
    
    r = _run(["ip", "rule", "show"])
    if r and f"fwmark 0x{int(mark):x}" in r.stdout:
        print(f"  ip rule: {ok(f'fwmark {mark}')}")
    elif r:
        print(f"  ip rule: {warn('fwmark rule not found')}")
    else:
        print(f"  ip rule: {fail('cannot run ip')}")
    
    r = _run(["ip", "route", "show", "table", str(table_id)])
    if r and "default" in r.stdout:
        print(f"  table {table_id}: {ok('default route exists')}")
    elif r:
        print(f"  table {table_id}: {warn('empty')}")
    else:
        print(f"  table {table_id}: {fail('cannot query')}")


def show_firewall():
    section("Firewall")
    
    n = ipset.count()
    if n > 0:
        print(f"  ipset: {ok(f'{n} entries')}")
    else:
        print(f"  ipset: {info('empty')}")
    
    r = _run(["iptables", "-L", "INPUT", "-n"])
    if r and "policy DROP" in r.stdout:
        print(f"  iptables: {ok('configured')}")
    elif r:
        print(f"  iptables: {warn('not configured (ACCEPT policy)')}")
    else:
        print(f"  iptables: {fail('cannot run')}")


def show_sessions():
    section("Sessions")
    
    sess = sessions.load()
    n = len(sess)
    
    if n == 0:
        print(f"  {info('no active sessions')}")
        return
    
    print(f"  Total: {n}\n")
    
    for ip, s in sess.items():
        username = s.get("username", "-")
        state = s.get("state", "-")
        used = limits.get_used_mb(ip)
        time_left = limits.get_time_left(ip)
        
        if state == "connect":
            state_str = ok(state)
        elif state == "sleep":
            state_str = warn(state)
        elif state == "pending":
            state_str = info(state)
        else:
            state_str = state
        
        print(f"  {ip:18} {username:15} {state_str}")
        print(f"    used={used:.1f}MB", end="")
        if time_left is not None:
            h = time_left // 3600
            m = (time_left % 3600) // 60
            print(f"  time_left={h}h {m}m", end="")
        print()


def show_services():
    section("Services")
    
    services = [
        "captive-portal",
        "captive-portal-admin",
        "session-monitor",
        "l2tp-watchdog",
        "portal-watchdog",
        "dnsmasq",
        "xl2tpd",
    ]
    
    for svc in services:
        r = _run(["systemctl", "is-active", svc])
        if r is None:
            continue
        r2 = _run(["systemctl", "list-unit-files", f"{svc}.service"])
        if r2 and r2.returncode == 0 and svc not in r2.stdout:
            continue
        active = r.stdout.strip() == "active"
        if active:
            print(f"  {ok(svc)}")
        else:
            print(f"  {fail(svc)}")


def show_api():
    section("API")
    
    base = config.get("API_BASE", "")
    if not base:
        print(f"  {fail('API_BASE not configured')}")
        return
    
    if api.is_alive():
        print(f"  {ok(base)}")
    else:
        print(f"  {fail(base)}")


def main():
    parser = argparse.ArgumentParser(description="Captive Portal Status")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sessions", action="store_true")
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    
    if args.json:
        import json
        print(json.dumps({
            "node_id": config.get("NODE_ID"),
            "sessions": sessions.count(),
            "ipset": ipset.count(),
            "api_alive": api.is_alive(),
        }, indent=2))
        return
    
    if args.sessions:
        show_sessions()
        return
    
    if args.network:
        show_network()
        return
    
    header("Captive Portal Status")
    show_identity()
    show_api()
    show_network()
    show_tunnel()
    show_routing()
    show_firewall()
    show_sessions()
    show_services()
    print()


if __name__ == "__main__":
    main()
