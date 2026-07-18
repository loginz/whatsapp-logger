# 工作进度

更新时间：2026-07-18

## 当前状态

核心链路已经修正并通过静态检查与本地落盘测试，项目已上线稳定运行。
v3 重构后采用单一入口 `logger.py` 子命令结构，所有运行时数据与代码同目录平铺。

## 已完成功能

1. `logger.py` 启动独立 Baileys bridge，提供 `config account` / `config group` / `run` 三个子命令。
2. bridge 仅监听 `127.0.0.1:3001`。
3. `run` 子命令从 `http://127.0.0.1:3001/messages` 轮询消息。
4. `config account` 子命令前台启动 bridge，在当前终端显示 WhatsApp pairing 二维码，自动备份旧 session。
5. pairing 凭据持久化在 `<安装目录>/session/`（默认 `~/service/whatsapp-logger/session/`）。
6. 默认记录所有群成员消息，包括链接账号自己发送的群消息。
7. 每个群组每月一个 Markdown + JSONL 文件；附件位于群目录下的 `attachments/日期/`。
8. 群名称通过 WhatsApp 群元数据获取并缓存。
9. `config.json`、`session/`、`cache/` 与 `logger.py` 同目录平铺；日志默认写入 `<安装目录>/logs/groups/<群ID>/`。

## 目录布局（v3，平铺）

```
<安装目录>/                       # 默认 ~/service/whatsapp-logger/
├── logger.py                    # 主程序（config account / config group / run）
├── bridge/                      # Baileys bridge (Node.js)
│   ├── bridge.js                #   主桥接程序（含 /groups 端点）
│   ├── bridge_helpers.js
│   ├── allowlist.js / outbound_ids.js / owner_message_gate.js
│   └── package.json
├── install.sh
├── whatsapp-logger.service      # systemd 模板，含 {{APP_DIR}} / {{LOG_DIR}}
├── README.md / QUICKSTART.md / PROGRESS.md
├── config.json                  # 由 `logger config group` 写入，`logger run` 热加载
├── session/                     # Baileys pairing 凭据
├── cache/                       # 媒体缓存
│   └── images/  documents/  audio/  video/
└── logs/                        # 默认日志根目录（安装时可改）
    ├── groups_index.md          # 顶层索引
    └── groups/<群ID>/
        ├── <YYYY-MM>.md         # 单群单月 Markdown
        ├── <YYYY-MM>.jsonl      # 单群单月 JSONL
        └── attachments/<YYYY-MM-DD>/
```

## 快速使用

```bash
# 1. 安装（交互式询问安装目录与日志目录）
cd ~/devel/whatsapp-logger
./install.sh

# 2. 首次扫码认证（前台显示 QR 码）
python3 ~/service/whatsapp-logger/logger.py config account

# 3. 选择要记录的群组（需先临时启动 run，或保持 config account 后的状态）
python3 ~/service/whatsapp-logger/logger.py config group --init   # 记录所有群
# 或
python3 ~/service/whatsapp-logger/logger.py config group          # 交互式选择

# 4. 切换到 systemd 后台运行
systemctl --user enable --now whatsapp-logger
```

日志位置（默认）：
```
~/service/whatsapp-logger/logs/groups_index.md
~/service/whatsapp-logger/logs/groups/<群ID>/<YYYY-MM>.md
~/service/whatsapp-logger/logs/groups/<群ID>/<YYYY-MM>.jsonl
~/service/whatsapp-logger/logs/groups/<群ID>/attachments/<YYYY-MM-DD>/
```

配置文件：
```
~/service/whatsapp-logger/config.json
```

## CLI 用法

```bash
python3 logger.py config account                       # 配对 WhatsApp 账号（自动备份旧 session）
python3 logger.py config group                     # 交互式选择群组
python3 logger.py config group --list             # 查看群组与录制状态
python3 logger.py config group --add "群名"        # 按名称添加
python3 logger.py config group --remove "群名"     # 按名称移除
python3 logger.py config group --record-all        # 记录所有群（含未来新增）
python3 logger.py config group --init              # 记录所有当前群（首次设置）
python3 logger.py run                        # 启动记录循环
python3 logger.py                            # 等同于 run
```

顶层参数（可放在子命令前）：

| 参数 | 环境变量 | 默认值 |
|------|---------|--------|
| `--port` | `WHATSAPP_LOGGER_PORT` | `3001` |
| `--log-dir` | `WHATSAPP_LOGGER_LOG_DIR` | `<代码目录>/logs` |
| `--data-dir` | `WHATSAPP_LOGGER_DATA_DIR` | `<代码目录>` |

`--data-dir` 决定 `session/`、`cache/`、`config.json` 的位置（三者始终在同一目录下）。

## 群组概览（当前）

共 138 个群组，涵盖物业投诉反馈、门禁系统、项目管理、销售、技术方案、教会等。具体列表可通过 `python3 logger.py config group --list` 查看。

## 版本历史

### v3 重构（2026-07-18）

**子命令化**
- 文件: `logger.py`
- 用 argparse subcommands 把原 `logger.py` 和 `group_selector.py` 合并为单一入口
- 子命令: `init` / `config` / `run`（无子命令时默认进入 `run`）
- 顶层参数 `--port` / `--log-dir` / `--data-dir` 仍可放在子命令前

> 注: v3.3 将 `init` 重命名为 `config account`，`config` 重命名为 `config group`，见下文。

**目录平铺**
- `config.json`、`session/`、`cache/` 全部与 `logger.py` 同目录（不再放 `~/.hermes/`）
- 默认日志根目录改为 `<代码目录>/logs/`
- 仍支持 `--data-dir` / `WHATSAPP_LOGGER_DATA_DIR` 把 session/cache/config.json 移到别处

**安装脚本重写** (`install.sh`)
- 交互式询问代码安装目录（默认 `~/service/whatsapp-logger/`）和日志输出目录
- `rsync -a` 复制源码（排除 `.git`、`node_modules`、`session`、`cache`、`logs`、`config.json`），无 rsync 时退化到 `cp`
- 检测旧 `~/.hermes/whatsapp-logger/session` 和 `~/.hermes/data/whatsapp-logger/`，**只提示不迁移**
- 非交互模式: `WHATSAPP_LOGGER_INSTALL_DIR` / `WHATSAPP_LOGGER_LOG_DIR`

**systemd service 更新** (`whatsapp-logger.service`)
- 移除 `{{DATA_DIR}}` 占位符（默认 = APP_DIR）
- `ExecStart` 显式使用 `run` 子命令
- 新增 `WorkingDirectory={{APP_DIR}}`

**文件清理**
- 删除 `logger.py.orig`
- 删除 `group_selector.py`（逻辑合并入 `logger.py`）

**向后兼容**
- 旧 `~/.hermes/whatsapp-logger/` 下的 session 和日志**不自动迁移**
- 如需复用旧 session: `cp -a ~/.hermes/whatsapp-logger/session/. <安装目录>/session/`
- 旧 `config.json` 格式（`recorded_groups` 为字符串数组）仍可被识别

**验证**
- `python3 -m py_compile logger.py` ✅
- `python3 logger.py --help` / `init --help` / `config --help` / `run --help` ✅
- `bash -n install.sh` ✅
- 隔离 HOME 下交互式与非交互式安装测试 ✅（含旧路径检测）
- `logger config group --list/add/remove` 真实调用 bridge ✅

### v3.1 聊天格式优化（2026-07-18）

**群组标题简化**
- 文件: `logger.py` `process_message()`
- 变更: 群组标题 `## HH:MM:SS 群名 (群JID)` 改为 `## 群名 (群JID)`，不再重复时间
- 时间保留在 `**发送者** (...) (HH:MM:SS):` 行

**回复消息溯源**
- 文件: `logger.py` `process_message()`
- 变更: 当消息为回复时（bridge 提供 `hasQuotedMessage`/`quotedMessageId`/`quotedParticipant`/`quotedText`），在正文前插入 blockquote 显示被回复者 ID、原消息 ID 和预览（超 200 字符截断加 `…`）
- 示例:
  ```markdown
  > ↩ 回复 `(65xxx@s.whatsapp.net)`: `msg:原消息ID` 原消息预览…
  ```
- 无回复消息时无 blockquote，保持原样

**验证**
- `python3 -m py_compile logger.py` ✅
- 隔离目录模拟普通消息、回复消息、超长引用三种 case，输出格式正确 ✅

### v3.2 按群分目录 + 紧凑格式 + JSONL（2026-07-18）

**目录结构重构**
- 文件: `logger.py` `process_message()`
- 变更: 从 `logs/YYYY-MM/YYYY-MM-DD.md`（混合日文件）改为 `logs/groups/<群ID>/<YYYY-MM>.md`（单群单月）
- 媒体路径: `logs/groups/<群ID>/attachments/<YYYY-MM-DD>/`
- 旧 `logs/YYYY-MM/` 目录保留不动，新消息只写入新结构
- 收益: 单群月分析节省 90%+ tokens，跨群检索用 ripgrep 弥补

**Markdown 紧凑格式**
- 文件头: `# 群名 (群JID) — YYYY-MM`（每群每月一次）
- 日期头: `## YYYY-MM-DD`（同日连续消息不重复，跨日才输出；基于读文件尾 4KB 判定，进程重启正确）
- 消息行: `**sender** (JID) HH:MM:SS:` 换行 `[消息ID] 正文`（去掉 `msg:` 前缀）
- 回复内联: `↩@短号码 #原消息ID:`（单行，不保留被引用原文）
- 群组标题不再重复时间

**JSONL sidecar**
- 文件: `logs/groups/<群ID>/<YYYY-MM>.jsonl`
- 每行一个 JSON 对象，字段: `ts`(ISO 8601 带时区) / `gid` / `gname` / `sid` / `name` / `mid` / `type` / `body` / `reply_to` / `reply_to_sid` / `media` / `media_type`
- 用途: 程序化分块、向量检索、按群/时间/sender 过滤，比 Markdown 节省 40-60% tokens

**群组索引 (`groups_index.md`)**
- 文件: `logs/groups_index.md`
- 4 列: 群 ID / 群名 / 最近消息 / 本月文件链接
- 只含已记录过消息的群（通过 `is_group_recorded()` 检查后才进索引）
- 进程重启不丢失（启动时从磁盘恢复）
- 去抖写盘（60s 间隔，退出时强制 flush）

**群名每日刷新**
- 每天首次处理消息时调一次 `/groups` 端点
- 对比 `_index_cache` 检测改名，发现改名立即更新索引并打日志
- 只更新已索引的群，不新增未索引的群
- 失败静默（bridge 忙/重启时不影响消息处理，次日重试）

**新增函数**
- `_load_index_from_disk()`: 启动时从 `groups_index.md` 恢复索引
- `_update_index(chat_id, name, ts, month_str)`: 消息处理时更新内存索引
- `_maybe_flush_index(force=False)`: 去抖 60s 写盘
- `_write_index()`: 渲染 Markdown 表格
- `_last_date_in_file(md_path)`: 读文件尾 4KB 找最后日期头
- `_maybe_refresh_group_names()`: 每日拉 `/groups` 刷新群名
- `_local_dt_from_ts(ts_raw)`: 转本地 tz-aware datetime
- `_short_id(jid)`: 取 JID 的 @ 前部分
- `_message_type(media_type, has_quote)`: 分类消息类型

**向后兼容**
- 旧 `logs/YYYY-MM/` 保留不动
- 新消息只写 `logs/groups/`
- `config.json` 格式不变

**验证**
- `python3 -m py_compile logger.py` ✅
- 隔离目录模拟: 群A跨日两条+回复、群B一条、进程重启后继续写同月文件、群改名检测 → 全部通过 ✅

### v2 新功能（2026-07-15，已被 v3 部分取代）

> 注：v3 把 `group_selector.py` 合并入 `logger.py config`，配置路径从 `~/.hermes/whatsapp-logger/` 改为与代码同目录。以下为 v2 原始记录。

**群组查询端点 `GET /groups`**
- 文件: `bridge/bridge.js`
- 通过 Baileys `groupFetchAllParticipating()` 获取所有已加入群组
- 返回: 群 ID (JID)、群名称、成员数，按名称排序
- 使用: `curl http://127.0.0.1:3001/groups`

**群组选择与过滤**（v3 已合并入 `logger config`）
- 交互式 CLI 工具，查询已加入群组并让用户选择要记录的群
- 配置热加载: 每次处理消息时检查 `config.json` 的 mtime，有变更才重读
- 配置结构:
  ```json
  {
    "recorded_groups": [{"id": "120363...@g.us", "name": "群名"}, ...],
    "record_all": false
  }
  ```

**增强记录格式**
- 新增字段: 群 ID (`chatId`)、发送者 ID (`senderId`)、消息 ID (`messageId`)
- 格式:
  ```markdown
  ## HH:MM:SS 群名 `(群JID)`

  **发送者** `(发送者JID)` (HH:MM:SS):
  `msg:消息ID` 消息内容
  ```

## 服务状态

```
systemctl --user status whatsapp-logger
● Active: active (running) since Sat 2026-07-11 17:18:35 +08
   Memory: ~210M (max: 512M)
   Bridge: port 3001, WhatsApp connected
```

### v3.3 子命令重构（2026-07-18）

**`init` → `config account`**
- 旧: `logger.py init`（检测到旧 session 只打印提示，需手动移走；配对成功后立即停止 bridge）
- 新: `logger.py config account`（自动备份旧 session 为 `session.backup-<时间戳>`；配对后自动 `daemon-reload` + `systemctl start` 启动服务，确认服务就绪后**直接进入 `config group` 交互式选择群组**）

**`config` → `config group`**
- 旧: `logger.py config` / `logger.py config --list` / `logger.py config --add ...`
- 新: `logger.py config group` / `logger.py config group --list` / `logger.py config group --add ...`
- `cmd_config` 重命名为 `cmd_config_group`，`cmd_init` 重命名为 `cmd_config_account`

**嵌套子命令结构**
- `config` 成为容器，下含 `account` 和 `group` 两个子命令
- `config` 不带子参数时打印帮助
- `run` 保持不变，无子命令时默认进入

**文档同步**
- README.md / QUICKSTART.md / INSTALL.md / PROGRESS.md 中所有 `init` 改为 `config account`，`config` 改为 `config group`
- "重新连接或更换账号"流程简化为直接 `config account`（不再需手动 `mv session`）

**验证**
- `python3 -m py_compile logger.py` ✅
- `--help` / `config --help` / `config account --help` / `config group --help` ✅
- `_backup_session_dir()` 四种边界（无 session / 空 session / 有 session / 连续两次备份）✅

## 后续待办

- 真实媒体附件的端到端接收测试
- 旧 `~/.hermes/data/whatsapp-logger/` 下的历史 Markdown 是否需要提供迁移工具（当前保留原位）
