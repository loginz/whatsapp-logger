# WhatsApp Logger Archive Reference

## Archive layout

```text
<log-root>/
├── groups_index.md
└── groups/<group-jid>/
    ├── YYYY-MM.jsonl
    ├── YYYY-MM.md
    └── attachments/YYYY-MM-DD/
```

`groups_index.md` maps group IDs to current names and recent files. A group name stored on an old message may differ from its current name.

## JSONL fields

Each non-empty line is one message object:

| Field | Meaning |
|---|---|
| `ts` | ISO 8601 timestamp with UTC offset |
| `gid` | Group JID |
| `gname` | Group name when the message was recorded |
| `sid` | Sender JID |
| `name` | Sender display name |
| `mid` | Message ID |
| `type` | `text`, `image`, `video`, `audio`, `ptt`, `document`, `sticker`, `location`, `contact`, `reaction`, or `poll` |
| `body` | Text or textual representation recorded by the logger |
| `reply_to` | Optional parent message ID |
| `reply_to_sid` | Optional parent sender JID |
| `media` | Optional array of paths relative to the group directory |
| `media_type` | Optional media category |

Do not assume the body contains OCR, audio transcription, or the contents of a document. An attachment's existence is evidence of sharing, not evidence of its unseen contents.

## Markdown fallback

Monthly Markdown files organize messages under `## YYYY-MM-DD`. A message begins with a bold sender line and then `[message-id] body`. Replies contain `#parent-message-id`. Media links are relative to the group directory.

Use Markdown when JSONL is missing or when visual conversational context is easier to recover there. Prefer JSONL for filtering and counts.

## Collector behavior

`scripts/collect_messages.py` reads `groups/*/*.jsonl`, validates timestamps, filters records, removes duplicate `(gid, mid)` messages by default, and sorts chronologically. It adds:

- `_source_file`: source path relative to the log root
- `_source_line`: one-based JSONL line number

Date-only `--start` and `--end` bounds are inclusive local calendar dates. Datetime bounds use the offset supplied in the value; a naive datetime uses the system timezone. `--month YYYY-MM` selects that complete calendar month. Repeated `--group` filters are OR conditions matched case-insensitively against `gid` and `gname`.

Malformed records produce warnings on standard error and are skipped. Use `--strict` to fail immediately instead.
