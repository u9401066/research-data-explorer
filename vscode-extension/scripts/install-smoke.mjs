import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const extDir = path.resolve(scriptDir, '..');
const bundledToolRoot = path.join(extDir, 'bundled', 'tool');

function assertFile(relativePath) {
    const fullPath = path.join(bundledToolRoot, relativePath);
    if (!fs.existsSync(fullPath)) {
        throw new Error(`Missing bundled tool file: ${relativePath}`);
    }
}

function assertAbsent(relativePath) {
    const fullPath = path.join(bundledToolRoot, relativePath);
    if (fs.existsSync(fullPath)) {
        throw new Error(`Bundled tool must not include ${relativePath}`);
    }
}

assertFile('pyproject.toml');
assertFile(path.join('src', 'rde', '__main__.py'));
assertFile(path.join('src', 'rde', 'interface', 'mcp', 'server.py'));

assertAbsent('.venv');
assertAbsent('venv');
assertAbsent(path.join('src', 'rde', '__pycache__'));

console.log('[smoke] Bundled RDE tool project is installable-shaped.');
