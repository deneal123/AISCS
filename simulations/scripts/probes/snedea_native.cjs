// Upstream prints failures but does not set a failing exit code.
const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const result = spawnSync(process.execPath, ['tests/run-node.js'], {encoding:'utf8'});
process.stdout.write(result.stdout || '');
process.stderr.write(result.stderr || '');
const match = /([0-9]+) passed \/ ([0-9]+) failed \/ ([0-9]+) total/.exec(result.stdout || '');
if (result.status !== 0 || !match || Number(match[2]) !== 0 || Number(match[1]) !== 99 || Number(match[3]) !== 99) throw new Error('Native test summary did not establish all 99 passing tests');
fs.writeFileSync('/work/native-test-summary.json',JSON.stringify({status:'passed',passed:99,failed:0,total:99,scope:'native behavioral/group/renderer software tests; not biological validation'},null,2)+'\n');
