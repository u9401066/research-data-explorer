import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const extDir = path.resolve(scriptDir, '..');
const utilsPath = path.join(extDir, 'src', 'utils.ts');

function readConstantArray(source, name) {
    const match = source.match(new RegExp(`export const ${name} = \\[([\\s\\S]*?)\\] as const;`));
    if (!match) {
        throw new Error(`Missing ${name} in src/utils.ts`);
    }
    return [...match[1].matchAll(/'([^']+)'/g)].map(match => match[1]);
}

function assertFile(relativePath) {
    const fullPath = path.join(extDir, relativePath);
    if (!fs.existsSync(fullPath)) {
        throw new Error(`Missing bundled asset: ${relativePath}`);
    }
}

const utilsSource = fs.readFileSync(utilsPath, 'utf-8');
const skills = readConstantArray(utilsSource, 'BUNDLED_SKILLS');
const prompts = readConstantArray(utilsSource, 'BUNDLED_PROMPTS');
const agents = readConstantArray(utilsSource, 'BUNDLED_AGENTS');
const clineRules = readConstantArray(utilsSource, 'BUNDLED_CLINE_RULES');

for (const skill of skills) {
    assertFile(path.join('skills', skill, 'SKILL.md'));
}
for (const prompt of prompts) {
    assertFile(path.join('prompts', `${prompt}.prompt.md`));
}
for (const agent of agents) {
    assertFile(path.join('agents', `${agent}.agent.md`));
}
for (const rule of clineRules) {
    assertFile(path.join('clinerules', rule));
}

assertFile('AGENTS.md');

const vscodeIgnore = fs.readFileSync(path.join(extDir, '.vscodeignore'), 'utf-8');
for (const pattern of ['.venv/**', 'venv/**', 'bundled/tool/.venv/**']) {
    if (!vscodeIgnore.includes(pattern)) {
        throw new Error(`.vscodeignore missing ${pattern}`);
    }
}

console.log('[assets] Bundled agent assets are complete.');
