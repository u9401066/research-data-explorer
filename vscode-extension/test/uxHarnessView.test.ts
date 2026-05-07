import fs from 'fs';
import os from 'os';
import path from 'path';

import { afterEach, describe, expect, it } from 'vitest';

import {
    readUxHarnessArtifacts,
    renderUxHarnessDashboardHtml,
    summarizeUxHarnessArtifacts,
} from '../src/uxHarnessView';

const tempDirs: string[] = [];

function makeTempDir(): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rde-ux-'));
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

describe('uxHarnessView', () => {
    it('declares a VS Code command for opening the UX harness dashboard', () => {
        const pkg = JSON.parse(
            fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf-8'),
        );

        expect(pkg.contributes.commands).toEqual(expect.arrayContaining([
            expect.objectContaining({
                command: 'rde.openHarnessDashboard',
                category: 'RDE',
            }),
        ]));
    });

    it('summarizes missing UX harness artifacts with the MCP tools needed to create them', () => {
        const root = makeTempDir();
        const artifacts = readUxHarnessArtifacts(root);
        const summary = summarizeUxHarnessArtifacts(artifacts);

        expect(summary.total).toBe(6);
        expect(summary.present).toBe(0);
        expect(summary.missingTools).toEqual([
            'get_approval_card',
            'get_harness_dashboard',
            'build_artifact_index',
            'get_blocker_playbook',
        ]);

        const html = renderUxHarnessDashboardHtml(artifacts, '2026-05-07T00:00:00.000Z');
        expect(html).toContain('UX Harness');
        expect(html).toContain('get_approval_card');
        expect(html).toContain('build_artifact_index');
        expect(html).toContain('0 / 6');
    });

    it('renders existing JSON and Markdown artifacts safely', () => {
        const root = makeTempDir();
        const phase0 = path.join(root, 'artifacts', 'phase_00_project_setup');
        fs.mkdirSync(phase0, { recursive: true });
        fs.writeFileSync(
            path.join(phase0, 'approval_card.json'),
            JSON.stringify({
                title: '<script>alert(1)</script>',
                status: 'needs_approval',
                approvals: ['concept_alignment'],
            }),
        );
        fs.writeFileSync(
            path.join(phase0, 'blocker_playbook.md'),
            '# Blockers\n\n<script>alert(2)</script>\n',
        );

        const artifacts = readUxHarnessArtifacts(root);
        const summary = summarizeUxHarnessArtifacts(artifacts);
        const html = renderUxHarnessDashboardHtml(artifacts, '2026-05-07T00:00:00.000Z');

        expect(summary.present).toBe(2);
        expect(summary.missing).toBe(4);
        expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
        expect(html).toContain('&lt;script&gt;alert(2)&lt;/script&gt;');
        expect(html).not.toContain('<script>alert(1)</script>');
        expect(html).not.toContain('<script>alert(2)</script>');
    });

    it('redacts local absolute paths from rendered artifact previews', () => {
        const root = makeTempDir();
        const phase0 = path.join(root, 'artifacts', 'phase_00_project_setup');
        fs.mkdirSync(phase0, { recursive: true });
        fs.writeFileSync(
            path.join(phase0, 'artifact_index.json'),
            JSON.stringify({
                artifact_root: path.join(root, 'artifacts'),
                artifacts: [{ path: 'phase_00_project_setup/project.yaml' }],
            }),
        );

        const html = renderUxHarnessDashboardHtml(
            readUxHarnessArtifacts(root),
            '2026-05-07T00:00:00.000Z',
        );

        expect(html).toContain('&lt;redacted-path&gt;');
        expect(html).not.toContain(root);
    });

    it('discovers UX harness artifacts in the latest persisted RDE project directory', () => {
        const root = makeTempDir();
        const older = path.join(root, 'data', 'projects', '20260506_old', 'artifacts', 'phase_00_project_setup');
        const latest = path.join(root, 'data', 'projects', '20260507_latest', 'artifacts', 'phase_00_project_setup');
        fs.mkdirSync(older, { recursive: true });
        fs.mkdirSync(latest, { recursive: true });
        fs.writeFileSync(path.join(older, 'approval_card.json'), JSON.stringify({ status: 'older' }));
        fs.writeFileSync(path.join(latest, 'approval_card.json'), JSON.stringify({ status: 'latest' }));

        const artifacts = readUxHarnessArtifacts(root);
        const approvalCard = artifacts.find(artifact => artifact.key === 'approval_card_json');

        expect(approvalCard?.exists).toBe(true);
        expect(approvalCard?.absolutePath).toContain('20260507_latest');
        expect(approvalCard?.parsed).toEqual({ status: 'latest' });
    });
});
