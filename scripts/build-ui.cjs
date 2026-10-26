const { spawnSync } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const result = spawnSync(process.execPath, [path.join(root, 'node_modules/next/dist/bin/next'), 'build'], {
  cwd: root, stdio: 'inherit', env: { ...process.env, DESKTOP_EXPORT: '1' },
});
process.exit(result.status ?? 1);
