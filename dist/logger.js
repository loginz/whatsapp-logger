#!/usr/bin/env node
/**
 * WhatsApp Group Chat Logger (v4)
 *
 * Node.js replacement for logger.py.  The Baileys bridge remains a separate
 * process and keeps its existing loopback HTTP API.
 */
import { spawn, spawnSync } from 'node:child_process';
import { appendFileSync, copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';

const APP_DIR = path.dirname(fileURLToPath(import.meta.url));
const BRIDGE_DIR = path.join(APP_DIR, 'bridge');
const BRIDGE_SCRIPT = path.join(BRIDGE_DIR, 'bridge.js');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function createState(overrides = {}) {
  const dataDir = path.resolve(overrides.dataDir || process.env.WHATSAPP_LOGGER_DATA_DIR || APP_DIR);
  const logDir = path.resolve(overrides.logDir || process.env.WHATSAPP_LOGGER_LOG_DIR || path.join(APP_DIR, 'logs'));
  return {
    port: Number(overrides.port || process.env.WHATSAPP_LOGGER_PORT || 3001), dataDir, logDir,
    sessionDir: path.join(dataDir, 'session'), cacheDir: path.join(dataDir, 'cache'),
    configPath: path.join(dataDir, 'config.json'), indexPath: path.join(logDir, 'groups_index.md'),
    configCache: { mtimeMs: -1, data: {} }, index: new Map(), lastIndexFlush: 0, lastGroupsRefresh: 0,
  };
}

function log(message) { console.log(`[${new Date().toTimeString().slice(0, 8)}] ${message}`); }
function ensureDirs(s) { for (const d of [s.logDir, s.sessionDir, ...['images', 'documents', 'audio', 'video'].map((x) => path.join(s.cacheDir, x))]) mkdirSync(d, { recursive: true }); }
function url(s, suffix = '') { return `http://127.0.0.1:${s.port}${suffix}`; }
async function getJson(s, suffix, timeout = 30000) {
  const response = await fetch(url(s, suffix), { signal: AbortSignal.timeout(timeout) });
  if (!response.ok) throw new Error(`${suffix}: HTTP ${response.status}`);
  return response.json();
}
async function getBytes(source) {
  const response = await fetch(source, { signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}
function bridgeEnv(s) { return { ...process.env, HERMES_IMAGE_CACHE_DIR: path.join(s.cacheDir, 'images'), HERMES_DOCUMENT_CACHE_DIR: path.join(s.cacheDir, 'documents'), HERMES_AUDIO_CACHE_DIR: path.join(s.cacheDir, 'audio'), HERMES_VIDEO_CACHE_DIR: path.join(s.cacheDir, 'video'), WHATSAPP_MODE: 'bot', WHATSAPP_LOGGER_CAPTURE_GROUPS: 'true', WHATSAPP_ALLOWED_USERS: process.env.WHATSAPP_ALLOWED_USERS || '*' }; }
function ensureBridgeDependencies() {
  if (existsSync(path.join(BRIDGE_DIR, 'node_modules'))) return;
  log('Installing bridge dependencies...');
  const result = spawnSync('npm', ['install'], { cwd: BRIDGE_DIR, stdio: 'inherit' });
  if (result.status !== 0) throw new Error('npm install failed');
}
function startBridge(s) {
  ensureBridgeDependencies();
  log(`Starting bridge on port ${s.port}...`);
  return spawn(process.execPath, [BRIDGE_SCRIPT, '--port', String(s.port), '--session', s.sessionDir], { cwd: BRIDGE_DIR, env: bridgeEnv(s), stdio: 'inherit' });
}
async function waitForBridge(s, child, connected = false, timeout = connected ? 300000 : 30000) {
  const deadline = Date.now() + timeout;
  let lastStatus;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) return false;
    try {
      const health = await getJson(s, '/health', 3000);
      if (health.status !== lastStatus) { log(`WhatsApp status: ${health.status}`); lastStatus = health.status; }
      if (!connected && ['connected', 'disconnected'].includes(health.status)) return true;
      if (connected && health.status === 'connected') return true;
    } catch { /* bridge is still starting */ }
    await sleep(connected ? 1000 : 500);
  }
  return false;
}
async function stopBridge(child) {
  if (!child || child.exitCode !== null) return;
  log('Stopping bridge...'); child.kill('SIGTERM');
  await Promise.race([new Promise((resolve) => child.once('exit', resolve)), sleep(10000)]);
  if (child.exitCode === null) child.kill('SIGKILL');
}

export function isGroupRecorded(chatId, config) { return !!config.record_all || (config.recorded_groups || []).some((entry) => (typeof entry === 'object' ? entry.id : String(entry)) === chatId); }
function loadConfig(s, force = false) {
  try {
    const mtimeMs = statSync(s.configPath).mtimeMs;
    if (force || mtimeMs > s.configCache.mtimeMs) { s.configCache = { mtimeMs, data: JSON.parse(readFileSync(s.configPath, 'utf8')) }; log(`Config reloaded (${(s.configCache.data.recorded_groups || []).length} groups)`); }
  } catch (error) { if (error.code !== 'ENOENT') log(`WARN: failed to load config: ${error.message}`); }
  return s.configCache.data;
}
function saveConfig(s, config) { mkdirSync(path.dirname(s.configPath), { recursive: true }); writeFileSync(s.configPath, `${JSON.stringify(config, null, 2)}\n`); s.configCache.mtimeMs = -1; }
function localDate(ts) { return ts ? new Date(Number(ts) * 1000) : new Date(); }
function timestampParts(ts) { const d = localDate(ts); const pad = (v) => String(v).padStart(2, '0'); const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; const time = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; return { d, date, month: date.slice(0, 7), time, iso: `${date}T${time}${offset(d)}` }; }
function offset(d) { const n = -d.getTimezoneOffset(), sign = n >= 0 ? '+' : '-', a = Math.abs(n); return `${sign}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}`; }
function lastDate(mdPath) { if (!existsSync(mdPath)) return ''; const text = readFileSync(mdPath).subarray(Math.max(0, statSync(mdPath).size - 4096)).toString('utf8'); return [...text.matchAll(/^##\s+(\d{4}-\d{2}-\d{2})\s*$/gm)].at(-1)?.[1] || ''; }
function uniqueName(dir, prefix, ext) { for (let i = 1; ; i += 1) { const target = path.join(dir, `${prefix}_${String(i).padStart(3, '0')}${ext}`); if (!existsSync(target)) return target; } }
async function saveMedia(sources, type, mediaDir, groupDir) {
  const prefix = { image: 'photo', video: 'video', audio: 'audio', ptt: 'voice', document: 'doc', sticker: 'sticker' }[type] || 'media';
  const fallback = { image: '.jpg', video: '.mp4', audio: '.mp3', ptt: '.ogg', sticker: '.webp' }[type] || '.bin'; const saved = [];
  for (const source of sources) try {
    let ext = path.extname(new URL(source, 'file:///').pathname) || fallback; const target = uniqueName(mediaDir, prefix, ext);
    if (/^https?:\/\//.test(source)) writeFileSync(target, await getBytes(source)); else copyFileSync(source, target);
    saved.push(path.relative(groupDir, target));
  } catch (error) { log(`  WARN: failed to save media ${source}: ${error.message}`); }
  return saved;
}
function loadIndex(s) { s.index.clear(); if (!existsSync(s.indexPath)) return; for (const line of readFileSync(s.indexPath, 'utf8').split('\n')) { const m = line.match(/^\|\s*`([^`]+@g\.us)`\s*\|\s*(.*?)\s*\|\s*([^|]+?)\s*\|\s*\[([^\]]+)]\([^)]+\)\s*\|$/); if (m) s.index.set(m[1], { name: m[2].trim(), lastTs: m[3].trim(), monthFile: m[4].trim() }); } }
function flushIndex(s, force = false) { if (!force && Date.now() - s.lastIndexFlush < 60000) return; const rows = [...s.index.entries()].sort((a, b) => b[1].lastTs.localeCompare(a[1].lastTs)).map(([gid, x]) => `| \`${gid}\` | ${x.name} | ${x.lastTs} | [${x.monthFile}](groups/${gid}/${x.monthFile}) |`); writeFileSync(s.indexPath, `# Group Index\n\nLast updated: ${new Date().toLocaleString('sv-SE').replace('T', ' ')}\n\n| Group ID | Group name | Latest message | Monthly file |\n|-------|------|---------|---------|\n${rows.join('\n')}\n`); s.lastIndexFlush = Date.now(); }
async function refreshGroupNames(s) { if (Date.now() - s.lastGroupsRefresh < 86400000) return; s.lastGroupsRefresh = Date.now(); try { const { groups = [] } = await getJson(s, '/groups', 15000); let changed = false; for (const g of groups) { const old = s.index.get(g.id); if (old && g.name && old.name !== g.name) { old.name = g.name; changed = true; } } if (changed) flushIndex(s, true); } catch (error) { log(`WARN: /groups refresh failed (will retry next day): ${error.message}`); } }

export async function processMessage(s, data) {
  if (!data.isGroup || !isGroupRecorded(data.chatId || '', loadConfig(s))) return false;
  await refreshGroupNames(s); const chatId = data.chatId || ''; const chatName = data.chatName || chatId.split('@')[0] || 'unknown'; const senderId = data.senderId || ''; const senderName = data.senderName || senderId || 'unknown'; const body = data.body || ''; const p = timestampParts(data.timestamp); const groupDir = path.join(s.logDir, 'groups', chatId); mkdirSync(groupDir, { recursive: true });
  let media = []; if (data.hasMedia && data.mediaUrls?.length) { const mediaDir = path.join(groupDir, 'attachments', p.date); mkdirSync(mediaDir, { recursive: true }); media = await saveMedia(data.mediaUrls, data.mediaType || '', mediaDir, groupDir); }
  const md = path.join(groupDir, `${p.month}.md`); let content = ''; if (!existsSync(md)) content += `# ${chatName} \`(${chatId})\` — ${p.month}\n\n`; if (lastDate(md) !== p.date) content += `## ${p.date}\n\n`; const quote = data.hasQuotedMessage ? ` ↩@${(data.quotedParticipant || '').split('@')[0]}${data.quotedMessageId ? ` #${data.quotedMessageId}` : ''}` : ''; content += `**${senderName}** \`(${senderId})\` ${p.time}${quote}:\n${data.messageId ? `[${data.messageId}] ` : ''}${body}\n${media.map((x) => `![${data.mediaType}](${x})\n`).join('')}\n`; appendFileSync(md, content);
  const record = { ts: p.iso, gid: chatId, gname: chatName, sid: senderId, name: senderName, mid: data.messageId || '', type: data.mediaType || 'text', body }; if (data.hasQuotedMessage) { record.reply_to = data.quotedMessageId || ''; record.reply_to_sid = data.quotedParticipant || ''; } if (media.length) { record.media = media; record.media_type = data.mediaType || ''; } appendFileSync(path.join(groupDir, `${p.month}.jsonl`), `${JSON.stringify(record)}\n`);
  s.index.set(chatId, { name: chatName, lastTs: p.iso, monthFile: `${p.month}.md` }); flushIndex(s); log(`[${p.date} ${p.time}] ${chatName} / ${senderName}: ${body.slice(0, 60)}${body.length > 60 ? '...' : ''}`); return true;
}

async function run(s) { ensureDirs(s); loadIndex(s); let stopping = false; process.on('SIGTERM', () => { stopping = true; }); process.on('SIGINT', () => { stopping = true; }); while (!stopping) { let child; try { child = startBridge(s); if (!await waitForBridge(s, child)) throw new Error('Bridge failed to start'); const known = new Set(); while (!stopping && child.exitCode === null) { try { const messages = await getJson(s, '/messages'); for (const message of Array.isArray(messages) ? messages : []) { const id = message.id || message.key?.id; if (id && known.has(id)) continue; if (id) { known.add(id); if (known.size > 10000) { const keep = [...known].slice(-5000); known.clear(); keep.forEach((x) => known.add(x)); } } try { await processMessage(s, message); } catch (error) { log(`Error processing message: ${error.message}`); } } } catch (error) { log(`Poll error: ${error.message}`); await sleep(5000); } await sleep(1000); } } catch (error) { log(`${error.message}. Retrying in 10 seconds...`); await sleep(10000); } finally { await stopBridge(child); flushIndex(s, true); } } }
function backupSessionDir(s) { if (!existsSync(s.sessionDir) || !requireNonEmpty(s.sessionDir)) return; const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, '').replace('T', '-'); let target = path.join(s.dataDir, `session.backup-${stamp}`); for (let i = 1; existsSync(target); i += 1) target = path.join(s.dataDir, `session.backup-${stamp}-${i}`); renameSync(s.sessionDir, target); log(`Old session backed up: ${target}`); }
function requireNonEmpty(dir) { try { return readdirSync(dir).length > 0; } catch { return false; } }
async function configAccount(s) { ensureDirs(s); ensureBridgeDependencies(); backupSessionDir(s); mkdirSync(s.sessionDir, { recursive: true }); const child = startBridge(s); let paired = false; try { if (!await waitForBridge(s, child)) throw new Error('Bridge failed to start'); console.log('\nOpen WhatsApp: Settings -> Linked Devices -> Link a Device, then scan the QR code.\n'); paired = await waitForBridge(s, child, true); if (!paired) log('ERROR: Did not detect a successful pairing.'); } finally { await stopBridge(child); } if (!paired) return 1; log('✅ WhatsApp connected! Pairing complete.'); const reload = spawnSync('systemctl', ['--user', 'daemon-reload'], { stdio: 'pipe', encoding: 'utf8' }); const start = reload.status === 0 && spawnSync('systemctl', ['--user', 'start', 'whatsapp-logger'], { stdio: 'pipe', encoding: 'utf8' }); if (!start || start.status !== 0) { log('Service could not be started; run `node logger.js config group` after starting it.'); return 1; } await sleep(1000); return configGroup(s, {}); }
async function fetchGroups(s) { const data = await getJson(s, '/groups', 15000); return data.groups || []; }
function selectedIds(cfg) { return new Set((cfg.recorded_groups || []).map((x) => typeof x === 'object' ? x.id : String(x))); }
async function configGroup(s, options) { let groups; try { groups = await fetchGroups(s); } catch (error) { console.error(`❌ Failed to fetch groups: ${error.message}`); return 1; } const cfg = loadConfig(s, true); if (options.list) { const ids = selectedIds(cfg); console.log(`\nWhatsApp Groups (${groups.length} total)`); for (const [i, g] of groups.entries()) console.log(` ${ids.has(g.id) || cfg.record_all ? '✓' : ' '} ${String(i + 1).padStart(2)}. ${g.name} (${g.participantCount})`); return 0; } if (options.recordAll) { saveConfig(s, { ...cfg, record_all: true, recorded_groups: [] }); return 0; } if (options.init) { saveConfig(s, { recorded_groups: groups.map((g) => ({ id: g.id, name: g.name })), record_all: false }); return 0; } const match = (name) => groups.filter((g) => g.name.toLowerCase().includes(name.toLowerCase())); if (options.add || options.remove) { const found = match(options.add || options.remove); if (!found.length) { console.error(`❌ No group found matching '${options.add || options.remove}'`); return 1; } let entries = cfg.recorded_groups || []; const ids = selectedIds(cfg); for (const g of found) { if (options.add && !ids.has(g.id)) entries.push({ id: g.id, name: g.name }); if (options.remove) entries = entries.filter((x) => (typeof x === 'object' ? x.id : x) !== g.id); } saveConfig(s, { ...cfg, recorded_groups: entries, record_all: false }); return 0; } const rl = readline.createInterface({ input: process.stdin, output: process.stdout }); const ids = selectedIds(cfg); console.log(groups.map((g, i) => ` ${ids.has(g.id) ? '✓' : ' '} ${i + 1}. ${g.name} (${g.participantCount})`).join('\n')); const answer = await rl.question('Enter numbers to toggle, a/all, n/none, or done: '); rl.close(); if (answer === 'a') groups.forEach((g) => ids.add(g.id)); else if (answer === 'n') ids.clear(); else if (answer !== 'done') answer.split(/\s+/).forEach((n) => { const g = groups[Number(n) - 1]; if (g) ids.has(g.id) ? ids.delete(g.id) : ids.add(g.id); }); saveConfig(s, { recorded_groups: groups.filter((g) => ids.has(g.id)).map((g) => ({ id: g.id, name: g.name })), record_all: false }); return 0; }
export function parseArgs(argv) { const options = {}; const rest = []; for (let i = 0; i < argv.length; i += 1) { const a = argv[i]; if (a === '--help' || a === '-h') options.help = true; else if (['--port', '--log-dir', '--data-dir', '--add', '--remove'].includes(a)) options[{ '--port': 'port', '--log-dir': 'logDir', '--data-dir': 'dataDir', '--add': 'add', '--remove': 'remove' }[a]] = argv[++i]; else if (['--list', '--record-all', '--init'].includes(a)) options[{ '--list': 'list', '--record-all': 'recordAll', '--init': 'init' }[a]] = true; else rest.push(a); } return { options, command: rest[0] || 'run', subcommand: rest[1] }; }
async function main() { const { options, command, subcommand } = parseArgs(process.argv.slice(2)); if (options.help || command === '--help') { console.log('Usage: node logger.js [--port PORT] [--log-dir DIR] [--data-dir DIR] {run|config account|config group}'); return; } const s = createState(options); let status = 0; if (command === 'run') await run(s); else if (command === 'config' && subcommand === 'account') status = await configAccount(s); else if (command === 'config' && subcommand === 'group') status = await configGroup(s, options); else { console.error('Unknown command'); status = 1; } process.exitCode = status; }
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
