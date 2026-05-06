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

function shouldInclude(entryPath) {
    return !entryPath.includes('__pycache__') && !entryPath.endsWith('.pyc') && !entryPath.endsWith('.pyo');
}

function copyDirRecursive(sourceDir, targetDir) {
    fs.mkdirSync(targetDir, { recursive: true });

    for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
        const sourceEntry = path.join(sourceDir, entry.name);
        const targetEntry = path.join(targetDir, entry.name);

        if (!shouldInclude(sourceEntry)) {
            continue;
        }

        if (entry.isDirectory()) {
            copyDirRecursive(sourceEntry, targetEntry);
            continue;
        }

        if (entry.isFile()) {
            fs.copyFileSync(sourceEntry, targetEntry);
        }
    }
}

if (!fs.existsSync(sourceRoot)) {
    throw new Error(`RDE source not found: ${sourceRoot}`);
}

if (!fs.existsSync(repoPyproject)) {
    throw new Error(`pyproject.toml not found: ${repoPyproject}`);
}

fs.rmSync(bundledToolRoot, { recursive: true, force: true });
fs.mkdirSync(bundledSrcRoot, { recursive: true });

if (typeof fs.cpSync === 'function') {
    fs.cpSync(sourceRoot, bundledRdeRoot, {
        recursive: true,
        filter: shouldInclude,
    });
} else {
    copyDirRecursive(sourceRoot, bundledRdeRoot);
}

fs.copyFileSync(repoPyproject, path.join(bundledToolRoot, 'pyproject.toml'));

console.log(`[bundle] Prepared bundled Python project at ${bundledToolRoot}`);
