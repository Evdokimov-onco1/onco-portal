// Parse every script shipped by the browser entry point before UI-specific tests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, 'web');
const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*src="\/([^"?]+)"/g)].map(m => m[1]);
assert.ok(scripts.length > 0, 'entry point must contain scripts');
for (const filename of scripts) {
  new vm.Script(fs.readFileSync(path.join(web, filename), 'utf8'), { filename });
}
console.log(`Browser syntax: ${scripts.length} entry scripts parsed successfully`);
