#!/bin/bash
# ============================================================
# install.sh - نصب Captive Portal
# ============================================================
set -e

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="/opt/captive-portal"
SBIN_DIR="/usr/local/sbin"

echo "═══════════════════════════════════════"
echo "  Captive Portal Installer"
echo "  Source: $SRC_DIR"
echo "  Dest:   $DEST_DIR"
echo "═══════════════════════════════════════"

[[ $EUID -eq 0 ]] || { echo "❌ root required"; exit 1; }

# ۱. دایرکتوری‌ها
echo "[1/6] Creating directories..."
mkdir -p "$DEST_DIR"/{lib,services,scripts,bin,templates,static}
mkdir -p /var/lib/captive-portal
mkdir -p /var/log/captive-portal
mkdir -p /var/log/captive-usage
mkdir -p /var/run/captive-portal

# ۲. کپی فایل‌ها
echo "[2/6] Copying files..."
cp -a "$SRC_DIR/lib/"* "$DEST_DIR/lib/"
cp -a "$SRC_DIR/services/"* "$DEST_DIR/services/"
cp -a "$SRC_DIR/scripts/"* "$DEST_DIR/scripts/"

# ۳. config
echo "[3/6] Setting up config..."
if [[ ! -f "$DEST_DIR/config.conf" ]]; then
    if [[ -f "$SRC_DIR/config/config.conf.example" ]]; then
        cp "$SRC_DIR/config/config.conf.example" "$DEST_DIR/config.conf"
    elif [[ -f "$SRC_DIR/config/config.default.conf" ]]; then
        cp "$SRC_DIR/config/config.default.conf" "$DEST_DIR/config.conf"
    fi
    echo "  ✓ config.conf created"
else
    echo "  ⚠ config.conf already exists"
fi

# ۴. wrapper ها
echo "[4/6] Installing wrappers..."
cp "$SRC_DIR/bin/"* "$SBIN_DIR/"
chmod +x "$SBIN_DIR"/cp-*

# ۵. systemd
echo "[5/6] Installing systemd units..."
cp "$SRC_DIR/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

# ۶. enable
echo "[6/6] Enabling services..."
systemctl enable captive-portal 2>/dev/null || true
systemctl enable captive-portal-admin 2>/dev/null || true
systemctl enable session-monitor 2>/dev/null || true

# IP forwarding
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf || \
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1 > /dev/null

echo ""
echo "═══════════════════════════════════════"
echo "  ✅ Installation complete"
echo "═══════════════════════════════════════"
echo ""
echo "  Config:   $DEST_DIR/config.conf"
echo "  Reload:   cp-reload"
echo "  Status:   cp-status"
echo "  Portal:   http://<LAN_IP>:8080"
echo "  Admin:    http://<LAN_IP>:7575"
echo ""
