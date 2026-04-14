import path from 'path';

import { describe, expect, it } from 'vitest';

import { getPythonArgs } from '../src/utils';

describe('utils', () => {
    it('builds default uv module args for repo workspaces', () => {
        expect(getPythonArgs('uv', 'rde')).toEqual(['run', 'python', '-m', 'rde']);
    });

    it('builds uv project args for bundled tool execution', () => {
        const bundledProject = path.join('tmp', 'bundled', 'tool');

        expect(getPythonArgs('uv', 'rde', { projectPath: bundledProject })).toEqual([
            'run',
            '--project',
            bundledProject,
            'python',
            '-m',
            'rde',
        ]);
    });

    it('treats POSIX virtualenv interpreters as python module runners', () => {
        expect(getPythonArgs('/tmp/workspace/.venv/bin/python', 'rde')).toEqual(['-m', 'rde']);
        expect(getPythonArgs('/tmp/workspace/venv/bin/python3', 'rde')).toEqual(['-m', 'rde']);
    });

    it('treats Windows virtualenv interpreters as python module runners', () => {
        expect(getPythonArgs('C:\\repo\\.venv\\Scripts\\python.exe', 'rde')).toEqual(['-m', 'rde']);
        expect(getPythonArgs('C:\\repo\\VENV\\Scripts\\python.exe', 'rde')).toEqual(['-m', 'rde']);
    });
});
