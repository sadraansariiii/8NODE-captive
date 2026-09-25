# Captive Portal + L2TP/IPsec

سیستم مدیریت کاربران اینترنت با پورتال لاگین، محدودیت پهنای باند، و تونل L2TP/IPsec.

## ✨ ویژگی‌ها

- 🔐 پورتال لاگین (Flask)
- 📊 پنل ادمین با تنظیمات داینامیک
- 🌐 تونل L2TP/IPsec با watchdog
- 📶 WiFi AP (hostapd) با auto-detect USB
- 🚦 محدودیت پهنای باند (tc/HTB)
- 📈 محاسبه مصرف real-time
- 🔄 Watchdog خودترمیم
- ⚙️ کاملاً داینامیک (config.conf)
- 🖥️ Multi-WAN (LTE / WiFi / Ethernet)
- 🔀 سوییچ VPN/Direct

## 🚀 نصب

```bash
git clone <REPO_URL>
cd captive-portal
nano config/config.conf
sudo ./install.sh
cp-status
🌐 پنل‌ها
پورتال: http://<LAN_IP>:8080

ادمین: http://<LAN_IP>:7575

📄 License
MIT
