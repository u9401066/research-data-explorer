import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { canonicalAssets } from './asset-manifest.mjs';

const extDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoDir = path.dirname(extDir);
for (const [source, destination] of canonicalAssets) {
    const target = path.join(extDir, destination);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(repoDir, source), target);
}
console.log(`[assets] Synchronized ${canonicalAssets.length} canonical harness/illustration assets.`);
