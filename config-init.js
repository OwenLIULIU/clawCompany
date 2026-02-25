import fs from 'node:fs';
import path from 'node:path';

const configPath = process.env.OPENCLAW_CONFIG_PATH || '/workspace/.openclaw/openclaw.json';
const hostWorkspaceRoot = process.env.HOST_WORKSPACE_ROOT;

// Helper to recursively clean sessions.json of stale sessionFile paths.
// The gateway (2026.2.12+) validates that session file paths resolve within
// the sessions directory via realpath.  Stale absolute paths from previous
// HOME values (/root, /home/node, etc.) will fail that check.  Removing
// the sessionFile field lets the gateway recompute the correct path.
function migrateSessionPaths(dir) {
  if (!fs.existsSync(dir)) return;
  try {
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);
      if (stat.isDirectory()) {
        migrateSessionPaths(fullPath);
      } else if (file === 'sessions.json') {
        let content = fs.readFileSync(fullPath, 'utf8');
        // Detect any sessionFile pointing outside /workspace/.openclaw
        const stalePathRe = /\/(?:root|home\/node)\/\.openclaw/;
        if (stalePathRe.test(content)) {
          console.log(`Stripping stale sessionFile paths in ${fullPath}...`);
          try {
            const store = JSON.parse(content);
            let cleaned = 0;
            for (const key of Object.keys(store)) {
              if (store[key] && store[key].sessionFile && stalePathRe.test(store[key].sessionFile)) {
                delete store[key].sessionFile;
                cleaned++;
              }
            }
            if (cleaned > 0) {
              fs.writeFileSync(fullPath, JSON.stringify(store, null, 2));
              console.log(`  Cleaned ${cleaned} stale sessionFile entries.`);
            }
          } catch (parseErr) {
            // Fallback: simple string replacement
            content = content.replace(/\/root\/\.openclaw/g, '/workspace/.openclaw');
            content = content.replace(/\/home\/node\/\.openclaw/g, '/workspace/.openclaw');
            fs.writeFileSync(fullPath, content);
            console.log(`  Fallback: replaced stale paths via string replacement.`);
          }
        }
      }
    }
  } catch (err) {
    console.error(`Error migrating paths in ${dir}:`, err);
  }
}

if (!hostWorkspaceRoot) {
  console.warn("HOST_WORKSPACE_ROOT not set. Skipping sandbox workspaceRoot injection.");
}

try {
  if (!fs.existsSync(configPath)) {
    console.error(`Config file not found at ${configPath}`);
  } else {

    const configRaw = fs.readFileSync(configPath, 'utf8');
    // Use Function constructor to parse relaxed JSON (comments, unquoted keys)
    const config = (new Function('return ' + configRaw))();

    // Ensure structure
    if (!config.agents) config.agents = {};
    if (!config.agents.defaults) config.agents.defaults = {};
    if (!config.agents.defaults.sandbox) config.agents.defaults.sandbox = {};

    // Inject Host Path for Sandbox DinD mounting
    if (hostWorkspaceRoot) {
      console.log(`Injecting sandbox.workspaceRoot = ${hostWorkspaceRoot}`);
      config.agents.defaults.sandbox.workspaceRoot = hostWorkspaceRoot;
    }
    
    // Ensure Gateway internal workspace path is set to the mount point inside container
    console.log(`Setting internal workspace = /workspace`);
    config.agents.defaults.workspace = "/workspace";

    // Write back formatted JSON
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
    console.log("Config updated successfully.");
  }

  // Migrate session paths in the config directory
  const configDir = path.dirname(configPath);
  migrateSessionPaths(configDir);

} catch (e) {
  console.error("Failed to update config or migrate paths:", e);
  process.exit(1);
}
