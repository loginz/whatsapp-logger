import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { applyGroupSelection, createState, isGroupRecorded, parseArgs, processMessage } from '../logger.js';

function state() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'wa-logger-'));
  const s = createState({ dataDir: path.join(root, 'data'), logDir: path.join(root, 'logs') });
  mkdirSync(s.dataDir, { recursive: true });
  return s;
}

test('accepts both legacy and current recorded_groups formats', () => {
  assert.equal(isGroupRecorded('a@g.us', { recorded_groups: ['a@g.us'] }), true);
  assert.equal(isGroupRecorded('b@g.us', { recorded_groups: [{ id: 'b@g.us', name: 'B' }] }), true);
  assert.equal(isGroupRecorded('x@g.us', { record_all: true }), true);
});

test('writes compatible Markdown, JSONL, media, and group index', async () => {
  const s = state();
  writeFileSync(s.configPath, JSON.stringify({ recorded_groups: [{ id: 'g@g.us', name: 'Group' }] }));
  const source = path.join(s.dataDir, 'photo.jpg'); writeFileSync(source, 'image');
  await processMessage(s, { isGroup: true, chatId: 'g@g.us', chatName: 'Group', senderId: '65@s.whatsapp.net', senderName: 'Alice', messageId: 'M1', body: 'hello', timestamp: 1784452201, hasMedia: true, mediaType: 'image', mediaUrls: [source] });
  const group = path.join(s.logDir, 'groups', 'g@g.us');
  const md = readFileSync(path.join(group, '2026-07.md'), 'utf8');
  assert.match(md, /# Group `\(g@g\.us\)` — 2026-07/);
  assert.match(md, /\[M1\] hello/);
  const record = JSON.parse(readFileSync(path.join(group, '2026-07.jsonl'), 'utf8'));
  assert.equal(record.gid, 'g@g.us'); assert.deepEqual(record.media, ['attachments/2026-07-19/photo_001.jpg']);
  assert.match(readFileSync(s.indexPath, 'utf8'), /g@g\.us/);
});

test('parses existing command-line shape', () => {
  assert.deepEqual(parseArgs(['--port', '3002', 'config', 'group', '--add', 'Family']).options, { port: '3002', add: 'Family' });
});

test('interactive group selection only exits on done or quit', () => {
  const groups = [{ id: 'a@g.us' }, { id: 'b@g.us' }];
  const ids = new Set();
  assert.deepEqual(applyGroupSelection('1', groups, ids), { done: false, cancelled: false });
  assert.deepEqual([...ids], ['a@g.us']);
  assert.deepEqual(applyGroupSelection('2', groups, ids), { done: false, cancelled: false });
  assert.deepEqual([...ids], ['a@g.us', 'b@g.us']);
  assert.deepEqual(applyGroupSelection('done', groups, ids), { done: true, cancelled: false });
  assert.deepEqual(applyGroupSelection('q', groups, ids), { done: true, cancelled: true });
});
