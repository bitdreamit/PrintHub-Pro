#!/usr/bin/env bash
# ============================================================
#  PrintHub Pro - Unix uninstall  (v1.2.0)
#  Removes every auto-run registration and stops the hub.
#  Does NOT delete your print data in ~/.printhub
# ============================================================
OS="$(uname -s)"

echo "[..] Removing auto-run registrations ..."

# systemd user service (Linux)
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now printhub 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/printhub.service"
    systemctl --user daemon-reload 2>/dev/null || true
fi

# LaunchAgent (macOS)
PLIST="$HOME/Library/LaunchAgents/com.bitdream.it.printhub.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
fi

# XDG autostart (desktop Linux fallback)
rm -f "$HOME/.config/autostart/printhub.desktop"
rm -f "$HOME/.printhub/start-hub.sh"

# stop any hub still running on the port
if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -ti tcp:9235 -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
        echo "[OK] Hub on port 9235 stopped"
    fi
fi

echo "[OK] PrintHub Pro uninstalled."
echo "     Print data kept in ~/.printhub - delete it manually if you want:"
echo "       rm -rf ~/.printhub"
echo "     Remove the Chrome extension in chrome://extensions"
