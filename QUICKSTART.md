# 快速启动

## 1. 安装

```bash
cd ~/devel/whatsapp-logger
./install.sh
```

安装脚本会安装 Node.js bridge 依赖、创建数据目录，并安装用户级 systemd 服务。

## 2. 首次连接 WhatsApp

首次连接必须在前台启动，以便显示二维码：

```bash
cd ~/devel/whatsapp-logger
python3 logger.py
```

终端显示二维码后，在手机 WhatsApp 中依次进入：

```text
设置 -> 已链接设备 -> 链接设备
```

扫描二维码。终端显示 `WhatsApp connected!` 后，连接成功并开始记录群聊消息。

认证信息保存在：

```text
~/.hermes/whatsapp-logger/session/
```

正常停止或重启不需要再次扫码。

## 3. 切换到后台运行

扫码成功后按 `Ctrl+C` 停止前台进程，然后执行：

```bash
systemctl --user enable --now whatsapp-logger
```

常用管理命令：

```bash
# 查看状态
systemctl --user status whatsapp-logger

# 查看实时运行日志
journalctl --user -u whatsapp-logger -f

# 重启
systemctl --user restart whatsapp-logger

# 停止
systemctl --user stop whatsapp-logger
```

## 4. 查看聊天记录

默认数据目录：

```text
~/.hermes/data/whatsapp-logger/
└── YYYY-MM/
    ├── YYYY-MM-DD.md
    └── attachments/
        └── YYYY-MM-DD/
```

例如：

```text
~/.hermes/data/whatsapp-logger/2026-07/2026-07-11.md
~/.hermes/data/whatsapp-logger/2026-07/attachments/2026-07-11/photo_001.jpg
```

## 5. 重新连接或更换账号

先停止服务，并备份当前 session：

```bash
systemctl --user stop whatsapp-logger
mv ~/.hermes/whatsapp-logger/session \
   ~/.hermes/whatsapp-logger/session.backup-$(date +%Y%m%d-%H%M%S)
```

然后重新前台启动：

```bash
cd ~/devel/whatsapp-logger
python3 logger.py
```

扫描新二维码，确认连接成功后按 `Ctrl+C`，再启动后台服务：

```bash
systemctl --user start whatsapp-logger
```

确认新账号工作正常后，可以删除旧 session 备份。如果需要恢复旧账号，停止服务，将当前 `session` 移走，再把对应备份改名为 `session`。

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

如果 WhatsApp 显示链接设备已注销，按“重新连接或更换账号”步骤重新扫码。

更多配置参数和目录自定义方法见 `README.md`。
