/**
 * Extension Helpers — Pure functions extracted from extension.ts for testability.
 * NO dependency on the `vscode` API.
 */

import * as path from 'path';
import * as fs from 'fs';

/**
 * Check if the workspace has a user-defined rde MCP server in .vscode/mcp.json.
 */
export function shouldSkipMcpRegistration(mcpJsonContent: string): boolean {
    try {
        const parsed = JSON.parse(mcpJsonContent) as unknown;
        return hasRdeServerKey(parsed);
    } catch {
        return /"rde"\s*:/.test(mcpJsonContent)
            && /(research-data-explorer|python"\s*,\s*"-m"\s*,\s*"rde"|uvx)/.test(mcpJsonContent);
    }
}

function hasRdeServerKey(value: unknown): boolean {
    if (!value || typeof value !== 'object') {
        return false;
    }

    const record = value as Record<string, unknown>;
    for (const containerName of ['servers', 'mcpServers']) {
        const container = record[containerName];
        if (container && typeof container === 'object') {
            const servers = container as Record<string, unknown>;
            for (const [serverKey, serverValue] of Object.entries(servers)) {
                if (isRdeServerEntry(serverKey, serverValue)) {
                    return true;
                }
            }
        }
    }

    return Object.entries(record).some(([serverKey, serverValue]) =>
        isRdeServerEntry(serverKey, serverValue),
    );
}

function isRdeServerEntry(serverKey: string, value: unknown): boolean {
    if (!value || typeof value !== 'object') {
        return false;
    }
    if (serverKey === 'rde' || serverKey === 'research-data-explorer') {
        return true;
    }
    const entry = value as Record<string, unknown>;
    const command = typeof entry.command === 'string' ? entry.command : '';
    const args = Array.isArray(entry.args) ? entry.args.map(String).join(' ') : '';
    const haystack = `${serverKey} ${command} ${args}`;
    return /research-data-explorer|python\s+-m\s+rde|uvx\s+.*rde|uvx\s+.*research-data-explorer/.test(haystack);
}

/**
 * Check if the workspace is a development workspace (has RDE source code).
 */
export function isDevWorkspace(wsRoot: string): boolean {
    return fs.existsSync(path.join(wsRoot, 'src', 'rde'));
}

/**
 * Check if pyproject.toml belongs to the research-data-explorer project.
 */
export function isRdeProject(pyprojectPath: string): boolean {
    try {
        if (!fs.existsSync(pyprojectPath)) {
            return false;
        }
        const content = fs.readFileSync(pyprojectPath, 'utf-8');
        return content.includes('research-data-explorer');
    } catch {
        return false;
    }
}

/**
 * Determine the Python path to use.
 *
 * Priority:
 * 1. User configuration (if valid)
 * 2. 'uv' if workspace is the RDE project
 * 3. Virtual environment in workspace
 * 4. Fallback to 'uv'
 */
export function determinePythonPath(options: {
    configuredPath?: string;
    wsRoot?: string;
    extensionPath: string;
}): string {
    const { configuredPath, wsRoot, extensionPath } = options;
    const pyprojectPath = wsRoot ? path.join(wsRoot, 'pyproject.toml') : undefined;
    const isRepoProject = pyprojectPath ? isRdeProject(pyprojectPath) : false;

    const workspaceVenvCandidates = wsRoot
        ? (process.platform === 'win32'
            ? [
                path.join(wsRoot, '.venv', 'Scripts', 'python.exe'),
                path.join(wsRoot, 'venv', 'Scripts', 'python.exe'),
                path.join(wsRoot, '.venv', 'bin', 'python'),
                path.join(wsRoot, 'venv', 'bin', 'python'),
            ]
            : [
                path.join(wsRoot, '.venv', 'bin', 'python'),
                path.join(wsRoot, '.venv', 'bin', 'python3'),
                path.join(wsRoot, 'venv', 'bin', 'python'),
                path.join(wsRoot, 'venv', 'bin', 'python3'),
            ])
        : [];

    if (configuredPath) {
        if (configuredPath === 'uv') {
            return configuredPath;
        }
        if (configuredPath === 'uvx') {
            return isRepoProject ? 'uv' : configuredPath;
        }
        if (isRepoProject) {
            const normalizedConfiguredPath = path.normalize(configuredPath);
            for (const candidate of workspaceVenvCandidates) {
                if (path.normalize(candidate) === normalizedConfiguredPath && fs.existsSync(candidate)) {
                    return configuredPath;
                }
            }
            return 'uv';
        }
        if (fs.existsSync(configuredPath)) {
            return configuredPath;
        }
    }

    if (isRepoProject) {
        return 'uv';
    }

    for (const venvPath of workspaceVenvCandidates) {
        if (fs.existsSync(venvPath)) {
            return venvPath;
        }
    }

    const bundledPythonCandidates = process.platform === 'win32'
        ? [
            path.join(extensionPath, 'bundled', 'python', 'Scripts', 'python.exe'),
            path.join(extensionPath, 'bundled', 'python', 'python.exe'),
        ]
        : [
            path.join(extensionPath, 'bundled', 'python', 'bin', 'python3'),
            path.join(extensionPath, 'bundled', 'python', 'bin', 'python'),
        ];

    for (const bundledPython of bundledPythonCandidates) {
        if (fs.existsSync(bundledPython)) {
            return bundledPython;
        }
    }

    return 'uv';
}

/**
 * Build PYTHONPATH for development workspace.
 */
export function buildDevPythonPath(wsRoot: string, bundledToolPath: string): string {
    const paths = [
        path.join(wsRoot, 'src'),
    ];
    const bundledSrcPath = path.join(bundledToolPath, 'src');
    if (fs.existsSync(bundledSrcPath)) {
        paths.push(bundledSrcPath);
    } else if (fs.existsSync(bundledToolPath)) {
        paths.push(bundledToolPath);
    }
    return paths.join(path.delimiter);
}

/**
 * Check if the extension has a bundled local Python project for RDE.
 */
export function isBundledToolProject(projectRoot: string): boolean {
    return fs.existsSync(path.join(projectRoot, 'pyproject.toml'))
        && fs.existsSync(path.join(projectRoot, 'src', 'rde', '__main__.py'));
}

/**
 * Count missing bundled items in a workspace.
 */
export function countMissingBundledItems(
    wsRoot: string,
    extPath: string,
    bundledSkills: readonly string[],
    bundledAgents: readonly string[],
    bundledPrompts: readonly string[],
    bundledCodexSkills: readonly string[] = [],
    bundledClineRules: readonly string[] = [],
    includeCodexInstructions = false,
): {
    missingSkills: number;
    missingAgents: number;
    missingPrompts: number;
    missingCodexSkills: number;
    missingClineRules: number;
    missingCodexInstructions: number;
    total: number;
} {
    const skillsDir = path.join(wsRoot, '.claude', 'skills');
    const agentsDir = path.join(wsRoot, '.github', 'agents');
    const promptsDir = path.join(wsRoot, '.github', 'prompts');
    const codexSkillsDir = path.join(wsRoot, '.codex', 'skills');
    const clineRulesDir = path.join(wsRoot, '.clinerules');

    let missingSkills = 0;
    for (const skill of bundledSkills) {
        const src = path.join(extPath, 'skills', skill, 'SKILL.md');
        const dst = path.join(skillsDir, skill, 'SKILL.md');
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            missingSkills++;
        }
    }

    let missingAgents = 0;
    for (const agent of bundledAgents) {
        const src = path.join(extPath, 'agents', `${agent}.agent.md`);
        const dst = path.join(agentsDir, `${agent}.agent.md`);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            missingAgents++;
        }
    }

    let missingPrompts = 0;
    for (const prompt of bundledPrompts) {
        const src = path.join(extPath, 'prompts', `${prompt}.prompt.md`);
        const dst = path.join(promptsDir, `${prompt}.prompt.md`);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            missingPrompts++;
        }
    }

    let missingCodexSkills = 0;
    for (const skill of bundledCodexSkills) {
        const src = path.join(extPath, 'skills', skill, 'SKILL.md');
        const dst = path.join(codexSkillsDir, skill, 'SKILL.md');
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            missingCodexSkills++;
        }
    }

    let missingClineRules = 0;
    for (const rule of bundledClineRules) {
        const src = path.join(extPath, 'clinerules', rule);
        const dst = path.join(clineRulesDir, rule);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            missingClineRules++;
        }
    }

    const missingCodexInstructions = includeCodexInstructions
        && fs.existsSync(path.join(extPath, 'AGENTS.md'))
        && !fs.existsSync(path.join(wsRoot, 'AGENTS.md'))
        ? 1
        : 0;

    const total = missingSkills
        + missingAgents
        + missingPrompts
        + missingCodexSkills
        + missingClineRules
        + missingCodexInstructions;
    return {
        missingSkills,
        missingAgents,
        missingPrompts,
        missingCodexSkills,
        missingClineRules,
        missingCodexInstructions,
        total,
    };
}
