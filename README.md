# WhatsApp Group Chat Logger

独立 WhatsApp 群聊消息记录器。基于 `@whiskeysockets/baileys`，通过独立的 Baileys bridge 连接 WhatsApp，只记录群聊消息到本地文件，不发送任何回复。

## 架构

```
WhatsApp
   ↕ (WebSocket)
Baileys Bridge (Node.js, 端口 3001)
   ↕ HTTP (long-poll /messages)
logger.js (Node.js)
   ↓
<安装目录>/logs/
├── groups_index.md              # 顶层索引
└── groups/<群ID>/
    ├── <YYYY-MM>.md             # 单群单月记录
    ├── <YYYY-MM>.jsonl          # JSONL sidecar
    └── attachments/<YYYY-MM-DD>/
```

与 Hermes 使用**独立的 bridge 实例**（不同端口、不同 session 目录），互不干扰。

## 目录布局（平铺）

安装后所有代码和运行时数据都在同一目录下（默认 `~/service/whatsapp-logger/`）：

```
~/service/whatsapp-logger/
├── logger.js                # 主程序（含 config account / config group / run 三个子命令）
├── bridge/                  # Baileys bridge (Node.js)
│   ├── bridge.js
│   ├── bridge_helpers.js
│   └── package.json
├── install.sh
├── whatsapp-logger.service
├── README.md / QUICKSTART.md / PROGRESS.md
├── config.json              # 群组过滤配置（由 `logger config` 写入，logger run 热加载）
├── session/                 # Baileys pairing 凭据
├── cache/                   # 媒体缓存
│   ├── images/  documents/  audio/  video/
└── logs/                    # 日志输出根目录（安装时可改）
    ├── groups_index.md      # 顶层群组索引
    └── groups/
        └── <群ID>/
            ├── <YYYY-MM>.md       # 单群单月 Markdown
            ├── <YYYY-MM>.jsonl    # 单群单月 JSONL
            └── attachments/<YYYY-MM-DD>/
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `logger.js` | 主程序：config account / config group / run 三个子命令 |
| `bridge/` | Baileys bridge (Node.js) |
| `install.sh` | 一键安装脚本（交互式） |
| `whatsapp-logger.service` | systemd 服务模板（含 `{{APP_DIR}}` / `{{LOG_DIR}}` 占位符） |
| `QUICKSTART.md` | 安装、扫码、后台运行和重新连接的快速指南 |

## CLI 用法

```bash
node logger.js --help
node logger.js config account --help
node logger.js config group --help
node logger.js run --help
```

### 子命令

| 子命令 | 说明 |
|--------|------|
| `config account` | 配对 WhatsApp 账号：自动备份旧 session，前台显示 QR，等待连接成功后退出 |
| `config group` | 选择要记录的群组（需 logger 已在运行） |
| `run` | 启动记录循环（默认行为：无子命令时等同于 `run`） |

### `logger config group` 的选项

```bash
node logger.js config group                  # 交互式选择群组
node logger.js config group --list           # 查看所有群及当前录制状态
node logger.js config group --record-all     # 记录所有群（包括以后新增的）
node logger.js config group --init           # 记录所有当前群（首次设置）
node logger.js config group --add "仁爱"     # 按名称添加（子串匹配）
node logger.js config group --remove "We are Family"  # 按名称移除
```

### 顶层参数（可放在子命令前）

```bash
node logger.js --port 3002 run
node logger.js --log-dir /path/to/logs run
node logger.js --data-dir /path/to/data run
```

| 参数 | 环境变量 | 默认值 |
|------|---------|--------|
| `--port` | `WHATSAPP_LOGGER_PORT` | `3001` |
| `--log-dir` | `WHATSAPP_LOGGER_LOG_DIR` | `<代码目录>/logs` |
| `--data-dir` | `WHATSAPP_LOGGER_DATA_DIR` | `<代码目录>` |

`--data-dir` 决定 `session/`、`cache/`、`config.json` 的位置（三者始终在同一目录下）。

## 安装步骤

```bash
cd ~/devel/whatsapp-logger
./install.sh
```

`install.sh` 是交互式脚本，会询问：

1. **代码安装目录** — 默认 `~/service/whatsapp-logger/`
2. **日志输出目录** — 默认 `<安装目录>/logs`

然后执行：

1. 检查 Node.js v18+
2. 复制源码到安装目录（排除 `.git`、`node_modules`、`session`、`cache`、`logs`、`config.json`）
3. 在 `<安装目录>/bridge/` 执行 `npm install`
4. 创建 `logs/`、`session/`、`cache/` 目录
5. 检测旧 `~/.hermes/whatsapp-logger/session` 和 `~/.hermes/data/whatsapp-logger/`，**只提示不迁移**
6. 渲染 systemd service 文件（替换 `{{APP_DIR}}`、`{{LOG_DIR}}`），写入 `~/.config/systemd/user/`，`daemon-reload`

### 非交互模式

通过环境变量跳过询问：

```bash
WHATSAPP_LOGGER_INSTALL_DIR=/opt/whatsapp-logger \
WHATSAPP_LOGGER_LOG_DIR=/var/log/whatsapp-logger \
./install.sh
```

## 启动方法

### 1. 首次扫码 + 配置群组（`config account`）

```bash
node ~/service/whatsapp-logger/logger.js config account
```

`config account` 会：
- 自动备份旧 session（如有）为 `session.backup-<时间戳>`
- 前台启动 bridge（二维码直接打印到当前终端）
- 等待 `WhatsApp connected!`（最多 5 分钟）
- 配对成功后自动停止前台 bridge，启动后台服务
- 确认服务就绪后**自动进入群组配置**（交互式选择）

用 WhatsApp → 设置 → 已链接设备 → 链接设备，扫描二维码。

认证信息持久保存在 `<安装目录>/session/`。正常停止或重启服务不会要求重新扫码。

群组选择完成后，配置立即生效（`run` 循环热加载）。验证服务状态：

```bash
systemctl --user status whatsapp-logger
journalctl --user -u whatsapp-logger -f
```

### 2. 重新连接或更换 WhatsApp 账号

```bash
systemctl --user stop whatsapp-logger
node ~/service/whatsapp-logger/logger.js config account
# 配对新账号后自动进入群组配置
```

`config account` 会自动把旧 session 重命名为 `session.backup-<时间戳>`（不删除，可恢复）。

## 输出格式

每个群组每月一个 Markdown 文件 + 一个 JSONL 文件，按群 ID 分目录存放：

```
logs/
├── groups_index.md                          # 顶层索引（ID→名称、最近消息、文件链接）
└── groups/
    └── <群ID>/
        ├── <YYYY-MM>.md                     # 单群单月 Markdown（人类+LLM 阅读）
        ├── <YYYY-MM>.jsonl                   # 单群单月 JSONL（程序化检索）
        └── attachments/<YYYY-MM-DD>/        # 当月附件
```

### Markdown 格式

`logs/groups/<群ID>/<YYYY-MM>.md`：

```markdown
# 测试群 `(120363XXX@g.us)` — 2026-07

## 2026-07-11

**张三** `(65xxxxxxxx@s.whatsapp.net)` 14:30:01:
[MSG001] 今天电梯维修，请大家注意

**李四** `(65yyyyyyyy@s.whatsapp.net)` 14:32:15 ↩@65xxxxxxxx #MSG001:
[MSG002] 好的，几点恢复？
![image](attachments/2026-07-11/photo_001.jpg)

## 2026-07-12

**王五** `(65zzzzzzzz@s.whatsapp.net)` 09:00:00:
[MSG003] 第二天
```

格式说明：
- **文件头**：每群每月只写一次 `# 群名 (群JID) — YYYY-MM`
- **日期头**：同一日连续消息不重复，跨日才输出 `## YYYY-MM-DD`
- **消息行**：`**sender** (JID) HH:MM:SS:` 换行 `[消息ID] 正文`
- **回复消息**：单行内联 `↩@短号码 #原消息ID:`，不保留被引用原文（LLM 可按 ID 在上下文中查找）
- **媒体**：`![type](attachments/日期/文件名)` 相对群目录

### JSONL 格式

`logs/groups/<群ID>/<YYYY-MM>.jsonl`，每行一个 JSON 对象：

```json
{"ts":"2026-07-11T14:30:01+08:00","gid":"120363XXX@g.us","gname":"测试群","sid":"65xxxxxxxx@s.whatsapp.net","name":"张三","mid":"MSG001","type":"text","body":"今天电梯维修"}
{"ts":"2026-07-11T14:32:15+08:00","gid":"120363XXX@g.us","gname":"测试群","sid":"65yyyyyyyy@s.whatsapp.net","name":"李四","mid":"MSG002","type":"text","body":"好的，几点恢复？","reply_to":"MSG001","reply_to_sid":"65xxxxxxxx@s.whatsapp.net"}
```

字段说明：

| 字段 | 说明 | 是否必填 |
|------|------|---------|
| `ts` | ISO 8601 带时区时间戳 | 必填 |
| `gid` | 群 JID | 必填 |
| `gname` | 群名（写入时的最新名） | 必填 |
| `sid` | 发送者 JID | 必填 |
| `name` | 发送者名称 | 必填 |
| `mid` | 消息 ID | 必填 |
| `type` | `text` / `image` / `video` / `audio` / `ptt` / `document` / `sticker` / `location` / `contact` / `reaction` / `poll` | 必填 |
| `body` | 消息正文 | 必填 |
| `reply_to` | 被回复消息的 ID | 仅回复消息 |
| `reply_to_sid` | 被回复消息的发送者 JID | 仅回复消息 |
| `media` | 媒体文件相对路径数组 | 仅媒体消息 |
| `media_type` | 媒体类型 | 仅媒体消息 |

### 群组索引

`logs/groups_index.md` 列出所有**已记录过消息**的群（不预填所有已加入群）：

```markdown
# 群组索引

更新时间：2026-07-18 15:00:00

| 群 ID | 群名 | 最近消息 | 本月文件 |
|-------|------|---------|---------|
| `120363XXX@g.us` | 测试群 | 2026-07-18T14:30:01+08:00 | [2026-07.md](groups/120363XXX@g.us/2026-07.md) |
```

行为：
- **只含已记录的群** — 通过 `is_group_recorded()` 检查并真正写过消息的群才进索引
- **群名每日刷新** — 每天首次处理消息时调一次 `/groups` 端点，检测到改名立即更新索引并打日志
- **进程重启不丢失** — 启动时从磁盘 `groups_index.md` 恢复历史条目
- **去抖写盘** — 距上次写盘 > 60s 才重写文件；进程退出时强制 flush

### LLM 分析建议

| 场景 | 做法 |
|------|------|
| "分析某群本月讨论" | 读 `groups_index.md` 找群 → 读对应 `<YYYY-MM>.md` |
| "某群某天说了什么" | ripgrep 日期头 `rg "## 2026-07-11" logs/groups/<gid>/` |
| 跨群关键词搜索 | `rg "关键词" logs/groups/*/<YYYY-MM>.md` |
| 程序化分块/检索 | 解析 `<YYYY-MM>.jsonl`（每行一 JSON 对象，jq 友好） |

## 配置

### 配置文件

`<安装目录>/config.json`：

```json
{
  "recorded_groups": [
    {"id": "120363...@g.us", "name": "群名称"},
    ...
  ],
  "record_all": false
}
```

- `record_all: true` 时记录所有群（包括以后新增的），忽略 `recorded_groups`
- `record_all: false` 时只记录 `recorded_groups` 列出的群
- 修改后无需重启：`run` 循环每条消息检查 mtime，配置变更立即生效

通过 `logger config group` 命令管理，不要手动编辑（除非必要）。

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
