# Installation Guide

This document is for **first-time deployment** of the WhatsApp Group Chat Logger on a new host.
The `dist/` directory contains all required code and scripts — no access to the original repository needed.

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| Node.js | v18+ | Runs the Baileys bridge |
| Python | 3.9+ | Runs `logger.py` (stdlib only, no pip install needed) |
| systemd | user mode | User-level service (`systemctl --user`) |
| rsync | optional | Used by `install.sh` for file copy; falls back to `cp` |

Check:

```bash
node --version       # expect v18+
python3 --version    # expect 3.9+
```

## Layout

After installation everything lives under one directory (flat layout, default `~/service/whatsapp-logger/`):

```
~/service/whatsapp-logger/
├── logger.py                # Main program (config account / config group / run)
├── bridge/                  # Baileys bridge (Node.js)
├── install.sh
├── whatsapp-logger.service
├── *.md
├── config.json              # Group filter (written by `config group`, hot-reloaded)
├── session/                 # Baileys pairing credentials
├── cache/                   # Media cache
│   └── images/  documents/  audio/  video/
└── logs/                    # Chat records root (configurable during install)
    ├── groups_index.md      # Top-level group index
    └── groups/<群ID>/
        ├── <YYYY-MM>.md     # Per-group monthly Markdown
        ├── <YYYY-MM>.jsonl  # Per-group monthly JSONL
        └── attachments/<YYYY-MM-DD>/
```

## Installation

### 1. Copy `dist/` to the target host

```bash
scp -r dist/ user@newhost:~/whatsapp-logger-dist/
# or
rsync -av --exclude node_modules dist/ user@newhost:~/whatsapp-logger-dist/
```

### 2. Run the install script

```bash
cd ~/whatsapp-logger-dist
./install.sh
```

The script will ask:

1. **Install directory** — default `~/service/whatsapp-logger/`
2. **Chat records directory** — default `<install-dir>/logs`

Then it:

1. Checks Node.js v18+
2. Copies source code (excludes `.git`, `node_modules`, `session`, `cache`, `logs`, `config.json`)
3. Runs `npm install` in `<install-dir>/bridge/`
4. Creates `logs/`, `session/`, `cache/` directories
5. Detects old `~/.hermes/whatsapp-logger/session` and `~/.hermes/data/whatsapp-logger/` — **hints only, no migration**
6. Renders the systemd service file (replaces `{{APP_DIR}}`, `{{LOG_DIR}}`, `{{EXTRA_PATH}}`), writes to `~/.config/systemd/user/`, runs `daemon-reload`

### 3. Non-interactive mode

Skip prompts via environment variables:

```bash
WHATSAPP_LOGGER_INSTALL_DIR=/opt/whatsapp-logger \
WHATSAPP_LOGGER_LOG_DIR=/var/log/whatsapp-logger \
./install.sh
```

## First-time setup

### 1. Pair a WhatsApp account + configure groups

```bash
python3 ~/service/whatsapp-logger/logger.py config account
```

The terminal will show a WhatsApp pairing QR code. On your phone:

```
Settings → Linked Devices → Link a Device
```

Scan the QR code. After successful pairing, `config account` will:

1. Back up any old session to `session.backup-<timestamp>` (recoverable)
2. Start the background service (`systemctl --user daemon-reload` + `systemctl --user start`)
3. Wait for the service to be ready
4. **Automatically enter group selection** (interactive mode)

In the group selection interface:

- Enter group numbers to toggle selection (e.g., `1 3 5`)
- `a` — select all
- `n` — select none
- `done` — save and exit
- `q` — quit without saving

Config is saved to `<install-dir>/config.json` and takes effect immediately (hot-reloaded).

### 2. Verify the service

```bash
systemctl --user status whatsapp-logger
journalctl --user -u whatsapp-logger -f
```

## Re-pairing or changing WhatsApp account

```bash
systemctl --user stop whatsapp-logger
python3 ~/service/whatsapp-logger/logger.py config account
```

`config account` automatically backs up the old session and enters group configuration after pairing.

## CLI reference

```bash
python3 logger.py --help
python3 logger.py config account                     # Pair WhatsApp account (auto-enters group config)
python3 logger.py config group                       # Interactive group selection
python3 logger.py config group --list                # List groups and recording status
python3 logger.py config group --add "Name"          # Add groups matching name
python3 logger.py config group --remove "Name"       # Remove groups matching name
python3 logger.py config group --record-all          # Record all groups (including future ones)
python3 logger.py config group --init                # Record all current groups
python3 logger.py run                                # Start recording loop (default)
python3 logger.py                                    # Same as `run`
```

Top-level options (before subcommand):

| Option | Env var | Default |
|--------|---------|---------|
| `--port` | `WHATSAPP_LOGGER_PORT` | `3001` |
| `--log-dir` | `WHATSAPP_LOGGER_LOG_DIR` | `<code-dir>/logs` |
| `--data-dir` | `WHATSAPP_LOGGER_DATA_DIR` | `<code-dir>` |

## Troubleshooting

| Symptom | Check |
|---------|-------|
| No QR code during `config account` | Verify Node.js v18+; check `journalctl --user -u whatsapp-logger -n 50` |
| Scan fails / no "connected" | Check WhatsApp "Linked Devices" on phone; timeout is 5 minutes |
| `config group` says "Cannot connect to bridge" | Make sure the service is running: `systemctl --user status whatsapp-logger` |
| Service fails to start | Check `systemctl --user status whatsapp-logger`; verify `ExecStart` path in service file |
| No chat logs | Verify groups are selected: `logger.py config group --list`; check for new messages |
| WhatsApp shows "device logged out" | Re-pair: `systemctl --user stop whatsapp-logger` then `logger.py config account` |

## Further reading

- `README.md` — Full documentation (architecture, config, output format)
- `QUICKSTART.md` — Quick start guide
- `PROGRESS.md` — Version history and changelog
