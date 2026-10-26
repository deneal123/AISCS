// Identity-checked correction in the disposable source copy only.
const fs = require('node:fs');
const crypto = require('node:crypto');
const file = 'js/sim-worker.js';
const original = fs.readFileSync(file);
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
if (sha(original) !== 'b99a6932e549968b63449aab4630a9462c5d6606355cd56021f13a5445637b51') throw new Error('Unreviewed worker source');
const text = original.toString('utf8');
const newline = text.includes('\r\n') ? '\r\n' : '\n';
const marker = "case 'reset':" + newline + "\t\tif (N === 0) break;";
if (text.split(marker).length !== 2) throw new Error('Ambiguous reset patch');
const changed = text.replace(marker, marker + newline + '\t\ttickCount = 0;');
fs.writeFileSync(file, changed);
fs.writeFileSync('/work/worker-correction.json', JSON.stringify({scope:'working copy only; restores model clock on explicit reset', file, before_sha256:sha(original), after_sha256:sha(changed), change:'one added assignment tickCount = 0 in reset handler'}, null, 2)+'\n');
