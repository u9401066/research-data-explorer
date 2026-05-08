import fs from 'fs';
import os from 'os';
import path from 'path';

import { afterEach, describe, expect, it } from 'vitest';

import {
    buildCodexRdeMcpBlock,
    buildDevPythonPath,
    configureCodexRdeMcpConfigFile,
    countMissingBundledItems,
    codexConfigPath,
    determinePythonPath,
    isBundledToolProject,
    isDevWorkspace,
    shouldSkipMcpRegistration,
    upsertCodexRdeMcpConfig,
} from '../src/extensionHelpers';

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

    it('detects user-managed RDE MCP registrations without requiring package-name text', () => {
        const mcpJson = JSON.stringify({
            servers: {
                rde: {
                    command: 'uv',
                    args: ['run', 'python', '-m', 'rde'],
                },
            },
        });

        expect(shouldSkipMcpRegistration(mcpJson)).toBe(true);
    });

    it('detects README-style research-data-explorer MCP registrations', () => {
        const mcpJson = JSON.stringify({
            servers: {
                'research-data-explorer': {
                    command: 'uvx',
                    args: ['research-data-explorer'],
                },
            },
        });

        expect(shouldSkipMcpRegistration(mcpJson)).toBe(true);
    });

    it('counts Copilot, Codex, and Cline scaffold targets', () => {
        const wsRoot = makeTempDir();
        const extPath = makeTempDir();

        fs.mkdirSync(path.join(extPath, 'skills', 'eda-workflow'), { recursive: true });
        fs.writeFileSync(path.join(extPath, 'skills', 'eda-workflow', 'SKILL.md'), '# skill\n');
        fs.mkdirSync(path.join(extPath, 'prompts'), { recursive: true });
        fs.writeFileSync(path.join(extPath, 'prompts', 'rde-13-phase.prompt.md'), '# prompt\n');
        fs.mkdirSync(path.join(extPath, 'agents'), { recursive: true });
        fs.writeFileSync(path.join(extPath, 'agents', 'eda.agent.md'), '# agent\n');
        fs.mkdirSync(path.join(extPath, 'clinerules'), { recursive: true });
        fs.writeFileSync(path.join(extPath, 'clinerules', '00-rde.md'), '# rule\n');
        fs.writeFileSync(path.join(extPath, 'AGENTS.md'), '# agents\n');

        const missing = countMissingBundledItems(
            wsRoot,
            extPath,
            ['eda-workflow'],
            ['eda'],
            ['rde-13-phase'],
            ['eda-workflow'],
            ['00-rde.md'],
            true,
        );

        expect(missing.total).toBe(6);
        expect(missing.missingCodexSkills).toBe(1);
        expect(missing.missingClineRules).toBe(1);
        expect(missing.missingCodexInstructions).toBe(1);
    });

    it('builds a Codex MCP block for a local RDE project with UTF-8 env', () => {
        const root = makeTempDir();
        const workspace = path.join(root, 'workspace');
        const project = path.join(root, 'bundled', 'tool');

        const block = buildCodexRdeMcpBlock({
            command: 'uv',
            projectPath: project,
            workspacePath: workspace,
        });

        expect(block).toContain('[mcp_servers.research-data-explorer]');
        expect(block).toContain('"run", "--directory"');
        expect(block).toContain(JSON.stringify(path.resolve(project)));
        expect(block).toContain(`RDE_WORKSPACE = ${JSON.stringify(path.resolve(workspace))}`);
        expect(block).toContain('PYTHONUTF8 = "1"');
        expect(block).toContain('PYTHONIOENCODING = "utf-8"');
    });

    it('upserts Codex MCP config without duplicating the managed RDE block', () => {
        const root = makeTempDir();
        const existing = [
            '[mcp_servers.other]',
            'command = "node"',
            '',
            '[mcp_servers.research-data-explorer]',
            'command = "old"',
            '',
            '[mcp_servers.research-data-explorer.env]',
            'RDE_WORKSPACE = "old"',
            '',
        ].join('\n');

        const once = upsertCodexRdeMcpConfig(existing, {
            projectPath: path.join(root, 'tool'),
            workspacePath: path.join(root, 'workspace'),
        });
        const twice = upsertCodexRdeMcpConfig(once, {
            projectPath: path.join(root, 'tool'),
            workspacePath: path.join(root, 'workspace'),
        });

        expect(twice).toBe(once);
        expect(twice).toContain('[mcp_servers.other]');
        expect((twice.match(/\[mcp_servers\.research-data-explorer\]/g) || [])).toHaveLength(1);
        expect((twice.match(/\[mcp_servers\.research-data-explorer\.env\]/g) || [])).toHaveLength(1);
        expect(twice).not.toContain('command = "old"');
    });

    it('writes the Codex config file idempotently', () => {
        const home = makeTempDir();
        const config = codexConfigPath(home);
        const first = configureCodexRdeMcpConfigFile(config, {
            projectPath: path.join(home, 'tool'),
            workspacePath: path.join(home, 'workspace'),
        });
        const second = configureCodexRdeMcpConfigFile(config, {
            projectPath: path.join(home, 'tool'),
            workspacePath: path.join(home, 'workspace'),
        });

        expect(first.changed).toBe(true);
        expect(second.changed).toBe(false);
        expect(fs.readFileSync(config, 'utf-8')).toContain('[mcp_servers.research-data-explorer]');
    });
});
