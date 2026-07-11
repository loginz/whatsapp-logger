#!/usr/bin/env python3
"""
WhatsApp Group Chat Logger

Standalone service that:
1. Starts a Baileys bridge (Node.js subprocess)
2. Polls for incoming WhatsApp messages
3. Saves group chat messages to daily markdown files
4. Downloads and links media attachments

Completely independent from Hermes — no LLM processing, no replies.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config (can be overridden via CLI args or env vars) ─────────────────────

BRIDGE_PORT = int(os.environ.get("WHATSAPP_LOGGER_PORT", "3001"))
BRIDGE_DIR = Path(__file__).resolve().parent / "bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
POLL_INTERVAL = 1.0  # seconds between polls
POLL_TIMEOUT = 30  # seconds for each /messages HTTP request

# Output directory (logs + attachments)
DEFAULT_LOG_DIR = Path.home() / ".hermes" / "data" / "whatsapp-logger"
LOG_DIR = Path(os.environ.get("WHATSAPP_LOGGER_LOG_DIR", str(DEFAULT_LOG_DIR)))

# Bridge data directory (session + media cache)
DEFAULT_BRIDGE_DATA = Path.home() / ".hermes" / "whatsapp-logger"
BRIDGE_DATA_DIR = Path(os.environ.get("WHATSAPP_LOGGER_DATA_DIR", str(DEFAULT_BRIDGE_DATA)))
SESSION_DIR = BRIDGE_DATA_DIR / "session"
IMAGE_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "images"
DOCUMENT_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "documents"
AUDIO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "audio"
VIDEO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "video"

# Max retries for bridge health check
BRIDGE_START_TIMEOUT = 30  # seconds

# ── Helpers ─────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


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


def wait_for_bridge(proc: subprocess.Popen, timeout: int = BRIDGE_START_TIMEOUT) -> bool:
    """Wait until the bridge health endpoint responds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check if process died
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


def save_media(media_urls: list, media_type: str, media_dir: Path) -> list[str]:
    """Save media files to media_dir. Returns list of relative paths."""
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
            # Try to guess extension from URL
            for known_ext in [".jpg", ".jpeg", ".png", ".gif", ".webp",
                              ".mp4", ".mov", ".avi", ".ogg", ".mp3",
                              ".m4a", ".pdf", ".docx", ".txt"]:
                if known_ext in url.lower():
                    ext = known_ext
                    break
        else:
            # Local file: use original extension
            p = Path(url)
            if p.suffix:
                ext = p.suffix

        dest = _unique_filename(media_dir, prefix, ext)
        result = _copy_or_download_media(url, dest)
        if result:
            rel = dest.relative_to(LOG_DIR)
            saved.append(str(rel))
    return saved


# ── Message processing ─────────────────────────────────────────────────────


def process_message(data: dict) -> None:
    """Process one WhatsApp message: save to markdown if it's a group message."""
    # Only process group messages
    if not data.get("isGroup"):
        return

    chat_name = data.get("chatName") or data.get("chatId", "unknown")
    sender_name = data.get("senderName") or data.get("senderId", "unknown")
    body = data.get("body", "") or ""
    ts_raw = data.get("timestamp")
    has_media = data.get("hasMedia", False)
    media_type = data.get("mediaType", "")
    media_urls = data.get("mediaUrls", []) or []

    # Parse timestamp
    if ts_raw:
        try:
            dt = datetime.fromtimestamp(int(ts_raw))
        except (ValueError, TypeError):
            dt = datetime.now()
    else:
        dt = datetime.now()

    date_str = dt.strftime("%Y-%m-%d")
    month_str = dt.strftime("%Y-%m")
    time_str = dt.strftime("%H:%M:%S")

    # Keep each daily log and its attachments under the same month.
    month_dir = LOG_DIR / month_str
    month_dir.mkdir(parents=True, exist_ok=True)
    media_dir = month_dir / "attachments" / date_str
    media_dir.mkdir(parents=True, exist_ok=True)

    # Save media
    media_links = []
    if has_media and media_urls:
        saved = save_media(media_urls, media_type, media_dir)
        media_links = saved

    # Append to daily markdown
    md_path = month_dir / f"{date_str}.md"

    # Write header if new file
    needs_header = not md_path.exists()

    with open(md_path, "a", encoding="utf-8") as f:
        if needs_header:
            f.write(f"# 群聊消息 - {date_str}\n\n")

        # Check if this is a new chat (different from last)
        f.write(f"## {time_str} {chat_name}\n\n")
        f.write(f"**{sender_name}** ({time_str}):\n")
        f.write(f"{body}\n")

        for link in media_links:
            target = LOG_DIR / link
            relative_link = Path(os.path.relpath(target, md_path.parent)).as_posix()
            f.write(f"![{media_type}]({relative_link})\n")

        f.write("\n")

    log(f"[{date_str} {time_str}] {chat_name} / {sender_name}: {body[:60]}{'...' if len(body) > 60 else ''}")


# ── Main loop ───────────────────────────────────────────────────────────────


def poll_loop(bridge_proc: subprocess.Popen) -> None:
    """Continuously poll the bridge for new messages."""
    known_ids: set[str] = set()

    while True:
        # Check if bridge is still alive
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

            # Deduplicate by message ID
            msg_id = msg_data.get("id") or msg_data.get("key", {}).get("id")
            if msg_id:
                if msg_id in known_ids:
                    continue
                known_ids.add(msg_id)
                # Keep set bounded
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

    # Check Node.js
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("ERROR: Node.js not found. Please install Node.js first.")
        sys.exit(1)

    # Check bridge script
    if not BRIDGE_SCRIPT.exists():
        log(f"ERROR: Bridge script not found at {BRIDGE_SCRIPT}")
        sys.exit(1)

    # Check bridge dependencies
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

    # Main loop with auto-restart
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
            break
        except Exception as e:
            log(f"Poll loop error: {e}")
            stop_bridge(bridge_proc)
            log("Restarting in 5 seconds...")
            time.sleep(5)


# ── Entry ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp Group Chat Logger")
    parser.add_argument("--port", type=int, default=BRIDGE_PORT,
                        help=f"Bridge HTTP port (default: {BRIDGE_PORT}, env: WHATSAPP_LOGGER_PORT)")
    parser.add_argument("--log-dir", type=str, default=str(LOG_DIR),
                        help=f"Log output directory (default: {LOG_DIR}, env: WHATSAPP_LOGGER_LOG_DIR)")
    parser.add_argument("--data-dir", type=str, default=str(BRIDGE_DATA_DIR),
                        help=f"Bridge data directory for session+cache (default: {BRIDGE_DATA_DIR}, env: WHATSAPP_LOGGER_DATA_DIR)")
    args = parser.parse_args()

    BRIDGE_PORT = args.port
    LOG_DIR = Path(args.log_dir).expanduser().resolve()
    BRIDGE_DATA_DIR = Path(args.data_dir).expanduser().resolve()
    SESSION_DIR = BRIDGE_DATA_DIR / "session"
    IMAGE_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "images"
    DOCUMENT_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "documents"
    AUDIO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "audio"
    VIDEO_CACHE_DIR = BRIDGE_DATA_DIR / "cache" / "video"

    # Handle signals gracefully
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    run()
