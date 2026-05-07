import * as fs from 'fs';
import * as path from 'path';

export interface UxHarnessArtifactDefinition {
    key: string;
    title: string;
    tool: string;
    relativePath: string;
    description: string;
}

export interface UxHarnessArtifact extends UxHarnessArtifactDefinition {
    absolutePath: string;
    exists: boolean;
    content: string | null;
    parsed: unknown | null;
    error: string | null;
}

export interface UxHarnessSummary {
    total: number;
    present: number;
    missing: number;
    missingTools: string[];
}

export const UX_HARNESS_ARTIFACTS: readonly UxHarnessArtifactDefinition[] = [
    {
        key: 'approval_card_json',
        title: 'Approval Card JSON',
        tool: 'get_approval_card',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'approval_card.json'),
        description: 'Structured approval state for confirmation gates.',
    },
    {
        key: 'approval_card_md',
        title: 'Approval Card Markdown',
        tool: 'get_approval_card',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'approval_card.md'),
        description: 'Readable approval card for no-code review.',
    },
    {
        key: 'harness_dashboard',
        title: 'Harness Dashboard',
        tool: 'get_harness_dashboard',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'harness_dashboard.json'),
        description: 'Current phase, gate, audit, and blocker projection.',
    },
    {
        key: 'artifact_index',
        title: 'Artifact Index',
        tool: 'build_artifact_index',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'artifact_index.json'),
        description: 'Navigation index for generated EDA artifacts.',
    },
    {
        key: 'blocker_playbook_json',
        title: 'Blocker Playbook JSON',
        tool: 'get_blocker_playbook',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'blocker_playbook.json'),
        description: 'Structured blocker remediation guidance.',
    },
    {
        key: 'blocker_playbook_md',
        title: 'Blocker Playbook Markdown',
        tool: 'get_blocker_playbook',
        relativePath: path.join('artifacts', 'phase_00_project_setup', 'blocker_playbook.md'),
        description: 'Readable blocker playbook for users.',
    },
] as const;

export function readUxHarnessArtifacts(workspaceRoot: string): UxHarnessArtifact[] {
    return UX_HARNESS_ARTIFACTS.map(definition => {
        const absolutePath = resolveUxHarnessArtifactPath(workspaceRoot, definition);
        const relativePath = path.relative(workspaceRoot, absolutePath) || definition.relativePath;
        if (!fs.existsSync(absolutePath)) {
            return {
                ...definition,
                relativePath,
                absolutePath,
                exists: false,
                content: null,
                parsed: null,
                error: null,
            };
        }

        try {
            const content = fs.readFileSync(absolutePath, 'utf-8');
            const parsed = absolutePath.endsWith('.json') ? JSON.parse(content) : null;
            return {
                ...definition,
                relativePath,
                absolutePath,
                exists: true,
                content,
                parsed,
                error: null,
            };
        } catch (error) {
            return {
                ...definition,
                relativePath,
                absolutePath,
                exists: true,
                content: null,
                parsed: null,
                error: error instanceof Error ? error.message : String(error),
            };
        }
    });
}

function resolveUxHarnessArtifactPath(
    workspaceRoot: string,
    definition: UxHarnessArtifactDefinition,
): string {
    const artifactRelativePath = toArtifactRootRelativePath(definition.relativePath);
    for (const artifactRoot of candidateArtifactRoots(workspaceRoot)) {
        const candidate = path.join(artifactRoot, artifactRelativePath);
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }
    return path.join(workspaceRoot, definition.relativePath);
}

function toArtifactRootRelativePath(relativePath: string): string {
    const marker = `artifacts${path.sep}`;
    if (relativePath.startsWith(marker)) {
        return relativePath.slice(marker.length);
    }
    if (relativePath.startsWith('artifacts/')) {
        return relativePath.slice('artifacts/'.length);
    }
    return relativePath;
}

function candidateArtifactRoots(workspaceRoot: string): string[] {
    const roots: string[] = [path.join(workspaceRoot, 'artifacts')];
    const projectsRoot = path.join(workspaceRoot, 'data', 'projects');
    if (!fs.existsSync(projectsRoot)) {
        return roots;
    }

    const projectArtifactRoots = fs.readdirSync(projectsRoot, { withFileTypes: true })
        .filter(entry => entry.isDirectory())
        .map(entry => path.join(projectsRoot, entry.name, 'artifacts'))
        .filter(candidate => fs.existsSync(candidate))
        .sort((left, right) => right.localeCompare(left));

    return roots.concat(projectArtifactRoots);
}

export function summarizeUxHarnessArtifacts(artifacts: readonly UxHarnessArtifact[]): UxHarnessSummary {
    const missingTools: string[] = [];
    for (const artifact of artifacts) {
        if (!artifact.exists && !missingTools.includes(artifact.tool)) {
            missingTools.push(artifact.tool);
        }
    }

    const present = artifacts.filter(artifact => artifact.exists).length;
    return {
        total: artifacts.length,
        present,
        missing: artifacts.length - present,
        missingTools,
    };
}

export function renderUxHarnessDashboardHtml(
    artifacts: readonly UxHarnessArtifact[],
    generatedAt = new Date().toISOString(),
): string {
    const summary = summarizeUxHarnessArtifacts(artifacts);
    const redactRoots = inferRedactionRoots(artifacts);
    const missingTools = summary.missingTools.length > 0
        ? summary.missingTools.map(tool => `<code>${escapeHtml(tool)}</code>`).join(', ')
        : 'none';
    const cards = artifacts.map(artifact => renderArtifactCard(artifact, redactRoots)).join('\n');

    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RDE UX Harness</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: var(--vscode-font-family, Segoe UI, sans-serif);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
    }
    body { margin: 0; padding: 24px; }
    header { border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 16px; }
    h1 { font-size: 24px; margin: 0 0 8px; letter-spacing: 0; }
    h2 { font-size: 16px; margin: 0 0 8px; letter-spacing: 0; }
    p { line-height: 1.5; margin: 4px 0; }
    code, pre { font-family: var(--vscode-editor-font-family, Consolas, monospace); }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }
    .metric, .artifact {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      padding: 12px;
      background: var(--vscode-sideBar-background);
    }
    .metric strong { display: block; font-size: 22px; margin-top: 4px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      border: 1px solid var(--vscode-panel-border);
    }
    .ok { color: var(--vscode-testing-iconPassed, #2e7d32); }
    .missing { color: var(--vscode-testing-iconFailed, #b00020); }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 260px;
      overflow: auto;
      border-radius: 4px;
      padding: 10px;
      background: var(--vscode-textCodeBlock-background);
    }
    .path { overflow-wrap: anywhere; color: var(--vscode-descriptionForeground); }
  </style>
</head>
<body>
  <header>
    <h1>UX Harness</h1>
    <p>Generated: ${escapeHtml(generatedAt)}</p>
    <p>Missing MCP tools to run: ${missingTools}</p>
  </header>
  <section class="summary" aria-label="UX harness summary">
    <div class="metric"><span>Artifacts present</span><strong>${summary.present} / ${summary.total}</strong></div>
    <div class="metric"><span>Missing artifacts</span><strong>${summary.missing}</strong></div>
    <div class="metric"><span>Unique tools needed</span><strong>${summary.missingTools.length}</strong></div>
  </section>
  <main class="grid">
    ${cards}
  </main>
</body>
</html>`;
}

function renderArtifactCard(artifact: UxHarnessArtifact, redactRoots: readonly string[]): string {
    const statusClass = artifact.exists ? 'ok' : 'missing';
    const statusText = artifact.exists ? 'present' : 'missing';
    const preview = artifact.error
        ? `Error: ${artifact.error}`
        : artifact.exists
            ? artifactPreview(artifact, redactRoots)
            : `Run ${artifact.tool} to create this artifact.`;

    return `<article class="artifact">
  <h2>${escapeHtml(artifact.title)}</h2>
  <p><span class="status ${statusClass}">${statusText}</span></p>
  <p>${escapeHtml(artifact.description)}</p>
  <p class="path">${escapeHtml(artifact.relativePath)}</p>
  <p>Tool: <code>${escapeHtml(artifact.tool)}</code></p>
  <pre>${escapeHtml(preview)}</pre>
</article>`;
}

function artifactPreview(artifact: UxHarnessArtifact, redactRoots: readonly string[]): string {
    const preview = artifact.parsed !== null
        ? JSON.stringify(artifact.parsed, null, 2)
        : artifact.content ?? '';
    return redactLocalPaths(preview, redactRoots);
}

function inferRedactionRoots(artifacts: readonly UxHarnessArtifact[]): string[] {
    const roots: string[] = [];
    for (const artifact of artifacts) {
        const normalized = artifact.absolutePath.replace(/\\/g, '/');
        const marker = '/artifacts/';
        const index = normalized.lastIndexOf(marker);
        if (index <= 0) {
            continue;
        }
        const root = normalized.slice(0, index);
        if (root && !roots.includes(root)) {
            roots.push(root);
        }
    }
    return roots.sort((left, right) => right.length - left.length);
}

function redactLocalPaths(value: string, roots: readonly string[]): string {
    let redacted = value;
    for (const root of roots) {
        const variants = [
            root,
            root.replace(/\//g, '\\'),
            root.replace(/\//g, '\\\\'),
        ];
        for (const variant of variants) {
            if (!variant) {
                continue;
            }
            redacted = redacted.split(variant).join('<redacted-path>');
        }
    }
    return redacted;
}

function escapeHtml(value: unknown): string {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
