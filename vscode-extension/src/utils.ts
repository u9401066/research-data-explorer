/**
 * Utility functions for Research Data Explorer VS Code Extension.
 * Extracted for testability — NO vscode API dependency.
 */

import * as path from 'path';
import * as fs from 'fs';

/**
 * Determine the correct Python args based on the command being used.
 */
export function getPythonArgs(command: string, module: string): string[] {
    const baseCommand = path.basename(command).toLowerCase();
    const commandName = baseCommand.replace(/\.exe$/, '');

    if (commandName === 'uv') {
        return ['run', 'python', '-m', module];
    }

    if (commandName === 'uvx') {
        const packageMap: Record<string, string> = {
            'rde': 'research-data-explorer',
        };
        const pkg = packageMap[module];
        if (pkg) {
            return [pkg];
        }
        return [module];
    }

    if (commandName === 'python' || commandName === 'py' || /^python3(\.\d+)?$/.test(commandName)) {
        return ['-m', module];
    }

    if (command.includes('.venv') || command.includes('venv')) {
        return ['-m', module];
    }

    return [module];
}

/**
 * Load all SKILL.md files from a directory as concatenated instructions.
 */
export function loadSkillsAsInstructions(skillsPath: string): string {
    const instructions: string[] = [];

    if (!fs.existsSync(skillsPath)) {
        return '';
    }

    const skillDirs = fs.readdirSync(skillsPath, { withFileTypes: true })
        .filter(dirent => dirent.isDirectory())
        .map(dirent => dirent.name);

    for (const skillDir of skillDirs) {
        const skillFile = path.join(skillsPath, skillDir, 'SKILL.md');
        if (fs.existsSync(skillFile)) {
            const content = fs.readFileSync(skillFile, 'utf-8');
            instructions.push(`## Skill: ${skillDir}\n\n${content}`);
        }
    }

    return instructions.join('\n\n---\n\n');
}

/**
 * Load a single skill's content.
 */
export function loadSkillContent(skillsPath: string, skillName: string): string | null {
    const skillFile = path.join(skillsPath, skillName, 'SKILL.md');
    if (fs.existsSync(skillFile)) {
        return fs.readFileSync(skillFile, 'utf-8');
    }
    return null;
}

/**
 * Skills bundled in the VSX extension.
 */
export const BUNDLED_SKILLS = [
    'eda-workflow',
    'data-profiling',
    'report-generator',
    'session-start',
    'session-end',
    'memory-updater',
    'memory-checkpoint',
    'git-precommit',
] as const;

/**
 * Prompts bundled in the VSX extension.
 */
export const BUNDLED_PROMPTS = [
    'rde-phase-0-10',
    'rde-audit',
    'rde-code-review',
    'rde-pre-commit',
] as const;

/**
 * Agents bundled in the VSX extension.
 */
export const BUNDLED_AGENTS = [
    'architect',
    'ask',
    'audit',
    'code',
    'context-loader',
    'debug',
    'eda',
    'orchestrator',
    'test-runner',
] as const;
