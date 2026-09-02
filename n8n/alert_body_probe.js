// Contract test for the Steering Cell's Telegram alert body.
//
// It runs the real Code node out of quality_steering_cell_v1.json against every
// alerting event in every batch, and checks the message it produces is something
// Telegram will accept. It is JavaScript and not Python, unlike the other two
// probes, for one reason: a Python reimplementation of the escaping would be a
// test of the imitation rather than of the node, and this defect was found in a
// branch that had only ever been exercised with data that happened to be safe.
//
// What it exists for. The alert body used to be a Markdown template with six raw
// event values interpolated into it. Legacy Telegram Markdown reads an underscore
// as an italic marker, so the single underscore in a record id like
// NEU-INCLUSION_244 produced "Bad Request: can't parse entities" - and by then the
// incident had been written, its id consumed and its dedup key stored, while the
// caller got HTTP 200 with an empty body. An alert that is lost and reported as
// delivered is the worst failure this system can have, so the property is tested
// over every event the repository can publish rather than over a sample.
//
// Usage, from the repository root:
//     node n8n/alert_body_probe.js

const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const flow = JSON.parse(fs.readFileSync(path.join(REPO, 'n8n/quality_steering_cell_v1.json'), 'utf8'));
const jsCode = flow.nodes.find((n) => n.name === 'Validate + Dedup + Incident').parameters.jsCode;

// The Code node is evaluated with two globals it does not declare. A fresh static
// store per call keeps incident ids deterministic and stops the dedup cache
// suppressing the next event.
const run = (event) => {
  const store = { seen: {}, counter: 0 };
  return new Function('$json', '$getWorkflowStaticData', jsCode)({ body: event }, () => store);
};

// Telegram HTML accepts a small tag set. Strip the ones this message uses and
// nothing that looks like markup may be left, and every ampersand must be an
// entity. That is the property the escaping exists to guarantee.
const ALLOWED = /<\/?(?:b|code)>/g;
const ENTITY = /&(?:amp|lt|gt);/g;

function invalidBecause(text) {
  const stripped = text.replace(ALLOWED, '');
  if (stripped.includes('<') || stripped.includes('>')) return 'leftover angle bracket';
  if (stripped.replace(ENTITY, '').includes('&')) return 'bare ampersand';
  const pairs = [['<b>', '</b>'], ['<code>', '</code>']];
  for (const [open, close] of pairs) {
    const o = (text.match(new RegExp(open, 'g')) || []).length;
    const c = (text.match(new RegExp(close, 'g')) || []).length;
    if (o !== c) return `unbalanced ${open}: ${o} open, ${c} close`;
  }
  return null;
}

let failures = 0;
let rendered = 0;

// 1. Every alerting event the repository can publish.
console.log('Every alerting event, through the real node:');
for (const name of fs.readdirSync(path.join(REPO, 'events/out')).filter((f) => f.endsWith('.jsonl'))) {
  const events = fs.readFileSync(path.join(REPO, 'events/out', name), 'utf8')
    .split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l))
    .filter((e) => e.priority === 'P1' || e.priority === 'P2');
  let bad = 0;
  for (const event of events) {
    let out;
    try {
      out = run(event);
    } catch (err) {
      bad += 1;
      if (bad === 1) console.log(`  ${name} threw on ${event.event_id}: ${err.message}`);
      continue;
    }
    if (!out.json.alert) continue;
    rendered += 1;
    const text = out.json.alert_text;
    if (typeof text !== 'string' || !text.length) {
      bad += 1;
      if (bad === 1) console.log(`  ${name}: ${event.event_id} produced no alert_text`);
      continue;
    }
    const problem = invalidBecause(text);
    if (problem) {
      bad += 1;
      if (bad === 1) console.log(`  ${name}: ${event.event_id} -> ${problem}`);
    }
  }
  failures += bad;
  console.log(`  ${name.padEnd(34)} ${String(events.length).padStart(4)} alerting, ${bad} invalid`);
}

// 2. The check itself, on cases whose answer is known. A checker that has never
//    fired has proved nothing about the documents it passed.
console.log('');
console.log('The check, on cases whose answer is known:');
const base = JSON.parse(
  fs.readFileSync(path.join(REPO, 'events/out/neu_events.jsonl'), 'utf8')
    .split('\n').filter((l) => l.trim()).find((l) => JSON.parse(l).priority === 'P2')
);
const cases = [
  { name: 'real node output, untouched', build: () => run(base).json.alert_text, expect: 'valid' },
  { name: 'summary carrying markup, escaped by the node',
    build: () => run({ ...base, summary: 'Strip <b>bad</b> & worse' }).json.alert_text, expect: 'valid' },
  { name: 'body that skipped escaping', build: () => '<b>P2</b> x\n\n<script>alert(1)</script>', expect: 'invalid' },
  { name: 'body with a bare ampersand', build: () => '<b>P2</b> x\n\nTools & dies', expect: 'invalid' },
  { name: 'body with an unbalanced tag', build: () => '<b>P2 x<b>y</b>\n\nfine', expect: 'invalid' },
];
for (const c of cases) {
  const problem = invalidBecause(c.build());
  const got = problem ? 'invalid' : 'valid';
  const ok = got === c.expect;
  if (!ok) failures += 1;
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${c.name.padEnd(44)} ${got}${problem ? ' (' + problem + ')' : ''}`);
}

console.log('');
console.log(`${rendered} alert bodies rendered, ${failures} problem(s)`);
process.exit(failures === 0 ? 0 : 1);
