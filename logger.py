#!/usr/bin/env python3
"""
WhatsApp Group Chat Logger

Standalone service that:
1. Starts a Baileys bridge (Node.js subprocess)
2. Polls for incoming WhatsApp messages
3. Saves group chat messages to per-group monthly markdown files
4. Downloads and links media attachments

Completely independent from Hermes — no LLM processing, no replies.

Subcommands:
  config account  Pair a (new) WhatsApp account: backs up old session, shows QR.
  config group     Select which groups to record (requires logger running).
  run              Start the recording loop (default when no subcommand is given).

Layout (all under the code root directory by default):
  logger.py
  bridge/
  config.json        # group filter, hot-reloaded by `run`
  session/           # Baileys pairing credentials
  cache/             # media cache
  logs/              # default log output root (overridable via --log-dir)
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Paths (flat layout under the code root) ────────────────────────────────

APP_DIR = Path(__file__).resolve().parent
BRIDGE_DIR = APP_DIR / "bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"

DEFAULT_LOG_DIR = APP_DIR / "logs"
DEFAULT_BRIDGE_DATA = APP_DIR

SESSION_DIR = DEFAULT_BRIDGE_DATA / "session"
IMAGE_CACHE_DIR = DEFAULT_BRIDGE_DATA / "cache" / "images"
DOCUMENT_CACHE_DIR = DEFAULT_BRIDGE_DATA / "cache" / "documents"
AUDIO_CACHE_DIR = DEFAULT_BRIDGE_DATA / "cache" / "audio"
VIDEO_CACHE_DIR = DEFAULT_BRIDGE_DATA / "cache" / "video"
CONFIG_PATH = DEFAULT_BRIDGE_DATA / "config.json"

# Effective values — may be overridden by CLI / env vars at startup.
LOG_DIR: Path = Path(os.environ.get(
    "WHATSAPP_LOGGER_LOG_DIR", str(DEFAULT_LOG_DIR)))
BRIDGE_DATA_DIR: Path = Path(os.environ.get(
    "WHATSAPP_LOGGER_DATA_DIR", str(DEFAULT_BRIDGE_DATA)))
INDEX_PATH = LOG_DIR / "groups_index.md"
BRIDGE_PORT: int = int(os.environ.get("WHATSAPP_LOGGER_PORT", "3001"))

POLL_INTERVAL = 1.0  # seconds between polls
POLL_TIMEOUT = 30    # seconds for each /messages HTTP request
BRIDGE_START_TIMEOUT = 30  # seconds


# ── Helpers ─────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def apply_overrides(port: int | None = None,
                    log_dir: str | None = None,
                    data_dir: str | None = None) -> None:
    """Apply CLI overrides to module-level path globals.

    `data_dir` changes where session/, cache/, and config.json live — they
    are always co-located with each other (flat layout under data dir)."""
    global BRIDGE_PORT, LOG_DIR, BRIDGE_DATA_DIR
    global SESSION_DIR, IMAGE_CACHE_DIR, DOCUMENT_CACHE_DIR
    global AUDIO_CACHE_DIR, VIDEO_CACHE_DIR, CONFIG_PATH, INDEX_PATH
    if port is not None:
        BRIDGE_PORT = port
    if log_dir is not None:
        LOG_DIR = Path(log_dir).expanduser().resolve()
        INDEX_PATH = LOG_DIR / "groups_index.md"
    if data_dir is not None:
        BRIDGE_DATA_DIR = Path(data_dir).expanduser().resolve()
        SESSION_DIR = BRIDGE_DATA_DIR / "session"
        IMAGE_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "images"
        DOCUMENT_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "documents"
        AUDIO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "audio"
        VIDEO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "video"
        CONFIG_PATH = BRIDGE_DATA_DIR / "config.json"


def ensure_dirs() -> None:
    for d in [LOG_DIR, SESSION_DIR, IMAGE_CACHE_DIR, DOCUMENT_CACHE_DIR,
              AUDIO_CACHE_DIR, VIDEO_CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def bridge_http_url(path: str = "") -> str:
    return f"http://127.0.0.1:{BRIDGE_PORT}{path}"


def http_get(url: str, timeout: int = POLL_TIMEOUT) -> dict | list:
    """Simple HTTP GET, returns parsed JSON."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get_bytes(url: str, timeout: int = 30) -> bytes:
    """HTTP GET returning raw bytes (for media download)."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ── Bridge management ───────────────────────────────────────────────────────


def start_bridge() -> subprocess.Popen:
    """Start the Baileys bridge as a subprocess."""
    env = os.environ.copy()
    env.update({
        "HERMES_IMAGE_CACHE_DIR": str(IMAGE_CACHE_DIR),
        "HERMES_DOCUMENT_CACHE_DIR": str(DOCUMENT_CACHE_DIR),
        "HERMES_AUDIO_CACHE_DIR": str(AUDIO_CACHE_DIR),
        "HERMES_VIDEO_CACHE_DIR": str(VIDEO_CACHE_DIR),
        "WHATSAPP_MODE": "bot",
        # This is a dedicated local logger, not a message-replying bot. Capture
        # every group participant unless the operator explicitly narrows it.
        "WHATSAPP_LOGGER_CAPTURE_GROUPS": "true",
    })
    env.setdefault("WHATSAPP_ALLOWED_USERS", "*")

    log(f"Starting bridge on port {BRIDGE_PORT}...")
    proc = subprocess.Popen(
        ["node", str(BRIDGE_SCRIPT),
         "--port", str(BRIDGE_PORT),
         "--session", str(SESSION_DIR)],
        cwd=str(BRIDGE_DIR),
        env=env,
        # Inherit the terminal/journal so the pairing QR remains visible and
        # bridge logging can never fill an unread subprocess pipe.
        stdout=None,
        stderr=None,
    )
    return proc


def wait_for_bridge(proc: subprocess.Popen,
                    timeout: int = BRIDGE_START_TIMEOUT) -> bool:
    """Wait until the bridge health endpoint responds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            log(f"Bridge exited prematurely (rc={proc.returncode})")
            return False
        try:
            resp = http_get(bridge_http_url("/health"), timeout=3)
            if isinstance(resp, dict) and resp.get("status") in {"connected", "disconnected"}:
                log(f"Bridge HTTP server is ready (WhatsApp: {resp['status']})")
                return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(0.5)
    log("Bridge failed to start within timeout")
    return False


def wait_for_whatsapp_connected(proc: subprocess.Popen,
                                timeout: int = 180) -> bool:
    """Wait until WhatsApp reports `connected` (pairing completed)."""
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        if proc.poll() is not None:
            log(f"Bridge exited before connecting (rc={proc.returncode})")
            return False
        try:
            resp = http_get(bridge_http_url("/health"), timeout=3)
            status = resp.get("status") if isinstance(resp, dict) else None
            if status != last_status:
                log(f"WhatsApp status: {status}")
                last_status = status
            if status == "connected":
                return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(1.0)
    log("Timed out waiting for WhatsApp to connect")
    return False


def stop_bridge(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    log("Stopping bridge...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── Config (hot-reload) ──────────────────────────────────────────────────

_config_cache: dict = {"_mtime": 0, "_data": {}}


def load_config() -> dict:
    """Load config with mtime-based caching — ~0 cost when file unchanged."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except (OSError, FileNotFoundError):
        return _config_cache.setdefault("_data", {})
    if mtime > _config_cache["_mtime"]:
        try:
            with open(CONFIG_PATH) as f:
                _config_cache["_data"] = json.load(f)
            _config_cache["_mtime"] = mtime
            log(f"Config reloaded ({len(_config_cache['_data'].get('recorded_groups', []))} groups)")
        except (json.JSONDecodeError, OSError) as e:
            log(f"WARN: failed to load config: {e}")
    return _config_cache["_data"]


def load_config_full() -> dict:
    """Always re-read config from disk (used by `config` subcommand)."""
    _config_cache["_mtime"] = 0
    return load_config()


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    # Invalidate cache so `run` picks up the new file immediately.
    _config_cache["_mtime"] = 0


def is_group_recorded(chat_id: str, config: dict) -> bool:
    """Check if a group chat should be recorded.
    Supports both old format (list of ID strings) and new format
    (list of {id, name} objects) for backward compatibility."""
    if config.get("record_all", False):
        return True
    for entry in config.get("recorded_groups", []):
        if isinstance(entry, dict):
            if entry.get("id") == chat_id:
                return True
        elif str(entry) == chat_id:
            return True
    return False


# ── Media handling ──────────────────────────────────────────────────────────


def _unique_filename(media_dir: Path, prefix: str, ext: str) -> Path:
    """Generate a unique filename in media_dir using a counter."""
    counter = 1
    while True:
        name = f"{prefix}_{counter:03d}{ext}"
        path = media_dir / name
        if not path.exists():
            return path
        counter += 1


def _copy_or_download_media(source: str, dest: Path) -> Path | None:
    """Copy local file or download URL to dest. Returns dest path on success."""
    try:
        if source.startswith(("http://", "https://")):
            data = http_get_bytes(source)
            dest.write_bytes(data)
        else:
            src_path = Path(source)
            if src_path.exists():
                dest.write_bytes(src_path.read_bytes())
            else:
                log(f"  WARN: media source not found: {source}")
                return None
        return dest
    except Exception as e:
        log(f"  WARN: failed to save media {source}: {e}")
        return None


def save_media(media_urls: list, media_type: str, media_dir: Path,
               base_dir: Path) -> list[str]:
    """Save media files to media_dir. Returns list of relative paths (to base_dir)."""
    saved = []
    prefix_map = {
        "image": "photo",
        "video": "video",
        "audio": "audio",
        "ptt": "voice",
        "document": "doc",
        "sticker": "sticker",
    }
    prefix = prefix_map.get(media_type, "media")

    ext_map = {
        "image": ".jpg",
        "video": ".mp4",
        "audio": ".mp3",
        "ptt": ".ogg",
        "sticker": ".webp",
    }
    default_ext = ext_map.get(media_type, ".bin")

    for url in media_urls:
        ext = default_ext
        if url.startswith(("http://", "https://")):
            for known_ext in [".jpg", ".jpeg", ".png", ".gif", ".webp",
                              ".mp4", ".mov", ".avi", ".ogg", ".mp3",
                              ".m4a", ".pdf", ".docx", ".txt"]:
                if known_ext in url.lower():
                    ext = known_ext
                    break
        else:
            p = Path(url)
            if p.suffix:
                ext = p.suffix

        dest = _unique_filename(media_dir, prefix, ext)
        result = _copy_or_download_media(url, dest)
        if result:
            rel = dest.relative_to(base_dir)
            saved.append(str(rel))
    return saved


# ── Group index (groups_index.md) ─────────────────────────────────────────
#
# A small Markdown table at <LOG_DIR>/groups_index.md listing every group
# that has actually been recorded (i.e. passed is_group_recorded). Columns:
#   Group ID | Group name | Latest message | Monthly file
# The index is rebuilt on startup (from the file itself) and updated on every
# recorded message, debounced to one write per 60s.

_index_cache: dict[str, dict] = {}  # chat_id -> {name, last_ts, month_file}
_index_last_flush: float = 0.0
_index_flush_interval = 60.0  # seconds

# Daily /groups refresh state — when 0, never refreshed; otherwise epoch of
# the last successful refresh. Used to detect group renames once per day.
_last_groups_refresh: float = 0.0
_GROUPS_REFRESH_INTERVAL = 86400.0  # seconds (1 day)


def _load_index_from_disk() -> None:
    """Read existing groups_index.md (if any) into _index_cache.

    This survives process restarts: groups that had messages yesterday but
    none today remain in the index."""
    _index_cache.clear()
    if not INDEX_PATH.exists():
        return
    try:
        text = INDEX_PATH.read_text(encoding="utf-8")
        # Parse table rows like:
        # | `120363XXX@g.us` | 测试群 | 2026-07-18T14:30:01+08:00 | [2026-07.md](groups/120363XXX@g.us/2026-07.md) |
        for line in text.splitlines():
            m = re.match(
                r"^\|\s*`([^`]+@g\.us)`\s*\|\s*(.*?)\s*\|\s*([^|]+?)\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*$",
                line,
            )
            if not m:
                continue
            gid, name, last_ts, month_file, _link = m.groups()
            _index_cache[gid] = {
                "name": name.strip(),
                "last_ts": last_ts.strip(),
                "month_file": month_file.strip(),
            }
        if _index_cache:
            log(f"Index: loaded {len(_index_cache)} group(s) from {INDEX_PATH.name}")
    except Exception as e:
        log(f"WARN: failed to load index: {e}")


def _update_index(chat_id: str, name: str, ts: str, month_str: str) -> None:
    """Update (or insert) one group's entry in the in-memory index."""
    _index_cache[chat_id] = {
        "name": name,
        "last_ts": ts,
        "month_file": f"{month_str}.md",
    }


def _write_index() -> None:
    """Render _index_cache as a Markdown table and write to groups_index.md."""
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Group Index", ""]
    lines.append(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("| Group ID | Group name | Latest message | Monthly file |")
    lines.append("|-------|------|---------|---------|")
    # Sort by last_ts descending (most recently active first)
    for gid, info in sorted(_index_cache.items(),
                            key=lambda kv: kv[1].get("last_ts", ""),
                            reverse=True):
        name = info.get("name", gid.split("@")[0])
        last_ts = info.get("last_ts", "")
        month_file = info.get("month_file", "")
        link = f"groups/{gid}/{month_file}"
        lines.append(
            f"| `{gid}` | {name} | {last_ts} | [{month_file}]({link}) |"
        )
    INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _maybe_flush_index(force: bool = False) -> None:
    """Debounced write of groups_index.md (or immediate if force=True)."""
    global _index_last_flush
    now = time.time()
    if not force and (now - _index_last_flush) < _index_flush_interval:
        return
    try:
        _write_index()
        _index_last_flush = now
    except Exception as e:
        log(f"WARN: failed to flush index: {e}")


def _maybe_refresh_group_names() -> None:
    """Once per day, call /groups on the bridge to detect group renames.

    Only updates groups already in _index_cache — does not add new ones
    (those grow organically as messages arrive)."""
    global _last_groups_refresh
    now = time.time()
    if (now - _last_groups_refresh) < _GROUPS_REFRESH_INTERVAL:
        return
    _last_groups_refresh = now
    try:
        data = http_get(bridge_http_url("/groups"), timeout=15)
        groups = data.get("groups", []) if isinstance(data, dict) else []
        gid_to_name = {
            g.get("id"): g.get("name")
            for g in groups
            if isinstance(g, dict) and g.get("id") and g.get("name")
        }
        changed = []
        for gid, cached in _index_cache.items():
            new_name = gid_to_name.get(gid)
            if new_name and new_name != cached.get("name"):
                old_name = cached.get("name")
                cached["name"] = new_name
                changed.append((gid, old_name, new_name))
        if changed:
            log(f"Index: {len(changed)} group(s) renamed:")
            for gid, old, new in changed:
                log(f"  {gid}: {old!r} -> {new!r}")
            _maybe_flush_index(force=True)
    except Exception as e:
        log(f"WARN: /groups refresh failed (will retry next day): {e}")


# ── Message processing ─────────────────────────────────────────────────────


def _last_date_in_file(md_path: Path) -> str:
    """Read the tail of md_path and return the last '## YYYY-MM-DD' header,
    or empty string if none found."""
    if not md_path.exists():
        return ""
    try:
        size = md_path.stat().st_size
        with open(md_path, "rb") as f:
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", errors="replace")
        # Match the last ## YYYY-MM-DD line
        matches = re.findall(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$", tail, re.MULTILINE)
        return matches[-1] if matches else ""
    except Exception:
        return ""


def _local_dt_from_ts(ts_raw) -> datetime:
    """Convert a WhatsApp timestamp to a local tz-aware datetime."""
    if ts_raw:
        try:
            return datetime.fromtimestamp(int(ts_raw), tz=timezone.utc).astimezone()
        except (ValueError, TypeError, OSError):
            pass
    return datetime.now().astimezone()


def _short_id(jid: str) -> str:
    """Return the user part of a JID (e.g. '65xxxxxxxx' from '65xxxxxxxx@s.whatsapp.net')."""
    return jid.split("@")[0] if jid else ""


def _message_type(media_type: str, has_quote: bool) -> str:
    """Classify a message for the JSONL 'type' field. Reply is orthogonal and
    surfaced via reply_to fields instead of overloading type."""
    if media_type:
        return media_type
    return "text"


def process_message(data: dict) -> None:
    """Process one WhatsApp message: save to per-group markdown + JSONL."""
    if not data.get("isGroup"):
        return

    chat_id = data.get("chatId", "")
    chat_name = data.get("chatName") or chat_id.split("@")[0] or "unknown"
    sender_name = data.get("senderName") or data.get("senderId", "unknown")
    sender_id = data.get("senderId", "")
    message_id = data.get("messageId", "")
    body = data.get("body", "") or ""
    ts_raw = data.get("timestamp")
    has_media = data.get("hasMedia", False)
    media_type = data.get("mediaType", "")
    media_urls = data.get("mediaUrls", []) or []

    # Reply context
    has_quote = bool(data.get("hasQuotedMessage"))
    quoted_participant = data.get("quotedParticipant") or ""
    quoted_msg_id = data.get("quotedMessageId") or ""

    cfg = load_config()
    if not is_group_recorded(chat_id, cfg):
        return

    # Daily /groups refresh to detect renames (cheap: once per day)
    _maybe_refresh_group_names()

    dt = _local_dt_from_ts(ts_raw)
    date_str = dt.strftime("%Y-%m-%d")
    month_str = dt.strftime("%Y-%m")
    time_str = dt.strftime("%H:%M:%S")
    iso_ts = dt.isoformat(timespec="seconds")

    # Per-group per-month layout:
    #   <LOG_DIR>/groups/<chat_id>/<YYYY-MM>.md
    #   <LOG_DIR>/groups/<chat_id>/<YYYY-MM>.jsonl
    #   <LOG_DIR>/groups/<chat_id>/attachments/<YYYY-MM-DD>/
    group_dir = LOG_DIR / "groups" / chat_id
    group_dir.mkdir(parents=True, exist_ok=True)
    media_dir = group_dir / "attachments" / date_str

    media_links = []
    if has_media and media_urls:
        media_dir.mkdir(parents=True, exist_ok=True)
        # base_dir = group_dir so saved paths are relative to the group dir
        # (md file lives in group_dir, so links resolve correctly)
        media_links = save_media(media_urls, media_type, media_dir, base_dir=group_dir)

    # ── Markdown ──
    md_path = group_dir / f"{month_str}.md"
    needs_file_header = not md_path.exists()
    last_date = _last_date_in_file(md_path)
    needs_date_header = (last_date != date_str)

    with open(md_path, "a", encoding="utf-8") as f:
        if needs_file_header:
            f.write(f"# {chat_name} `({chat_id})` — {month_str}\n\n")
        if needs_date_header:
            f.write(f"## {date_str}\n\n")

        # Message line: **sender** `(JID)` HH:MM:SS:
        # Reply inline (no quoted text): ↩@short_num #quoted_msg_id:
        if has_quote:
            short = _short_id(quoted_participant)
            ref = f" #{quoted_msg_id}" if quoted_msg_id else ""
            f.write(f"**{sender_name}** `({sender_id})` {time_str} ↩@{short}{ref}:\n")
        else:
            f.write(f"**{sender_name}** `({sender_id})` {time_str}:\n")
        if message_id:
            f.write(f"[{message_id}] {body}\n")
        else:
            f.write(f"{body}\n")

        for link in media_links:
            # link is relative to group_dir; md file is in group_dir, so use directly
            f.write(f"![{media_type}]({link})\n")

        f.write("\n")

    # ── JSONL sidecar ──
    jsonl_path = group_dir / f"{month_str}.jsonl"
    record = {
        "ts": iso_ts,
        "gid": chat_id,
        "gname": chat_name,
        "sid": sender_id,
        "name": sender_name,
        "mid": message_id,
        "type": _message_type(media_type, has_quote),
        "body": body,
    }
    if has_quote:
        record["reply_to"] = quoted_msg_id
        record["reply_to_sid"] = quoted_participant
    if media_links:
        record["media"] = media_links
        record["media_type"] = media_type

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── Index ──
    _update_index(chat_id, chat_name, iso_ts, month_str)
    _maybe_flush_index()

    log(f"[{date_str} {time_str}] {chat_name} / {sender_name}: {body[:60]}{'...' if len(body) > 60 else ''}")


# ── Recording loop ──────────────────────────────────────────────────────────


def poll_loop(bridge_proc: subprocess.Popen) -> None:
    """Continuously poll the bridge for new messages."""
    known_ids: set[str] = set()

    while True:
        if bridge_proc.poll() is not None:
            log(f"Bridge exited (rc={bridge_proc.returncode}), restarting...")
            return  # Let caller handle restart

        try:
            messages = http_get(bridge_http_url("/messages"), timeout=POLL_TIMEOUT)
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            log(f"Poll error: {e}")
            time.sleep(5)
            continue
        except Exception as e:
            log(f"Unexpected poll error: {e}")
            time.sleep(5)
            continue

        if not isinstance(messages, list):
            time.sleep(POLL_INTERVAL)
            continue

        for msg_data in messages:
            if not isinstance(msg_data, dict):
                continue

            msg_id = msg_data.get("id") or msg_data.get("key", {}).get("id")
            if msg_id:
                if msg_id in known_ids:
                    continue
                known_ids.add(msg_id)
                if len(known_ids) > 10000:
                    known_ids = set(list(known_ids)[-5000:])

            try:
                process_message(msg_data)
            except Exception as e:
                log(f"Error processing message: {e}")

        time.sleep(POLL_INTERVAL)


def run() -> None:
    """Main entry point: start bridge and poll loop with auto-restart."""
    ensure_dirs()
    log(f"Log directory: {LOG_DIR}")
    log(f"Session directory: {SESSION_DIR}")
    log(f"Config file: {CONFIG_PATH}")
    log(f"Index file: {INDEX_PATH}")

    # Restore index from disk so previously-recorded groups survive restart
    _load_index_from_disk()

    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("ERROR: Node.js not found. Please install Node.js first.")
        sys.exit(1)

    if not BRIDGE_SCRIPT.exists():
        log(f"ERROR: Bridge script not found at {BRIDGE_SCRIPT}")
        sys.exit(1)

    node_modules = BRIDGE_DIR / "node_modules"
    if not node_modules.exists():
        log("Installing bridge dependencies...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(BRIDGE_DIR),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"npm install failed:\n{result.stdout}\n{result.stderr}")
            sys.exit(1)
        log("Dependencies installed.")

    while True:
        bridge_proc = start_bridge()
        if not wait_for_bridge(bridge_proc):
            stop_bridge(bridge_proc)
            log("Bridge failed to start. Retrying in 10 seconds...")
            time.sleep(10)
            continue

        try:
            poll_loop(bridge_proc)
        except KeyboardInterrupt:
            log("Shutting down...")
            stop_bridge(bridge_proc)
            _maybe_flush_index(force=True)
            break
        except Exception as e:
            log(f"Poll loop error: {e}")
            stop_bridge(bridge_proc)
            _maybe_flush_index(force=True)
            log("Restarting in 5 seconds...")
            time.sleep(5)


# ── `config account` subcommand: pairing ─────────────────────────────────


def _backup_session_dir() -> None:
    """If a non-empty session/ exists, rename it to session.backup-<timestamp>.

    This is invoked by `config account` so a fresh QR code is shown for the
    new account. The old session is kept (renamed, not deleted) so the user
    can recover it if needed."""
    if not SESSION_DIR.exists() or not any(SESSION_DIR.iterdir()):
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = SESSION_DIR.parent / f"session.backup-{ts}"
    # In the rare case a backup with the same timestamp exists, append a counter
    counter = 1
    while backup.exists():
        backup = SESSION_DIR.parent / f"session.backup-{ts}-{counter}"
        counter += 1
    SESSION_DIR.rename(backup)
    log(f"Old session backed up: {backup}")
    log(f"(To restore it later: stop the service, move it back to {SESSION_DIR.name})")


def cmd_config_account(args: argparse.Namespace) -> None:
    """Pair a (new) WhatsApp account: back up any old session, start bridge,
    show the QR code, wait for connection."""
    apply_overrides(args.port, args.log_dir, args.data_dir)
    ensure_dirs()

    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("ERROR: Node.js not found. Please install Node.js first.")
        sys.exit(1)

    if not BRIDGE_SCRIPT.exists():
        log(f"ERROR: Bridge script not found at {BRIDGE_SCRIPT}")
        sys.exit(1)

    node_modules = BRIDGE_DIR / "node_modules"
    if not node_modules.exists():
        log("Installing bridge dependencies...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(BRIDGE_DIR),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"npm install failed:\n{result.stdout}\n{result.stderr}")
            sys.exit(1)
        log("Dependencies installed.")

    log(f"Log directory: {LOG_DIR}")
    log(f"Session directory: {SESSION_DIR}")

    # Back up any existing session so a fresh QR code is presented for the
    # new account. The old session is renamed, not deleted.
    _backup_session_dir()
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    bridge_proc = start_bridge()
    paired = False
    try:
        if not wait_for_bridge(bridge_proc):
            stop_bridge(bridge_proc)
            log("ERROR: Bridge failed to start.")
            sys.exit(1)

        print()
        print("Open WhatsApp on your phone:")
        print("  Settings -> Linked Devices -> Link a Device")
        print("and scan the QR code shown above.")
        print()

        if wait_for_whatsapp_connected(bridge_proc, timeout=300):
            print()
            log("✅ WhatsApp connected! Pairing complete.")
            log(f"   Session saved at: {SESSION_DIR}")
            paired = True
        else:
            log("ERROR: Did not detect a successful pairing.")
            log("       Re-run `logger.py config account` and try again.")
    except KeyboardInterrupt:
        print()
        log("Interrupted. Pairing not completed.")
    finally:
        stop_bridge(bridge_proc)

    if paired:
        # Start the background service so the bridge is available for config group.
        log("Starting background service...")
        result = subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log(f"ERROR: systemctl daemon-reload failed: {result.stderr.strip()}")
            log("You can manually run:")
            log("  systemctl --user daemon-reload")
            log("  systemctl --user start whatsapp-logger")
            sys.exit(1)

        result = subprocess.run(
            ["systemctl", "--user", "start", "whatsapp-logger"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log(f"ERROR: systemctl start failed: {result.stderr.strip()}")
            log("You can manually run:")
            log("  systemctl --user start whatsapp-logger")
            sys.exit(1)

        # Wait for the service's bridge to be reachable.
        log("Waiting for the service to be ready...")
        deadline = time.time() + 30
        service_ok = False
        while time.time() < deadline:
            try:
                resp = http_get(bridge_http_url("/health"), timeout=3)
                if isinstance(resp, dict) and resp.get("status") == "connected":
                    service_ok = True
                    break
            except Exception:
                pass
            time.sleep(1)

        if service_ok:
            log("✅ Service is running. Switching to group configuration...")
            print()
            # Proceed directly to group selection (interactive mode).
            group_args = argparse.Namespace(
                port=args.port,
                log_dir=args.log_dir,
                data_dir=args.data_dir,
                list=False,
                record_all=False,
                init=False,
                add=None,
                remove=None,
            )
            cmd_config_group(group_args)
        else:
            log("Service started but bridge is not ready yet.")
            log("Check status:  systemctl --user status whatsapp-logger")
            log("Check logs:    journalctl --user -u whatsapp-logger -f")
            log("Then run:      python3 config group")


# ── `config` subcommand: group selection ──────────────────────────────────
#
# Merged from group_selector.py. The logger must already be running (via
# `logger.py run` or systemd) so the bridge is up and `/groups` can be
# queried.


def _config_http_get(path: str) -> dict:
    url = bridge_http_url(path)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _fetch_groups() -> list:
    """Fetch all participating groups from the running bridge."""
    try:
        data = _config_http_get("/groups")
        return data.get("groups", [])
    except (urllib.error.URLError, ConnectionRefusedError) as e:
        print(f"❌ Cannot connect to bridge on port {BRIDGE_PORT}")
        print(f"   Is the logger running? Error: {e}")
        print()
        print("Start it with one of:")
        print(f"  systemctl --user start whatsapp-logger")
        print(f"  python3 {Path(__file__).resolve()} run")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to fetch groups: {e}")
        sys.exit(1)


def _recorded_ids(cfg: dict) -> set[str]:
    """Extract IDs from recorded_groups, supporting both old and new format."""
    ids = set()
    for entry in cfg.get("recorded_groups", []):
        if isinstance(entry, dict):
            ids.add(entry["id"])
        else:
            ids.add(str(entry))
    return ids


def _build_recorded_entry(g: dict) -> dict:
    return {"id": g["id"], "name": g["name"]}


def _groups_by_id(groups: list) -> dict[str, dict]:
    return {g["id"]: g for g in groups}


def _pick_groups_interactive(groups: list, current_entries: list) -> list[dict]:
    """Interactive prompt to select groups. Returns list of {id, name}."""
    groups_map = _groups_by_id(groups)
    current_ids = _recorded_ids({"recorded_groups": current_entries})
    selected_ids = set(current_ids)

    print(f"\n{'=' * 60}")
    print(f"  WhatsApp Groups ({len(groups)} total)")
    print(f"{'=' * 60}")
    print(f"  {'#':>3}  {'Name':<50} {'Members':>7}")
    print(f"  {'─' * 62}")
    for i, g in enumerate(groups, 1):
        mark = "✓" if g["id"] in selected_ids else " "
        print(f"  {mark} {i:>2}. {g['name'][:48]:<48} {g['participantCount']:>5}")
    print(f"  {'─' * 62}")
    print()
    print("  Enter group numbers to toggle (e.g. '1 3 5'), or:")
    print("    a - select all")
    print("    n - select none")
    print("    q - quit without saving")
    print("    done - save and exit")
    print()

    while True:
        try:
            cmd = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if cmd in ("q", "quit"):
            print("  Cancelled.")
            return []

        if cmd == "done":
            break

        if cmd == "a":
            selected_ids = {g["id"] for g in groups}
            print(f"  → All {len(selected_ids)} groups selected")
            continue

        if cmd == "n":
            selected_ids = set()
            print("  → No groups selected")
            continue

        parts = cmd.split()
        for p in parts:
            try:
                idx = int(p) - 1
                if 0 <= idx < len(groups):
                    gid = groups[idx]["id"]
                    if gid in selected_ids:
                        selected_ids.discard(gid)
                        print(f"  ✗ Deselected: {groups[idx]['name']}")
                    else:
                        selected_ids.add(gid)
                        print(f"  ✓ Selected:  {groups[idx]['name']}")
                else:
                    print(f"  ⚠ Invalid number: {p}")
            except ValueError:
                print(f"  ⚠ Invalid input: {p}")

    result = []
    for gid in sorted(selected_ids):
        g = groups_map.get(gid)
        result.append({"id": gid, "name": g["name"] if g else gid.split("@")[0]})
    return result


def _cmd_config_list(groups: list, cfg: dict) -> None:
    recorded = _recorded_ids(cfg)
    record_all = cfg.get("record_all", False)

    print(f"\n{'=' * 60}")
    print(f"  WhatsApp Groups ({len(groups)} total)")
    if record_all:
        print(f"  Status: 🔴 Recording ALL groups")
    else:
        print(f"  Status: Recording {len(recorded)}/{len(groups)} groups")
    print(f"{'=' * 60}")
    print(f"  {' ':>3}  {'Name':<50} {'Members':>7}")
    print(f"  {'─' * 62}")
    for g in groups:
        mark = "✓" if g["id"] in recorded else " "
        print(f"  {mark} {g['name'][:48]:<48} {g['participantCount']:>5}")
    print(f"  {'─' * 62}")
    print(f"  Config: {CONFIG_PATH}")
    print()


def _cmd_config_add(groups: list, cfg: dict, name: str) -> None:
    recorded = cfg.get("recorded_groups", [])
    recorded_id_set = _recorded_ids(cfg)

    matched = [g for g in groups if name.lower() in g["name"].lower()]
    if not matched:
        print(f"❌ No group found matching '{name}'")
        sys.exit(1)

    for g in matched:
        if g["id"] not in recorded_id_set:
            recorded.append(_build_recorded_entry(g))
            recorded_id_set.add(g["id"])
            print(f"  ✓ Added: {g['name']}")
        else:
            print(f"  - Already recorded: {g['name']}")

    cfg["recorded_groups"] = recorded
    cfg["record_all"] = False
    save_config(cfg)
    print(f"✅ Config saved: {CONFIG_PATH}")


def _cmd_config_remove(groups: list, cfg: dict, name: str) -> None:
    recorded = cfg.get("recorded_groups", [])
    recorded_id_set = _recorded_ids(cfg)

    matched = [g for g in groups if name.lower() in g["name"].lower()]
    if not matched:
        print(f"❌ No group found matching '{name}'")
        sys.exit(1)

    for g in matched:
        if g["id"] in recorded_id_set:
            recorded = [e for e in recorded
                        if (isinstance(e, dict) and e["id"] != g["id"])
                        or (not isinstance(e, dict) and str(e) != g["id"])]
            recorded_id_set.discard(g["id"])
            print(f"  ✗ Removed: {g['name']}")
        else:
            print(f"  - Not recorded: {g['name']}")

    cfg["recorded_groups"] = recorded
    cfg["record_all"] = False
    save_config(cfg)
    print(f"✅ Config saved: {CONFIG_PATH}")


def _cmd_config_init(groups: list) -> None:
    entries = [_build_recorded_entry(g) for g in groups]
    cfg = {"recorded_groups": entries, "record_all": False}
    save_config(cfg)
    print(f"✅ Config saved: {CONFIG_PATH}")
    print(f"   Recording all {len(entries)} groups. Edit later with `logger config group`.")


def _cmd_config_record_all() -> None:
    cfg = load_config_full()
    cfg["record_all"] = True
    cfg["recorded_groups"] = []
    save_config(cfg)
    print(f"✅ Config saved: {CONFIG_PATH}")
    print("   Will record ALL groups (including new ones added later).")


def cmd_config_group(args: argparse.Namespace) -> None:
    apply_overrides(args.port, args.log_dir, args.data_dir)
    groups = _fetch_groups()
    cfg = load_config_full()

    if args.list:
        _cmd_config_list(groups, cfg)
    elif args.record_all:
        _cmd_config_record_all()
    elif args.init:
        _cmd_config_init(groups)
    elif args.add:
        _cmd_config_add(groups, cfg, args.add)
    elif args.remove:
        _cmd_config_remove(groups, cfg, args.remove)
    else:
        result = _pick_groups_interactive(groups, cfg.get("recorded_groups", []))
        if result:
            cfg["recorded_groups"] = result
            cfg["record_all"] = False
            save_config(cfg)
            print(f"✅ Config saved: {CONFIG_PATH}")
            print(f"   Recording {len(result)} groups. Takes effect immediately.")


# ── `run` subcommand wrapper ───────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> None:
    apply_overrides(args.port, args.log_dir, args.data_dir)
    run()


# ── CLI ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logger.py",
        description="WhatsApp Group Chat Logger",
    )
    parser.add_argument("--port", type=int, default=BRIDGE_PORT,
                        help=f"Bridge HTTP port (default: {BRIDGE_PORT}, "
                             f"env: WHATSAPP_LOGGER_PORT)")
    parser.add_argument("--log-dir", type=str, default=str(LOG_DIR),
                        help=f"Log output directory (default: {LOG_DIR}, "
                             f"env: WHATSAPP_LOGGER_LOG_DIR)")
    parser.add_argument("--data-dir", type=str, default=str(BRIDGE_DATA_DIR),
                        help=f"Data directory for session+cache+config.json "
                             f"(default: {BRIDGE_DATA_DIR}, "
                             f"env: WHATSAPP_LOGGER_DATA_DIR)")

    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run",
                           help="Start the recording loop (default).")

    p_cfg = sub.add_parser("config",
                           help="Configuration: pair a WhatsApp account or select groups.")
    cfg_sub = p_cfg.add_subparsers(dest="config_command")

    cfg_sub.add_parser("account",
                       help="Pair a (new) WhatsApp account: backs up old session, "
                            "shows QR code, waits for connection.")

    p_group = cfg_sub.add_parser("group",
                                help="Select which groups to record (requires logger running).")
    p_group.add_argument("--list", action="store_true",
                         help="List all groups and current recording status")
    p_group.add_argument("--record-all", action="store_true",
                         help="Record all groups (including future ones)")
    p_group.add_argument("--init", action="store_true",
                         help="Record all current groups (first-time setup)")
    p_group.add_argument("--add", metavar="NAME",
                         help="Add groups matching NAME (substring match)")
    p_group.add_argument("--remove", metavar="NAME",
                         help="Remove groups matching NAME (substring match)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    command = args.command or "run"
    if command == "run":
        cmd_run(args)
    elif command == "config":
        config_command = args.config_command
        if config_command == "account":
            cmd_config_account(args)
        elif config_command == "group":
            cmd_config_group(args)
        else:
            parser.parse_args(["config", "--help"])
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
