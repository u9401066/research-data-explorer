import fs from 'fs';
import os from 'os';
import path from 'path';

import { afterEach, describe, expect, it } from 'vitest';

import { buildDevPythonPath, determinePythonPath, isBundledToolProject, isDevWorkspace } from '../src/extensionHelpers';

const tempDirs: string[] = [];

function makeTempDir(): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rde-ext-'));
    tempDirs.push(dir);
    return dir;
}

afterEach(() => {
    while (tempDirs.length > 0) {
        const dir = tempDirs.pop();
        if (dir) {
            fs.rmSync(dir, { recursive: true, force: true });
        }
    }
});

describe('extensionHelpers', () => {
    it('detects repo development workspaces from src/rde', () => {
        const root = makeTempDir();
        fs.mkdirSync(path.join(root, 'src', 'rde'), { recursive: true });

        expect(isDevWorkspace(root)).toBe(true);
    });

    it('detects bundled tool projects from pyproject and src/rde entrypoint', () => {
        const root = makeTempDir();
        const toolRoot = path.join(root, 'bundled', 'tool');
        fs.mkdirSync(path.join(toolRoot, 'src', 'rde'), { recursive: true });
        fs.writeFileSync(path.join(toolRoot, 'pyproject.toml'), '[project]\nname = "research-data-explorer"\n');
        fs.writeFileSync(path.join(toolRoot, 'src', 'rde', '__main__.py'), 'print("ok")\n');

        expect(isBundledToolProject(toolRoot)).toBe(true);
    });

    it('adds bundled src to PYTHONPATH when a packaged tool project exists', () => {
        const root = makeTempDir();
        const bundledToolRoot = path.join(root, 'bundled', 'tool');
        fs.mkdirSync(path.join(root, 'src'), { recursive: true });
        fs.mkdirSync(path.join(bundledToolRoot, 'src', 'rde'), { recursive: true });

        const pythonPath = buildDevPythonPath(root, bundledToolRoot);
        const parts = pythonPath.split(path.delimiter);

        expect(parts).toContain(path.join(root, 'src'));
        expect(parts).toContain(path.join(bundledToolRoot, 'src'));
    });

    it('prefers uv for repo workspaces over arbitrary configured Python paths', () => {
        const root = makeTempDir();
        const externalPython = path.join(root, 'python.exe');
        fs.mkdirSync(path.join(root, 'src', 'rde'), { recursive: true });
        fs.writeFileSync(path.join(root, 'pyproject.toml'), '[project]\nname = "research-data-explorer"\n');
        fs.writeFileSync(externalPython, '');

        expect(determinePythonPath({
            configuredPath: externalPython,
            wsRoot: root,
            extensionPath: root,
        })).toBe('uv');
    });

    it('allows a uv-managed workspace virtualenv Python in repo workspaces', () => {
        const root = makeTempDir();
        const workspacePython = process.platform === 'win32'
            ? path.join(root, '.venv', 'Scripts', 'python.exe')
            : path.join(root, '.venv', 'bin', 'python');

        fs.mkdirSync(path.dirname(workspacePython), { recursive: true });
        fs.mkdirSync(path.join(root, 'src', 'rde'), { recursive: true });
        fs.writeFileSync(path.join(root, 'pyproject.toml'), '[project]\nname = "research-data-explorer"\n');
        fs.writeFileSync(workspacePython, '');

        expect(determinePythonPath({
            configuredPath: workspacePython,
            wsRoot: root,
            extensionPath: root,
        })).toBe(workspacePython);
    });
});
