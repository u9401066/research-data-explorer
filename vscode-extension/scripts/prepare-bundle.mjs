import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const extDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(extDir, '..');

const sourceRoot = path.join(repoRoot, 'src', 'rde');
const repoPyproject = path.join(repoRoot, 'pyproject.toml');
const bundledToolRoot = path.join(extDir, 'bundled', 'tool');
const bundledSrcRoot = path.join(bundledToolRoot, 'src');
const bundledRdeRoot = path.join(bundledSrcRoot, 'rde');

if (!fs.existsSync(sourceRoot)) {
    throw new Error(`RDE source not found: ${sourceRoot}`);
}

if (!fs.existsSync(repoPyproject)) {
    throw new Error(`pyproject.toml not found: ${repoPyproject}`);
}

fs.mkdirSync(bundledSrcRoot, { recursive: true });
fs.rmSync(bundledRdeRoot, { recursive: true, force: true });

fs.cpSync(sourceRoot, bundledRdeRoot, {
    recursive: true,
    filter: (entry) => !entry.includes('__pycache__') && !entry.endsWith('.pyc') && !entry.endsWith('.pyo'),
});

fs.copyFileSync(repoPyproject, path.join(bundledToolRoot, 'pyproject.toml'));

console.log(`[bundle] Prepared bundled Python project at ${bundledToolRoot}`);