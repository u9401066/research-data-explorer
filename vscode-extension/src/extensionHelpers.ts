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
    return mcpJsonContent.includes('"rde"') && mcpJsonContent.includes('research-data-explorer');
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

    if (configuredPath) {
        if (configuredPath === 'uv' || configuredPath === 'uvx') {
            return configuredPath;
        }
        if (fs.existsSync(configuredPath)) {
            return configuredPath;
        }
    }

    if (wsRoot) {
        const pyprojectPath = path.join(wsRoot, 'pyproject.toml');
        if (isRdeProject(pyprojectPath)) {
            return 'uv';
        }
    }

    if (wsRoot) {
        const venvCandidates = process.platform === 'win32'
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
            ];
        for (const venvPath of venvCandidates) {
            if (fs.existsSync(venvPath)) {
                return venvPath;
            }
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
    if (fs.existsSync(bundledToolPath)) {
        paths.push(bundledToolPath);
    }
    return paths.join(path.delimiter);
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
): { missingSkills: number; missingAgents: number; missingPrompts: number; total: number } {
    const skillsDir = path.join(wsRoot, '.claude', 'skills');
    const agentsDir = path.join(wsRoot, '.github', 'agents');
    const promptsDir = path.join(wsRoot, '.github', 'prompts');

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

    const total = missingSkills + missingAgents + missingPrompts;
    return { missingSkills, missingAgents, missingPrompts, total };
}
