---
name: analyze-whatsapp-group-chats
description: Analyze WhatsApp group-chat logs produced by whatsapp-logger, especially monthly JSONL and Markdown files under logs/groups. Use for weekly or monthly chat reports, urgent and important matter detection, decisions and deadlines, completed-versus-outstanding work summaries, action-item tracking, participation and content statistics, or evidence-backed status reports across one or more groups.
---

# Analyze WhatsApp Group Chats

Produce concise, evidence-backed operational summaries from the logger's local archives. Treat chat statements as evidence, not guaranteed facts, and keep uncertain status visible.

## Establish the scope

1. Resolve the log root from the path supplied by the user, `WHATSAPP_LOGGER_LOG_DIR`, or `<project>/logs` in that order.
2. Interpret relative periods in the user's timezone. Treat a week as Monday through Sunday unless the user specifies otherwise. State exact start and end dates in the report.
3. Select the requested groups. Use `groups_index.md` to resolve names when available; if a name matches multiple groups, show the ambiguity instead of silently choosing one.
4. For a historical period, determine status using evidence at or before the period end. Use later messages only when the user requests current status or follow-through, and label such evidence as post-period context.
5. If the request is broad, analyze all recorded groups and clearly say so. Do not block on a missing preference that can be reported as an assumption.

## Collect messages

Prefer JSONL because it preserves timestamps, IDs, reply links, senders, and media metadata. Read Markdown only to recover human-readable context or when JSONL is absent.

Resolve bundled paths relative to this skill directory. Run the collector for deterministic date and group filtering:

```bash
python3 scripts/collect_messages.py /path/to/logs \
  --start 2026-07-13 --end 2026-07-19 \
  --group "Operations"
```

`--start` and `--end` are inclusive when passed as dates. Use `--month YYYY-MM` for a calendar month. The collector emits chronologically sorted JSONL with `_source_file` and `_source_line` evidence fields. Run `python3 scripts/collect_messages.py --help` for all options.

Read [references/log-format.md](references/log-format.md) when the archive layout, fields, media, reply chains, or collector behavior matters.

For large ranges, first inspect message counts and representative matches, then load the relevant conversations around candidate items. Reconstruct reply context with `reply_to`; do not interpret an isolated reply without its parent when that changes meaning.

## Analyze the evidence

### Identify urgent and important matters

Mark an item **urgent** only when messages provide a credible time-critical signal such as an explicit urgent label, a near deadline, a live outage or blocker, a safety issue, or a request requiring immediate action. Record the reason and deadline. Do not infer urgency from repetition, emotion, or message volume alone.

Mark an item **important** when it records a consequential decision, commitment, dependency, deadline, risk, escalation, customer or operational impact, or a change that affects future work. Deduplicate repeated discussion into one item while retaining the strongest evidence.

### Track work and status

Represent each task with action, owner, due date, status, relevant group, and evidence. Apply these rules:

- Mark **completed** only after an explicit completion statement, delivery, acceptance, or clearly documented outcome.
- Mark **outstanding** when work is assigned or committed and no later in-scope evidence closes it, or when a blocker or follow-up remains open.
- Mark **in progress** only when progress is explicitly reported.
- Mark **unclear** when ownership, due date, acceptance, or the latest state is ambiguous or conflicting.
- Treat a later reopening, rejection, regression, or new dependency as overriding an earlier completion.
- Never treat silence, a reaction, or vague acknowledgment such as “OK” as completion unless the surrounding conversation makes acceptance unambiguous.
- Distinguish a suggestion or question from an assigned or accepted action.

When a task predates the report period, include it only if it has activity in the period or the user asks for an as-of backlog snapshot. Do not claim that the chat contains the organization's complete backlog.

### Compute period statistics

Report only useful, reproducible measures. Typical measures include total messages, active participants, active days, messages by group, message/media types, number of urgent or important items, tasks completed, tasks still open, and dominant topics. Explain that counts describe recorded messages only. Avoid ranking individual productivity from message counts.

## Write the report

Adapt detail to the request, but default to:

1. Scope and executive summary
2. Urgent matters
3. Important decisions, deadlines, and risks
4. Completed work
5. Outstanding or in-progress work
6. Period statistics and major topics
7. Uncertainties, missing context, or data-quality notes

Attach compact evidence to every material claim using:

```text
[Group name | 2026-07-15 14:30 +08:00 | MSG001 | Sender]
```

Include short paraphrases by default; quote only when exact wording is essential. Avoid exposing full sender JIDs or attachment contents unless the user requests them. Separate facts from inference with labels such as `Explicit`, `Inferred`, and `Unclear`. If no qualifying item exists, say “No explicit evidence found” rather than inventing one.

End with a small action table for operational reports:

| Status | Action | Owner | Due | Evidence |
|---|---|---|---|---|

Use `Unassigned`, `No date stated`, or `Unclear` instead of filling gaps with assumptions.
