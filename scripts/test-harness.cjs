// Contract tests for the task transport/projection/client.
//   node scripts/test-harness.cjs [test file ...]
// The renderer modules are TypeScript; tsc compiles them to CommonJS in a cache
// folder so Node's test runner can require them without a bundler.
//
// Node's `--test <directory>` does not discover files on Windows: it treats the
// directory as a module and fails with MODULE_NOT_FOUND. The runner therefore
// passes explicit `.test.cjs` paths.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const tsc = path.join(root, 'node_modules', 'typescript', 'bin', 'tsc');

function findTests(directory) {
  const found = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) found.push(...findTests(full));
    else if (entry.isFile() && entry.name.endsWith('.test.cjs')) found.push(full);
  }
  return found.sort();
}

const build = spawnSync(process.execPath, [tsc, '-p', 'tsconfig.harness.json'], {
  cwd: root,
  stdio: 'inherit',
});
if (build.status !== 0) process.exit(build.status ?? 1);

const requested = process.argv.slice(2);
const targets = requested.length > 0 ? requested : findTests(path.join(root, 'tests', 'harness'));
if (targets.length === 0) {
  console.error('No harness tests found.');
  process.exit(1);
}

const test = spawnSync(process.execPath, ['--test', ...targets], {
  cwd: root,
  stdio: 'inherit',
});
process.exit(test.status ?? 1);
