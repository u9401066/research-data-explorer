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
});