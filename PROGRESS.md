# 工作进度

更新时间：2026-07-11

## 当前状态

核心链路已经修正并通过静态检查与本地落盘测试：

1. `logger.py` 启动独立 Baileys bridge。
2. bridge 仅监听 `127.0.0.1:3001`。
3. logger 从 `http://127.0.0.1:3001/messages` 轮询消息。
4. 首次启动时，bridge 直接在当前终端显示 WhatsApp pairing 二维码。
5. pairing 凭据持久化在 `~/.hermes/whatsapp-logger/session/`。
6. 默认记录所有群成员消息，包括链接账号自己发送的群消息。
7. 每月一个目录，每日一个 Markdown；附件位于同月目录的 `attachments/日期/`。
8. 群名称通过 WhatsApp 群元数据获取并缓存。

## 已完成修复

- 修复 logger 期望 `/health` 返回 `ok`，但 bridge 实际返回连接状态而导致的循环重启。
- bridge 输出继承当前终端，确保二维码完整显示，并避免未读取的 stdout 管道阻塞。
- logger 专用 bridge 默认启用群聊采集，并设置允许接收消息的默认白名单。
- 保留链接账号自己在群中发送的消息。
- 日志附件链接使用同月相对路径 `attachments/YYYY-MM-DD/...`。
- 使用真实群名称代替群 JID 编号。
- README 已更新端口、pairing、重新连接、session 持久化、月目录和 systemd 使用说明。

## 验证结果

已通过：

- `python3 -m py_compile logger.py`
- `bash -n install.sh`
- `node --check bridge/bridge.js`
- `node --check bridge/bridge_helpers.js`
- 临时目录中的群消息、Markdown 和媒体附件落盘测试
- 真实 WhatsApp 账号扫码 pairing 及群聊记录（使用者已确认运行正常）

尚未执行：

- 真实媒体附件的端到端接收测试
- systemd 长时间运行测试

这些测试会创建或改变 WhatsApp 的实际链接设备状态，应由使用者在目标账号上执行。

## 快速使用

```bash
cd ~/devel/whatsapp-logger
./install.sh
python3 logger.py
```

终端显示二维码后，在手机 WhatsApp 中进入“设置 -> 已链接设备 -> 链接设备”并扫码。看到 `WhatsApp connected!` 后即可在群聊发送测试消息。

日志位置：

```text
~/.hermes/data/whatsapp-logger/YYYY-MM/YYYY-MM-DD.md
~/.hermes/data/whatsapp-logger/YYYY-MM/attachments/YYYY-MM-DD/
```

扫码成功后，可按 `Ctrl+C` 停止前台进程并切换到 systemd：

```bash
systemctl --user enable --now whatsapp-logger
systemctl --user status whatsapp-logger
journalctl --user -u whatsapp-logger -f
```

完整参数和自定义目录说明见 `README.md`。
