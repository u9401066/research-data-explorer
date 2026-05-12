import fs from 'fs';
import os from 'os';
import path from 'path';

import { afterEach, describe, expect, it } from 'vitest';

import {
    buildMcpEnv,
    findInstalledTool,
    getPathDirectories,
    getUvxPath,
} from '../src/uvManager';

const originalEnv: NodeJS.ProcessEnv = { ...process.env };
const tempDirs: string[] = [];

function makeTempDir(): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rde-uv-'));
    tempDirs.push(dir);
    return dir;
}

afterEach(() => {
    process.env = { ...originalEnv };
    while (tempDirs.length > 0) {
        const dir = tempDirs.pop();
        if (dir) {
            fs.rmSync(dir, { recursive: true, force: true });
        }
    }
});

describe('uvManager', () => {
    it('derives uvx next to uv with platform-specific executable suffixes', () => {
        const uvPath = process.platform === 'win32'
            ? path.join('C:\\Users\\tester\\.local\\bin', 'uv.exe')
            : path.join('/Users/tester/.local/bin', 'uv');

        const uvxPath = getUvxPath(uvPath);

        expect(path.dirname(uvxPath)).toBe(path.dirname(uvPath));
        expect(path.basename(uvxPath)).toBe(process.platform === 'win32' ? 'uvx.exe' : 'uvx');
    });

    it('deduplicates PATH directories after enrichment', () => {
        const first = makeTempDir();
        const second = makeTempDir();
        const dirs = getPathDirectories([first, second, first].join(path.delimiter));

        expect(dirs.indexOf(first)).toBe(dirs.lastIndexOf(first));
        expect(dirs).toContain(second);
    });

    it('builds MCP env with UTF-8 settings plus inherited platform runtime variables', () => {
        const pathValue = [makeTempDir(), makeTempDir()].join(path.delimiter);
        process.env.PATH = pathValue;
        process.env.HOME = path.join(os.tmpdir(), 'home-rde');
        process.env.USERPROFILE = path.join(os.tmpdir(), 'profile-rde');
        process.env.LOCALAPPDATA = path.join(os.tmpdir(), 'localappdata-rde');
        process.env.TEMP = os.tmpdir();

        const env = buildMcpEnv({
            workspaceDir: path.join(os.tmpdir(), 'workspace-rde'),
            pythonPath: path.join(os.tmpdir(), 'workspace-rde', 'src'),
        });

        expect(env.RDE_WORKSPACE).toContain('workspace-rde');
        expect(env.PYTHONPATH).toContain('src');
        expect(env.PYTHONUTF8).toBe('1');
        expect(env.PYTHONIOENCODING).toBe('utf-8');
        expect(env.PATH).toContain(pathValue.split(path.delimiter)[0]);
        expect(env.HOME).toBe(process.env.HOME);
        expect(env.USERPROFILE).toBe(process.env.USERPROFILE);
        expect(env.LOCALAPPDATA).toBe(process.env.LOCALAPPDATA);
        expect(env.TEMP).toBe(process.env.TEMP);
    });

    it('finds pre-installed tool binaries from the enriched PATH', () => {
        const binDir = makeTempDir();
        const toolName = process.platform === 'win32' ? 'research-data-explorer.exe' : 'research-data-explorer';
        const toolPath = path.join(binDir, toolName);
        fs.writeFileSync(toolPath, '');
        process.env.PATH = [binDir, originalEnv.PATH || ''].join(path.delimiter);

        expect(findInstalledTool('research-data-explorer')).toBe(toolPath);
    });
});
