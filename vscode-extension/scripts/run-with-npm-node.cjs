const { spawnSync } = require("child_process");
const path = require("path");

const [, , scriptPath, ...scriptArgs] = process.argv;

if (!scriptPath) {
  console.error("[run-with-npm-node] Missing script path.");
  process.exit(1);
}

const nodeExecutable = process.env.npm_node_execpath || process.env.NODE || process.execPath;
const resolvedScriptPath = path.resolve(process.cwd(), scriptPath);
const pathKey = Object.keys(process.env).find((key) => key.toLowerCase() === "path") || "PATH";
const nodeDirectory = path.dirname(nodeExecutable);
const existingPath = process.env[pathKey] || "";
const childEnv = {
  ...process.env,
  [pathKey]: existingPath ? `${nodeDirectory}${path.delimiter}${existingPath}` : nodeDirectory,
};
const result = spawnSync(nodeExecutable, [resolvedScriptPath, ...scriptArgs], {
  cwd: process.cwd(),
  env: childEnv,
  stdio: "inherit",
});

if (result.error) {
  console.error(`[run-with-npm-node] Failed to launch ${resolvedScriptPath}:`, result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);