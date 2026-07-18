# 快速启动

## 1. 安装

```bash
cd ~/devel/whatsapp-logger
./install.sh
```

安装脚本会询问：

- 代码安装目录（默认 `~/service/whatsapp-logger/`）
- 日志输出目录（默认 `<安装目录>/logs`）

然后复制源码、安装 Node.js bridge 依赖、创建数据目录、安装 systemd 服务。

如果检测到旧 `~/.hermes/whatsapp-logger/session` 或旧日志，脚本只会**提示**，不会自动迁移。

## 2. 首次扫码认证 + 配置群组

```bash
python3 ~/service/whatsapp-logger/logger.py config account
```

终端显示二维码后，在手机 WhatsApp 中依次进入：

```text
设置 -> 已链接设备 -> 链接设备
```

扫描二维码。`config account` 会自动完成后续步骤：启动后台服务、进入群组配置界面。

按屏幕提示选择要记录的群组（输入编号切换选中/取消，输入 `done` 保存退出）。

## 3. 验证服务

```bash
systemctl --user status whatsapp-logger
journalctl --user -u whatsapp-logger -f
```

## 4. 查看聊天记录

默认数据目录：

```text
~/service/whatsapp-logger/logs/
├── groups_index.md                  # 顶层群组索引（先看这里找群）
└── groups/
    └── <群ID>/
        ├── <YYYY-MM>.md             # 单群单月 Markdown
        ├── <YYYY-MM>.jsonl          # 单群单月 JSONL（程序化检索）
        └── attachments/<YYYY-MM-DD>/
```

例如：

```text
~/service/whatsapp-logger/logs/groups_index.md
~/service/whatsapp-logger/logs/groups/120363XXX@g.us/2026-07.md
~/service/whatsapp-logger/logs/groups/120363XXX@g.us/2026-07.jsonl
~/service/whatsapp-logger/logs/groups/120363XXX@g.us/attachments/2026-07-11/photo_001.jpg
```

先读 `groups_index.md` 找到目标群，再点链接进对应月度文件。

## 5. 重新连接或更换账号

先停止服务，然后重新配对（`config account` 会自动备份旧 session、重启服务、进入群组配置）：

```bash
systemctl --user stop whatsapp-logger
python3 ~/service/whatsapp-logger/logger.py config account
```

`config account` 会把旧 session 重命名为 `session.backup-<时间戳>`（不删除，可恢复）。确认新账号工作正常后，可以删除旧 session 备份。如果需要恢复旧账号，停止服务，将当前 `session/` 移走，再把对应备份改名为 `session/`。

## 6. 快速排查

确认服务状态：

```bash
systemctl --user status whatsapp-logger
```

确认 bridge 是否监听本机端口 3001：

```bash
curl http://127.0.0.1:3001/health
```

查看最近 100 行运行日志：

```bash
journalctl --user -u whatsapp-logger -n 100 --no-pager
```

如果 WhatsApp 显示链接设备已注销，按"重新连接或更换账号"步骤重新 `config account`。

更多配置参数和目录自定义方法见 `README.md`。
