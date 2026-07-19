# Installation

This distribution contains the v4 WhatsApp Group Chat Logger. The logger is a
Node.js CLI, and the Baileys bridge remains a separate Node.js child process.

## Requirements

| Tool | Version | Purpose |
| --- | --- | --- |
| Node.js | 18+ | Runs `logger.js` and `bridge/bridge.js` |
| npm | Bundled with Node.js | Installs bridge dependencies |
| systemd user services | Linux only, optional | Keeps the logger running in the background |
| rsync | Optional | Used by `install.sh` for source copy; falls back to `cp` |

Check the required runtime:

```bash
node --version
npm --version
```

## Distribution Layout

```text
whatsapp-logger/
├── logger.js
├── package.json
├── bridge/
├── install.sh
├── whatsapp-logger.service
├── README.md
├── QUICKSTART.md
├── BRIDGE.md
├── INSTALL.md
└── PROGRESS.md
```

Runtime data is created under the selected install directory:

```text
<install-dir>/
├── config.json
├── session/
├── cache/
└── logs/
```

Existing `config.json`, `session/`, `cache/`, and `logs/` are preserved by the
installer.

## Install

From the distribution directory:

```bash
./install.sh
```

The installer asks for:

- Code install directory, default `~/service/whatsapp-logger`
- Chat records directory, default `<install-dir>/logs`

It then copies the distribution, installs bridge dependencies under
`<install-dir>/bridge/`, creates runtime directories, renders the systemd user
service, and runs `systemctl --user daemon-reload` when available.

For non-interactive installation:

```bash
WHATSAPP_LOGGER_INSTALL_DIR=/opt/whatsapp-logger \
WHATSAPP_LOGGER_LOG_DIR=/var/log/whatsapp-logger \
./install.sh
```

## First Run

Pair the WhatsApp account and configure groups:

```bash
node ~/service/whatsapp-logger/logger.js config account
```

After successful pairing, the logger starts the systemd service and enters group
selection automatically.

Check the background service:

```bash
systemctl --user status whatsapp-logger
journalctl --user -u whatsapp-logger -f
```

## CLI

```bash
node logger.js --help
node logger.js config account
node logger.js config group
node logger.js config group --list
node logger.js config group --add "Group name"
node logger.js config group --remove "Group name"
node logger.js config group --record-all
node logger.js config group --init
node logger.js run
npm start
```

Top-level options:

```bash
node logger.js --port 3002 run
node logger.js --log-dir /path/to/logs run
node logger.js --data-dir /path/to/data run
```

Environment variables:

| Option | Environment variable | Default |
| --- | --- | --- |
| `--port` | `WHATSAPP_LOGGER_PORT` | `3001` |
| `--log-dir` | `WHATSAPP_LOGGER_LOG_DIR` | `<app-dir>/logs` |
| `--data-dir` | `WHATSAPP_LOGGER_DATA_DIR` | `<app-dir>` |

## Compatibility

v4 keeps the existing architecture and data formats:

- The bridge still runs as an independent Node.js process.
- The logger still talks to the bridge over local HTTP.
- Existing `config.json`, `session/`, cache directories, Markdown logs, JSONL
  logs, and `groups_index.md` are used in place.
- No Python runtime is required for the logger.

## Troubleshooting

| Problem | Check |
| --- | --- |
| QR code does not appear | Run `node logger.js config account` in a real terminal. |
| Service does not start | Check `journalctl --user -u whatsapp-logger -n 100`. |
| No group logs appear | Run `node logger.js config group --list` and confirm groups are selected. |
| WhatsApp says the device logged out | Stop the service and run `node logger.js config account` again. |
