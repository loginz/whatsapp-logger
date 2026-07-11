#!/usr/bin/env bash
# WhatsApp Group Chat Logger — 一键安装脚本
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$APP_DIR/bridge"
SERVICE_NAME="whatsapp-logger"

# 默认路径
DEFAULT_LOG_DIR="$HOME/.hermes/data/whatsapp-logger"
DEFAULT_DATA_DIR="$HOME/.hermes/whatsapp-logger"

# 可配置
LOG_DIR="${WHATSAPP_LOGGER_LOG_DIR:-$DEFAULT_LOG_DIR}"
DATA_DIR="${WHATSAPP_LOGGER_DATA_DIR:-$DEFAULT_DATA_DIR}"

echo "=== WhatsApp Logger 安装 ==="
echo ""

# 1. 检查 Node.js
if ! command -v node &>/dev/null; then
    echo "❌ 未找到 Node.js，请先安装 Node.js (v18+)"
    echo "   推荐: https://nodejs.org 或 nvm"
    exit 1
fi
echo "✅ Node.js: $(node --version)"

# 2. 安装 bridge 依赖
echo ""
echo "安装 bridge 依赖..."
cd "$BRIDGE_DIR"
npm install --no-audit --no-fund 2>&1 | tail -1
echo "✅ Bridge 依赖已安装"

# 3. 创建数据目录
SESSION_DIR="$DATA_DIR/session"
mkdir -p "$LOG_DIR" "$SESSION_DIR"
echo "✅ 日志目录: $LOG_DIR"
echo "✅ Session 目录: $SESSION_DIR"
echo ""
echo "   可通过环境变量自定义路径:"
echo "     WHATSAPP_LOGGER_LOG_DIR  - 日志和附件目录 (默认: $DEFAULT_LOG_DIR)"
echo "     WHATSAPP_LOGGER_DATA_DIR - bridge session/cache 目录 (默认: $DEFAULT_DATA_DIR)"

# 4. 安装 systemd 服务
SERVICE_SRC="$APP_DIR/$SERVICE_NAME.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME.service"

if [ -f "$SERVICE_SRC" ]; then
    mkdir -p "$(dirname "$SERVICE_DST")"
    cp "$SERVICE_SRC" "$SERVICE_DST"
    # 替换路径占位符
    sed -i "s|{{APP_DIR}}|$APP_DIR|g" "$SERVICE_DST"
    sed -i "s|{{LOG_DIR}}|$LOG_DIR|g" "$SERVICE_DST"
    sed -i "s|{{DATA_DIR}}|$DATA_DIR|g" "$SERVICE_DST"
    systemctl --user daemon-reload 2>/dev/null || true
    echo ""
    echo "✅ Systemd 服务已安装: $SERVICE_NAME"
    echo ""
    echo "   启动: systemctl --user start $SERVICE_NAME"
    echo "   启用开机启动: systemctl --user enable $SERVICE_NAME"
    echo "   查看日志: journalctl --user -u $SERVICE_NAME -f"
fi

echo ""
echo "=== 安装完成 ==="
echo ""
echo "首次启动需要扫码认证:"
echo "  python3 $APP_DIR/logger.py"
echo ""
echo "扫码成功后 Ctrl+C 停止，然后用 systemd 管理:"
echo "  systemctl --user start $SERVICE_NAME"
echo ""
echo "自定义路径启动示例:"
echo "  WHATSAPP_LOGGER_LOG_DIR=/path/to/logs WHATSAPP_LOGGER_DATA_DIR=/path/to/data python3 $APP_DIR/logger.py"
