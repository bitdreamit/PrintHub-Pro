#!/usr/bin/env bash
# ============================================================
#  AdvPrint Pro - Unix uninstall  (v1.2.0)
#  Removes every auto-run registration and stops the hub.
#  Does NOT delete your print data in ~/.advprint
# ============================================================
OS="$(uname -s)"

echo "[..] Removing auto-run registrations ..."

# systemd user service (Linux)
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now advprint 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/advprint.service"
    systemctl --user daemon-reload 2>/dev/null || true
fi

# LaunchAgent (macOS)
PLIST="$HOME/Library/LaunchAgents/com.bitdream.it.advprint.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
fi

# XDG autostart (desktop Linux fallback)
rm -f "$HOME/.config/autostart/advprint.desktop"
rm -f "$HOME/.advprint/start-hub.sh"

# stop any hub still running on the port
if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -ti tcp:9235 -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
        echo "[OK] Hub on port 9235 stopped"
    fi
fi

echo "[OK] AdvPrint Pro uninstalled."
echo "     Print data kept in ~/.advprint - delete it manually if you want:"
echo "       rm -rf ~/.advprint"
echo "     Remove the Chrome extension in chrome://extensions"
