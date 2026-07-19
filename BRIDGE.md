# WhatsApp Bridge

`bridge/bridge.js` is the Hermes WhatsApp bridge used by this project. It is a
standalone Node.js process that connects to WhatsApp through Baileys and exposes
a loopback-only HTTP API on `127.0.0.1`.

In v4, the logger remains a separate process. It starts the bridge as a child
process and talks to it through the same local HTTP API. The bridge is therefore
not part of the logger implementation itself; it is the transport adapter
between WhatsApp and the logger/Hermes layers above it.

## Responsibilities

- Maintain the WhatsApp Baileys session under `session/`.
- Receive WhatsApp messages and convert them into normalized JSON events.
- Download inbound media into cache directories for later copying by the
  logger.
- Expose polling and metadata endpoints for the logger.
- Expose sending endpoints for Hermes text, media, location, poll, edit, and
  typing workflows.
- Apply bridge-level safety and stability behavior, including loopback host
  validation, send serialization, echo filtering, owner-message gating, and
  allowlist checks.

## HTTP API

| Method | Path | Purpose | Used by v4 logger |
| --- | --- | --- | --- |
| `GET` | `/health` | Health check. Returns connection status, queue length, uptime, and bridge script hash. | Yes |
| `GET` | `/messages` | Polls and clears queued inbound WhatsApp message events. | Yes |
| `GET` | `/groups` | Lists participating WhatsApp groups with id, name, and participant count. | Yes |
| `GET` | `/chat/:id` | Returns basic chat or group metadata for a specific chat id. | No |
| `POST` | `/send` | Sends a text message. Supports replies and automatic long-message chunking. | No |
| `POST` | `/edit` | Edits a previously sent message. | No |
| `POST` | `/send-media` | Sends image, video, audio, or document messages natively. | No |
| `POST` | `/send-poll` | Sends a native WhatsApp poll. | No |
| `POST` | `/send-location` | Sends a native WhatsApp location pin. | No |
| `POST` | `/typing` | Sends a WhatsApp typing indicator. | No |

## Logger Usage

The v4 logger only depends on the receiving and metadata side of the bridge:

- `GET /health` during startup checks.
- `GET /messages` once per second during normal logging.
- `GET /groups` for group selection and daily recorded-group name refresh.

The logger does not call Hermes sending endpoints and does not change their
behavior.

## Hermes Usage

The bridge still retains the Hermes sending surface:

- Text replies through `/send`.
- Message edits through `/edit`.
- Native media through `/send-media`.
- Native polls through `/send-poll`.
- Native locations through `/send-location`.
- Typing indicators through `/typing`.

These endpoints are intentionally kept in `bridge/bridge.js` so the bridge can
continue to serve Hermes-compatible workflows while the logger stays focused on
message capture and local log writing.

## Architecture Boundary

The important v4 boundary is:

```text
WhatsApp <-> Baileys bridge <-> local HTTP API <-> Node.js logger
```

The bridge remains an independent Node.js child process. The logger is also
Node.js, but it communicates with the bridge only through HTTP. This preserves
the existing architecture while removing the Python runtime dependency from the
logger layer.
