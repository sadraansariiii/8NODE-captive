#!/bin/bash
# ============================================================
# uninstall.sh - حذف کامل Captive Portal
# ============================================================
set +e

echo "⚠️  این همه چیز captive portal رو پاک می‌کنه!"
read -p "مطمئنی؟ (yes/no): " confirm
[[ "$confirm" != "yes" ]] && { echo "لغو شد"; exit 0; }

echo ""
echo "[1/6] Stopping services..."

SERVICES=(
    captive-portal
    captive-portal-admin
    session-monitor
    l2tp-watchdog
    portal-watchdog
)

for svc in "${SERVICES[@]}"; do
    systemctl stop "$svc" 2>/dev/null
    systemctl disable "$svc" 2>/dev/null
done

echo "[2/6] Killing processes..."
pkill -9 -f session_monitor 2>/dev/null
pkill -9 -f portal.py 2>/dev/null
pkill -9 -f admin.py 2>/dev/null
pkill -9 -f l2tp-watchdog 2>/dev/null
pkill -9 -f portal-watchdog 2>/dev/null
sleep 1

echo "[3/6] Cleaning network..."
# iptables
iptables -t nat -F 2>/dev/null
iptables -t mangle -F 2>/dev/null
iptables -F 2>/dev/null
iptables -t nat -X 2>/dev/null
iptables -t mangle -X 2>/dev/null
iptables -P INPUT ACCEPT 2>/dev/null
iptables -P FORWARD ACCEPT 2>/dev/null

# ipset
ipset destroy authorized_clients 2>/dev/null

# tc
for iface in $(ip -br link show | awk '{print $1}' | grep -vE '^(lo|ppp)'); do
    tc qdisc del dev "$iface" root 2>/dev/null
done

# ip rule
ip rule del fwmark 100 2>/dev/null
ip route flush table 100 2>/dev/null

# PPP
for ppp in $(ip -br link show 2>/dev/null | awk '{print $1}' | grep -E '^ppp[0-9]+$'); do
    ip link delete "$ppp" 2>/dev/null
done

echo "[4/6] Removing files..."
rm -rf /opt/captive-portal
rm -rf /opt/captive-portal-src
rm -f /usr/local/sbin/cp-*

echo "[5/6] Removing systemd units..."
for svc in "${SERVICES[@]}"; do
    rm -f "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
systemctl reset-failed

echo "[6/6] Removing configs and data..."
rm -f /etc/dnsmasq.d/captive-*.conf
rm -f /etc/swanctl/conf.d/l2tp.conf
rm -f /etc/xl2tpd/xl2tpd.conf
rm -f /etc/ppp/options.l2tpd.client
rm -f /etc/captive-portal-ipset.conf
rm -f /etc/iptables/rules.v4
rm -rf /var/lib/captive-portal
rm -rf /var/log/captive-portal
rm -rf /var/log/captive-usage
rm -rf /var/run/captive-portal

# rt_tables
sed -i '/^100[[:space:]]*ppp/d' /etc/iproute2/rt_tables

echo ""
echo "✅ حذف کامل شد"
echo ""
