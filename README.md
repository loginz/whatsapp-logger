# WhatsApp Group Chat Logger

独立 WhatsApp 群聊消息记录器。基于 `@whiskeysockets/baileys`，通过独立的 Baileys bridge 连接 WhatsApp，只记录群聊消息到本地文件，不发送任何回复。

## 架构

```
WhatsApp
   ↕ (WebSocket)
Baileys Bridge (Node.js, 端口 3001)
   ↕ HTTP (long-poll /messages)
logger.py (Python)
   ↓
~/.hermes/data/whatsapp-logger/
└── 2026-07/                  # 每月一个目录
    ├── 2026-07-11.md         # 每日一个记录文件
    └── attachments/          # 当月附件
        └── 2026-07-11/
            ├── photo_001.jpg
            ├── video_001.mp4
            └── ...
```

与 Hermes 使用**独立的 bridge 实例**（不同端口、不同 session 目录），互不干扰。

## 文件说明

| 文件 | 说明 |
|------|------|
| `bridge/` | Baileys bridge (Node.js)，复制自 Hermes |
| `logger.py` | 主程序：管理 bridge 进程、轮询消息、保存到文件 |
| `install.sh` | 一键安装脚本 |
| `whatsapp-logger.service` | systemd 服务 |
| `QUICKSTART.md` | 安装、扫码、后台运行和重新连接的快速指南 |

## 安装步骤

```bash
cd ~/devel/whatsapp-logger
./install.sh
```

`install.sh` 做了四件事：

| 步骤 | 做了什么 |
|------|---------|
| 1. 检查 Node.js | 确认 `node` 命令存在，版本 v18+ |
| 2. 安装 bridge 依赖 | 在 `bridge/` 目录下执行 `npm install`，安装 `@whiskeysockets/baileys`、`express`、`qrcode-terminal`、`pino` 等 npm 包 |
| 3. 创建数据目录 | 创建日志根目录和 `~/.hermes/whatsapp-logger/session/`；月份目录在收到消息时自动创建 |
| 4. 安装 systemd 服务 | 把 `whatsapp-logger.service` 复制到 `~/.config/systemd/user/`，替换路径占位符，执行 `daemon-reload` |

## 启动方法

### 首次启动（需要扫码认证）

```bash
cd ~/devel/whatsapp-logger
python3 logger.py
```

首次启动时，bridge 会在终端打印一个 QR 码：

```
█▀▀▀▀▀█ ▄▀█ ▀▄▀ █▄▀▄▀█ █▀▀▀▀▀█
█ ███ █ █▀ █▀▄▀▄▀ █▄▄█ █ ███ █
█ ▀▀▀ █ █▄█▄▀▄▀ ██▀▄▄▀ █ ▀▀▀ █
▀▀▀▀▀▀▀ ▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀ ▀▀▀▀▀▀▀
```

用 WhatsApp → 设置 → 已链接设备 → 扫描 QR 码。

bridge 启动后会显示 HTTP 服务状态，并在同一终端打印二维码。扫码成功后会显示
`✅ WhatsApp connected!`，随后开始记录消息。

认证信息持久保存在 `~/.hermes/whatsapp-logger/session/`。正常停止或重启服务不会要求
重新扫码；只有 WhatsApp 主动注销该链接设备，或移走 session 目录后才需要重新认证。

### 重新连接或更换 WhatsApp 账号

先停止后台服务，并把当前 session 改名备份：

```bash
systemctl --user stop whatsapp-logger
mv ~/.hermes/whatsapp-logger/session ~/.hermes/whatsapp-logger/session.backup
python3 ~/devel/whatsapp-logger/logger.py
```

在终端扫描新的二维码。确认出现 `WhatsApp connected!` 后按 `Ctrl+C`，再启动后台服务：

```bash
systemctl --user start whatsapp-logger
```

如果 `session.backup` 已存在，请换一个备份名称，例如 `session.backup-2026-07-11`。确认新账号
工作正常后，可自行删除旧备份。若要恢复旧账号，则停止服务，移走当前 `session`，再把旧备份
改名回 `session`。

### 使用 systemd 管理（扫码认证后）

```bash
# 先 Ctrl+C 停止前台进程
# 启动服务
systemctl --user start whatsapp-logger

# 设置开机启动
systemctl --user enable whatsapp-logger

# 查看状态
systemctl --user status whatsapp-logger

# 查看实时日志
journalctl --user -u whatsapp-logger -f

# 停止
systemctl --user stop whatsapp-logger

# 重启
systemctl --user restart whatsapp-logger
```

## 输出格式

日志文件在 `~/.hermes/data/whatsapp-logger/YYYY-MM/YYYY-MM-DD.md`：

```markdown
# 群聊消息 - 2026-07-11

## 10:30:01 Normanton Park 住户群

**张三** (10:30:01):
今天电梯维修，请大家注意

## 10:32:15 Normanton Park 住户群

**李四** (10:32:15):
好的，大概几点恢复？
![photo](attachments/2026-07-11/photo_001.jpg)

## 10:35:00 Normanton Park 住户群

**管理员** (10:35:00):
预计下午3点
```

媒体文件保存在 `~/.hermes/data/whatsapp-logger/YYYY-MM/attachments/YYYY-MM-DD/`，Markdown 中使用相对路径引用。

## 配置

### 命令行参数

```bash
# 修改端口（如果 3001 被占用）
python3 logger.py --port 3002

# 修改日志和附件输出目录
python3 logger.py --log-dir /path/to/logs

# 修改 bridge 数据目录（session + 媒体缓存）
python3 logger.py --data-dir /path/to/bridge-data

# 所有参数一起
python3 logger.py --port 3002 --log-dir /data/logs --data-dir /data/bridge
```

### 环境变量

支持三个环境变量，与命令行参数对应：

| 环境变量 | 对应参数 | 默认值 |
|---------|---------|--------|
| `WHATSAPP_LOGGER_PORT` | `--port` | `3001` |
| `WHATSAPP_LOGGER_LOG_DIR` | `--log-dir` | `~/.hermes/data/whatsapp-logger` |
| `WHATSAPP_LOGGER_DATA_DIR` | `--data-dir` | `~/.hermes/whatsapp-logger` |

logger 启动的 bridge 仅监听 `127.0.0.1`，默认端口为 `3001`。logger 通过该端口的
`/messages` 接口获取消息。这个专用实例默认记录所有群成员（包括链接账号自己）发出的
群消息；它不调用发送接口，也不会回复消息。

```bash
# 通过环境变量配置
export WHATSAPP_LOGGER_LOG_DIR=/data/logs
export WHATSAPP_LOGGER_DATA_DIR=/data/bridge
python3 logger.py
```

### 配合 systemd 使用自定义路径

安装时通过环境变量传递给 `install.sh`：

```bash
WHATSAPP_LOGGER_LOG_DIR=/data/logs WHATSAPP_LOGGER_DATA_DIR=/data/bridge ./install.sh
```

systemd 服务会自动使用这些路径。

## 配合 Hermes

在 Hermes 的 Telegram adapter 配置中设置 `require_mention: true`，bot 就不会在群里主动搭话：

```yaml
# config.yaml
gateway:
  platforms:
    telegram:
      extra:
        require_mention: true
```

WhatsApp 侧同理，设置 `require_mention: true`。这样 bot 只回复被 @ 的消息，logger 独立记录所有群聊消息。
