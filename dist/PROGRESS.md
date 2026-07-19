# Progress

## v4 Node.js Logger

The distribution is now based on a pure Node.js logger implementation:

- `logger.js` replaces the old Python runtime entrypoint.
- `npm start` runs `node logger.js`.
- `whatsapp-logger.service` starts `node logger.js --log-dir {{LOG_DIR}} run`.
- `install.sh` checks Node.js/npm and no longer requires Python.
- `bridge/bridge.js` remains a separate Node.js child process.
- The logger continues to use the bridge through local HTTP on port `3001`.

## Preserved Behavior

v4 keeps the existing runtime architecture and file formats:

- CLI commands: `run`, `config account`, and `config group`.
- Top-level options: `--port`, `--log-dir`, and `--data-dir`.
- Environment variables: `WHATSAPP_LOGGER_PORT`,
  `WHATSAPP_LOGGER_LOG_DIR`, and `WHATSAPP_LOGGER_DATA_DIR`.
- Existing `config.json`, including both string group ids and `{id,name}`
  `recorded_groups` entries.
- Existing `session/`, `cache/`, Markdown logs, JSONL logs, and
  `groups_index.md`.
- Bridge endpoints used by the logger: `/health`, `/messages`, and `/groups`.
- Hermes sending endpoints in the bridge are kept unchanged.

## Distribution Contents

The `dist/` directory contains the files needed for installation:

```text
dist/
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

The old Python logger is no longer distributed.

## Validation

The v4 implementation has been checked with:

```bash
node --check logger.js
node logger.js --help
node logger.js config account --help
npm test
bash -n install.sh
git diff --check
```
