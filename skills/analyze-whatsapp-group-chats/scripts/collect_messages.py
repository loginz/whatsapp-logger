#!/usr/bin/env python3
"""Collect and filter whatsapp-logger JSONL messages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


def parse_bound(value: str, *, end: bool) -> datetime:
    """Parse an ISO date/datetime; make a date-only end inclusive."""
    try:
        if "T" not in value and " " not in value:
            day = date.fromisoformat(value)
            bound = datetime.combine(day, time.max if end else time.min)
        else:
            bound = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date or datetime: {value}") from exc
    if bound.tzinfo is None:
        bound = bound.astimezone()
    return bound


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("ts must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def calendar_month(value: str) -> tuple[datetime, datetime]:
    try:
        start_day = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("month must use YYYY-MM") from exc
    next_month = (start_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (
        datetime.combine(start_day, time.min).astimezone(),
        datetime.combine(next_month - timedelta(days=1), time.max).astimezone(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter whatsapp-logger JSONL archives and emit sorted JSONL."
    )
    parser.add_argument(
        "log_root",
        nargs="?",
        default=os.environ.get("WHATSAPP_LOGGER_LOG_DIR", "logs"),
        help="archive root containing groups/ (default: env or ./logs)",
    )
    parser.add_argument("--month", help="complete calendar month in YYYY-MM")
    parser.add_argument("--start", help="inclusive ISO date or datetime")
    parser.add_argument("--end", help="inclusive ISO date or datetime")
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="case-insensitive gid or group-name substring; repeat for OR",
    )
    parser.add_argument(
        "--keep-duplicates", action="store_true", help="do not deduplicate by gid and mid"
    )
    parser.add_argument("--strict", action="store_true", help="fail on the first bad record")
    return parser


def warn_or_fail(message: str, strict: bool) -> None:
    if strict:
        raise ValueError(message)
    print(f"warning: {message}", file=sys.stderr)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.month and (args.start or args.end):
        parser.error("--month cannot be combined with --start or --end")

    start: datetime | None = None
    end: datetime | None = None
    if args.month:
        start, end = calendar_month(args.month)
    else:
        if args.start:
            start = parse_bound(args.start, end=False)
        if args.end:
            end = parse_bound(args.end, end=True)
    if start and end and start > end:
        parser.error("--start must not be after --end")

    root = Path(args.log_root).expanduser().resolve()
    groups_dir = root / "groups"
    if not groups_dir.is_dir():
        parser.error(f"groups directory not found: {groups_dir}")

    filters = [item.casefold() for item in args.group]
    records: list[tuple[datetime, str, int, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()

    for path in sorted(groups_dir.glob("*/*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, 1):
                if not raw_line.strip():
                    continue
                location = f"{path}:{line_number}"
                try:
                    record = json.loads(raw_line)
                    if not isinstance(record, dict):
                        raise ValueError("record must be a JSON object")
                    timestamp = parse_timestamp(record.get("ts"))
                except (json.JSONDecodeError, ValueError) as exc:
                    warn_or_fail(f"{location}: {exc}", args.strict)
                    continue

                if start and timestamp < start:
                    continue
                if end and timestamp > end:
                    continue
                haystack = f"{record.get('gid', '')}\n{record.get('gname', '')}".casefold()
                if filters and not any(item in haystack for item in filters):
                    continue

                gid = str(record.get("gid", ""))
                mid = str(record.get("mid", ""))
                key = (gid, mid)
                if not args.keep_duplicates and gid and mid:
                    if key in seen:
                        continue
                    seen.add(key)

                record["_source_file"] = str(path.relative_to(root))
                record["_source_line"] = line_number
                records.append((timestamp, str(path), line_number, record))

    records.sort(key=lambda item: (item[0], item[1], item[2]))
    for _, _, _, record in records:
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
