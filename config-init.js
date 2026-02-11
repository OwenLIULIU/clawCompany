import fs from 'node:fs';
import path from 'node:path';

const configPath = process.env.OPENCLAW_CONFIG_PATH || '/root/.openclaw/openclaw.json';
const hostWorkspaceRoot = process.env.HOST_WORKSPACE_ROOT;

if (!hostWorkspaceRoot) {
  console.warn("HOST_WORKSPACE_ROOT not set. Skipping sandbox workspaceRoot injection.");
  process.exit(0);
}

try {
  if (!fs.existsSync(configPath)) {
    console.error(`Config file not found at ${configPath}`);
    process.exit(0); // Don't fail, maybe using defaults or different path
  }

  const configRaw = fs.readFileSync(configPath, 'utf8');
  // Use Function constructor to parse relaxed JSON (comments, unquoted keys)
  // This is safe locally as we trust the config file
  const config = (new Function('return ' + configRaw))();

  // Ensure structure
  if (!config.agents) config.agents = {};
  if (!config.agents.defaults) config.agents.defaults = {};
  if (!config.agents.defaults.sandbox) config.agents.defaults.sandbox = {};

  // Inject Host Path for Sandbox DinD mounting
  // CRITICAL: OpenClaw reads from sandbox.workspaceRoot (NOT sandbox.docker.workspaceRoot)
  console.log(`Injecting sandbox.workspaceRoot = ${hostWorkspaceRoot}`);
  config.agents.defaults.sandbox.workspaceRoot = hostWorkspaceRoot;
  
  // Ensure Gateway internal workspace path is set to the mount point inside container
  // We expect volume: ./workspace:/workspace
  console.log(`Setting internal workspace = /workspace`);
  config.agents.defaults.workspace = "/workspace";

  // Reverted invalid mode enforcement

  // Write back formatted JSON
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
  console.log("Config updated successfully.");


} catch (e) {
  console.error("Failed to update config:", e);
  process.exit(1);
}
