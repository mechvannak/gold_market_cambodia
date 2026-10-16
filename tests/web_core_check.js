// Runs the pure logic that lives in index.html (between // <core> and // </core>) under Node,
// so tests/test_web.py can compare it with scripts/decide.py and scripts/vault.py.
// usage: node tests/web_core_check.js < request.json   (request: {"op": "decide"|"decrypt", ...})
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const m = html.match(/\/\/ <core>([\s\S]*?)\/\/ <\/core>/);
if (!m) { console.error('core block not found in index.html'); process.exit(2); }
const core = new Function(m[1] + '\nreturn { holdings, decide, decryptVault, ozToChi };')();

let raw = '';
process.stdin.on('data', (d) => (raw += d));
process.stdin.on('end', async () => {
  const req = JSON.parse(raw);
  try {
    if (req.op === 'decide') {
      const out = req.cases.map((c) => {
        const hold = core.holdings(c.purchases);
        const ref = c.ref_chi == null ? core.ozToChi(c.market.price_oz) : c.ref_chi;
        return { hold, decision: core.decide(c.market, hold, ref, c.monthly) };
      });
      console.log(JSON.stringify(out));
    } else if (req.op === 'decrypt') {
      console.log(JSON.stringify({ ok: true, data: await core.decryptVault(req.pass, req.text) }));
    } else {
      throw new Error('unknown op');
    }
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: String(e && e.name), message: String(e && e.message) }));
  }
});
