/**
 * uv Manager — Auto-detection and installation of uv (Python package manager).
 *
 * Zero-config experience:
 * 1. Detect uv in PATH or known install locations
 * 2. Auto-install uv if not found (cross-platform)
 * 3. Derive uvx path from uv path
 */

import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Extra directories that may contain uv on macOS/Linux/Windows
 * (GUI apps may not inherit shell PATH).
 */
function getExtraPathDirs(): string[] {
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';
    const dirs: string[] = [];

    if (process.platform === 'win32') {
        const localAppData = process.env.LOCALAPPDATA || path.join(homeDir, 'AppData', 'Local');
        dirs.push(
            path.join(localAppData, 'uv', 'bin'),
            path.join(homeDir, '.local', 'bin'),
            path.join(homeDir, '.cargo', 'bin'),
        );
    } else {
        dirs.push(
            path.join(homeDir, '.local', 'bin'),
            path.join(homeDir, '.cargo', 'bin'),
        );
    }

    if (process.platform === 'darwin') {
        dirs.push(
            '/opt/homebrew/bin',
            '/opt/homebrew/sbin',
            '/usr/local/bin',
            '/usr/local/sbin',
        );
    }

    if (process.platform === 'linux') {
        dirs.push(
            '/usr/local/bin',
            '/snap/bin',
        );
    }

    return dirs.filter(d => fs.existsSync(d));
}

/**
 * Enrich PATH with extra directories that may contain tools.
 */
export function enrichPath(basePath: string): string {
    const extraDirs = getExtraPathDirs();
    const existing = new Set(basePath.split(path.delimiter));
    const toAdd = extraDirs.filter(d => !existing.has(d));
    if (toAdd.length === 0) { return basePath; }
    return [...toAdd, basePath].join(path.delimiter);
}

/**
 * Get potential uv binary paths based on platform.
 */
export function getUvSearchPaths(): string[] {
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';

    if (process.platform === 'win32') {
        const localAppData = process.env.LOCALAPPDATA || path.join(homeDir, 'AppData', 'Local');
        return [
            'uv',
            path.join(localAppData, 'uv', 'bin', 'uv.exe'),
            path.join(homeDir, '.local', 'bin', 'uv.exe'),
            path.join(homeDir, '.cargo', 'bin', 'uv.exe'),
            'C:\\Program Files\\uv\\uv.exe',
        ];
    } else if (process.platform === 'darwin') {
        return [
            'uv',
            path.join(homeDir, '.local', 'bin', 'uv'),
            path.join(homeDir, '.cargo', 'bin', 'uv'),
            '/opt/homebrew/bin/uv',
            '/usr/local/bin/uv',
        ];
    } else {
        return [
            'uv',
            path.join(homeDir, '.local', 'bin', 'uv'),
            path.join(homeDir, '.cargo', 'bin', 'uv'),
            '/usr/local/bin/uv',
            '/snap/bin/uv',
        ];
    }
}

/**
 * Derive uvx path from a known uv path.
 */
export function getUvxPath(uvPath: string): string {
    if (uvPath === 'uv') {
        return 'uvx';
    }
    const dir = path.dirname(uvPath);
    const ext = process.platform === 'win32' ? '.exe' : '';
    return path.join(dir, `uvx${ext}`);
}

/**
 * Get the install command for uv based on platform.
 */
export function getUvInstallCommand(): string {
    if (process.platform === 'win32') {
        return 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"';
    }
    return 'curl -LsSf https://astral.sh/uv/install.sh | sh';
}

/**
 * Find the actual uv binary path by checking known locations.
 */
export async function findUvPath(log?: (msg: string) => void): Promise<string | null> {
    const paths = getUvSearchPaths();
    const _log = log || (() => { /* noop */ });

    const enrichedPath = enrichPath(process.env.PATH || '');

    for (const uvPath of paths) {
        try {
            if (uvPath === 'uv') {
                await execAsync('uv --version', { env: { ...process.env, PATH: enrichedPath } });
                _log('Found uv in PATH');
                return 'uv';
            } else if (fs.existsSync(uvPath)) {
                await execAsync(`"${uvPath}" --version`);
                _log(`Found uv at: ${uvPath}`);
                return uvPath;
            }
        } catch {
            // Continue to next path
        }
    }

    return null;
}

/**
 * Install uv and return the installed path.
 */
export async function installUvHeadless(log?: (msg: string) => void): Promise<string | null> {
    const _log = log || (() => { /* noop */ });
    const command = getUvInstallCommand();

    _log(`Installing uv on ${process.platform}...`);
    _log(`Running: ${command}`);

    try {
        const enrichedPath = enrichPath(process.env.PATH || '');
        await execAsync(command, {
            timeout: 120000,
            env: { ...process.env, PATH: enrichedPath },
        });

        await new Promise(resolve => setTimeout(resolve, 2000));

        const uvPath = await findUvPath(log);
        if (uvPath) {
            _log(`uv installed successfully at: ${uvPath}`);
        } else {
            _log('uv installation completed but binary not found');
        }
        return uvPath;
    } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        _log(`uv installation failed: ${errorMsg}`);
        return null;
    }
}

/**
 * Build MCP server command. Prefers pre-installed tool binary, falls back to uvx.
 * Returns [command, args, isPreInstalled].
 */
export function buildMcpCommand(
    uvPath: string,
    packageName: string,
    binaryName?: string,
): [string, string[], boolean] {
    const binary = binaryName || packageName;
    const installed = findInstalledTool(binary);

    if (installed) {
        return [installed, [], true];
    }

    const uvxPath = getUvxPath(uvPath);
    return [uvxPath, [packageName], false];
}

/**
 * Build MCP environment variables.
 */
export function buildMcpEnv(options: {
    workspaceDir?: string;
    pythonPath?: string;
}): Record<string, string> {
    const env: Record<string, string> = {};
    if (options.workspaceDir) {
        env['RDE_WORKSPACE'] = options.workspaceDir;
    }
    if (options.pythonPath) {
        env['PYTHONPATH'] = options.pythonPath;
    }
    env['PYTHONUTF8'] = '1';
    env['PYTHONIOENCODING'] = 'utf-8';
    return env;
}

/**
 * Check if a tool binary is installed and available.
 */
export function findInstalledTool(name: string): string | null {
    const ext = process.platform === 'win32' ? '.exe' : '';
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';

    const candidates: string[] = [];

    if (process.platform === 'win32') {
        const localAppData = process.env.LOCALAPPDATA || path.join(homeDir, 'AppData', 'Local');
        candidates.push(
            path.join(localAppData, 'uv', 'bin', `${name}${ext}`),
            path.join(homeDir, '.local', 'bin', `${name}${ext}`),
            path.join(homeDir, '.cargo', 'bin', `${name}${ext}`),
        );
    } else {
        candidates.push(
            path.join(homeDir, '.local', 'bin', `${name}${ext}`),
            path.join(homeDir, '.cargo', 'bin', `${name}${ext}`),
        );
        if (process.platform === 'darwin') {
            candidates.push(path.join('/opt/homebrew/bin', `${name}${ext}`));
        }
    }

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }

    return null;
}

/**
 * Ensure a tool is installed persistently via uv tool install.
 */
export async function ensureInstalledTool(
    packageName: string,
    binaryName?: string,
    _extraArgs?: string[],
    log?: (msg: string) => void,
): Promise<void> {
    const _log = log || (() => { /* noop */ });
    const binary = binaryName || packageName;
    const installed = findInstalledTool(binary);

    const enrichedPath = enrichPath(process.env.PATH || '');
    const execOpts = { timeout: 120000, env: { ...process.env, PATH: enrichedPath } };

    if (installed) {
        _log(`${packageName} already installed at ${installed}, attempting upgrade...`);
        try {
            await execAsync(`uv tool upgrade ${packageName}`, execOpts);
            _log(`${packageName} upgraded successfully`);
        } catch {
            _log(`${packageName} upgrade skipped (may already be latest)`);
        }
        return;
    }

    _log(`Installing ${packageName} via uv tool install...`);
    try {
        await execAsync(`uv tool install ${packageName}`, execOpts);
        _log(`${packageName} installed successfully`);
    } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        _log(`Failed to install ${packageName}: ${errorMsg}`);
    }
}

/**
 * Check if a Docker-based service is healthy by probing an HTTP endpoint.
 * Returns true if the endpoint responds within the timeout.
 */
export async function checkDockerServiceHealth(
    url: string,
    timeoutMs: number = 3000,
    log?: (msg: string) => void,
): Promise<boolean> {
    const _log = log || (() => { /* noop */ });

    // Use native http/https module to avoid external dependencies
    return new Promise<boolean>((resolve) => {
        try {
            const proto = url.startsWith('https') ? require('https') : require('http');
            const req = proto.get(url, { timeout: timeoutMs }, (res: any) => {
                // Any response (even 404) means the service is running
                _log(`Docker service at ${url} responded with status ${res.statusCode}`);
                res.resume(); // Consume response to free memory
                resolve(true);
            });
            req.on('error', () => {
                _log(`Docker service at ${url} not reachable`);
                resolve(false);
            });
            req.on('timeout', () => {
                _log(`Docker service at ${url} timed out`);
                req.destroy();
                resolve(false);
            });
        } catch {
            resolve(false);
        }
    });
}
