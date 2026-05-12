const { spawnSync } = require('child_process');
const path = require('path');

const scriptDir = __dirname;
const extDir = path.resolve(scriptDir, '..');
const passthroughArgs = process.argv.slice(2);

const isWindows = process.platform === 'win32';
const command = isWindows ? 'powershell' : 'bash';
const args = isWindows
  ? [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      path.join(scriptDir, 'validate-build.ps1'),
      ...passthroughArgs,
    ]
  : [
      path.join(scriptDir, 'validate-build.sh'),
      ...passthroughArgs,
    ];

const result = spawnSync(command, args, {
  cwd: extDir,
  stdio: 'inherit',
  shell: false,
});

if (result.error) {
  console.error(`[validate] Failed to launch ${command}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
