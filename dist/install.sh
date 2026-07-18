#!/usr/bin/env bash
# WhatsApp Group Chat Logger — interactive install script
#
# Default layout (flat layout under the install dir):
#   ~/service/whatsapp-logger/
#   ├── logger.py
#   ├── bridge/
#   ├── install.sh, *.service, *.md
#   ├── config.json        # written by logger.py
#   ├── session/           # Baileys pairing credentials
#   ├── cache/            # media cache
#   └── logs/             # default chat records root (configurable)
set -euo pipefail

SERVICE_NAME="whatsapp-logger"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_INSTALL_DIR="$HOME/service/whatsapp-logger"
DEFAULT_LOG_DIR=""  # placeholder, computed after install dir is set

# ── Helpers ─────────────────────────────────────────────────────────────
ask() {
    local prompt="$1"
    local default="${2:-}"
    local reply
    if [ -n "$default" ]; then
        read -rp "$prompt [$default]: " reply
        echo "${reply:-$default}"
    else
        read -rp "$prompt: " reply
        echo "$reply"
    fi
}

echo "=== WhatsApp Logger Installation ==="
echo ""

# 1. Check Node.js
if ! command -v node &>/dev/null; then
    echo "❌ Node.js not found. Please install Node.js v18+ first."
    echo "   https://nodejs.org or nvm"
    exit 1
fi
echo "✅ Node.js: $(node --version)"
echo ""

# 2. Ask for install directory
INSTALL_DIR="${WHATSAPP_LOGGER_INSTALL_DIR:-$(ask "Install directory" "$DEFAULT_INSTALL_DIR")}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"   # expand ~
INSTALL_DIR="$(cd "$INSTALL_DIR" 2>/dev/null && pwd || echo "$INSTALL_DIR")"

if [ -e "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    echo "⚠  Target directory not empty: $INSTALL_DIR"
    confirm="$(ask "  Overwrite? Existing code will be replaced (session/cache/logs/config.json preserved) [y/N]" "N")"
    if [[ ! "${confirm,,}" =~ ^y(es)?$ ]]; then
        echo "Cancelled."
        exit 1
    fi
fi
DEFAULT_LOG_DIR="$INSTALL_DIR/logs"

# 3. Ask for chat records directory
LOG_DIR="${WHATSAPP_LOGGER_LOG_DIR:-$(ask "Chat records directory" "$DEFAULT_LOG_DIR")}"
LOG_DIR="${LOG_DIR/#\~/$HOME}"

echo ""
echo "── Paths ──"
echo "  Code directory:    $INSTALL_DIR"
echo "  Chat records dir:  $LOG_DIR"
echo "  Session/Cache/Config: co-located with code (flat layout)"
echo ""

# 4. Copy source code
echo "Copying source to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
if command -v rsync &>/dev/null; then
    rsync -a --delete \
        --exclude='.git/' \
        --exclude='__pycache__/' \
        --exclude='node_modules/' \
        --exclude='session/' \
        --exclude='cache/' \
        --exclude='logs/' \
        --exclude='config.json' \
        --exclude='*.pyc' \
        "$SRC_DIR/" "$INSTALL_DIR/"
else
    cp -r "$SRC_DIR/." "$INSTALL_DIR/"
    rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/__pycache__" \
           "$INSTALL_DIR/bridge/node_modules" \
           "$INSTALL_DIR/session" "$INSTALL_DIR/cache" \
           "$INSTALL_DIR/logs" "$INSTALL_DIR/config.json" 2>/dev/null || true
fi
echo "✅ Source code copied"

# 5. Install bridge dependencies
BRIDGE_DIR="$INSTALL_DIR/bridge"
if [ ! -f "$BRIDGE_DIR/package.json" ]; then
    echo "❌ bridge directory missing: $BRIDGE_DIR"
    exit 1
fi
echo ""
echo "Installing bridge dependencies..."
( cd "$BRIDGE_DIR" && npm install --no-audit --no-fund 2>&1 | tail -1 )
echo "✅ Bridge dependencies installed"

# 6. Create runtime directories
mkdir -p "$LOG_DIR" "$INSTALL_DIR/session" \
         "$INSTALL_DIR/cache/images" "$INSTALL_DIR/cache/documents" \
         "$INSTALL_DIR/cache/audio" "$INSTALL_DIR/cache/video"
echo "✅ Chat records directory: $LOG_DIR"
echo "✅ Session directory:      $INSTALL_DIR/session"

# 7. Detect old paths (hint only, no migration)
OLD_DATA_DIR="$HOME/.hermes/whatsapp-logger"
OLD_LOG_DIR="$HOME/.hermes/data/whatsapp-logger"
if [ -d "$OLD_DATA_DIR/session" ] && [ "$(ls -A "$OLD_DATA_DIR/session" 2>/dev/null)" ]; then
    echo ""
    echo "ℹ  Old session detected: $OLD_DATA_DIR/session"
    echo "   New installation uses $INSTALL_DIR/session. No automatic migration."
    echo "   To reuse old credentials:"
    echo "     cp -a $OLD_DATA_DIR/session/. $INSTALL_DIR/session/"
fi
if [ -d "$OLD_LOG_DIR" ] && [ "$(ls -A "$OLD_LOG_DIR" 2>/dev/null)" ]; then
    echo ""
    echo "ℹ  Old logs detected: $OLD_LOG_DIR"
    echo "   New logs go to $LOG_DIR. Old logs left in place."
fi

# 8. Install systemd service
SERVICE_SRC="$INSTALL_DIR/$SERVICE_NAME.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME.service"

if [ -f "$SERVICE_SRC" ]; then
    mkdir -p "$(dirname "$SERVICE_DST")"
    cp "$SERVICE_SRC" "$SERVICE_DST"
    # Collect bin directories for node and python3. systemd user services get
    # a minimal PATH (/usr/bin:/bin) by default, so tools installed via nvm,
    # pyenv, asdf, homebrew, etc. are invisible unless we inject them here.
    extra_paths=()
    for tool in node npm python3; do
        bin_path="$(command -v "$tool" 2>/dev/null | xargs dirname 2>/dev/null)"
        if [ -n "$bin_path" ] && [ -d "$bin_path" ]; then
            seen=0
            for p in "${extra_paths[@]:-}"; do
                if [ "$p" = "$bin_path" ]; then seen=1; break; fi
            done
            if [ "$seen" -eq 0 ]; then
                extra_paths+=("$bin_path")
            fi
        fi
    done
    EXTRA_PATH=""
    for p in "${extra_paths[@]:-}"; do
        if [ -n "$EXTRA_PATH" ]; then
            EXTRA_PATH="$EXTRA_PATH:$p"
        else
            EXTRA_PATH="$p"
        fi
    done
    if [ -z "$EXTRA_PATH" ]; then
        echo "⚠  Could not resolve node/python3 paths. Service PATH may need manual adjustment."
        EXTRA_PATH="/usr/local/bin"
    fi
    # Render placeholders
    sed -i "s|{{APP_DIR}}|$INSTALL_DIR|g" "$SERVICE_DST"
    sed -i "s|{{LOG_DIR}}|$LOG_DIR|g" "$SERVICE_DST"
    sed -i "s|{{EXTRA_PATH}}|$EXTRA_PATH|g" "$SERVICE_DST"
    systemctl --user daemon-reload 2>/dev/null || true
    echo ""
    echo "✅ Systemd service installed: $SERVICE_NAME"
    echo "   Service PATH prefix: $EXTRA_PATH"
else
    echo "⚠  $SERVICE_SRC not found, skipping systemd service installation"
fi

# 9. Final instructions
echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1) Pair a WhatsApp account and configure groups:"
echo "       python3 $INSTALL_DIR/logger.py config account"
echo "       After pairing, the service starts and group selection opens automatically."
echo ""
echo "  2) Verify the service is active:"
echo "       systemctl --user status $SERVICE_NAME"
echo "       journalctl --user -u $SERVICE_NAME -f"
