/** Config store with file persistence.
 *
 * Reads/writes configuration to ~/.redpilot/config.json so that
 * the Setup Wizard only runs on first launch.
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ProviderConfig } from "./model-types.js";

const CONFIG_DIR = join(homedir(), ".redpilot");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");

let _config: ProviderConfig | null = null;

function loadFromDisk(): ProviderConfig | null {
  try {
    if (!existsSync(CONFIG_PATH)) return null;
    const raw = readFileSync(CONFIG_PATH, "utf-8");
    const parsed = JSON.parse(raw) as ProviderConfig;
    if (parsed.provider && parsed.apiKey) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

function saveToDisk(config: ProviderConfig): void {
  try {
    if (!existsSync(CONFIG_DIR)) {
      mkdirSync(CONFIG_DIR, { recursive: true });
    }
    writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), "utf-8");
  } catch {
    // Silently fail — config still exists in memory
  }
}

function deleteConfigFile(): void {
  try {
    if (existsSync(CONFIG_PATH)) {
      writeFileSync(CONFIG_PATH, JSON.stringify({}), "utf-8");
    }
  } catch {
    // ignore
  }
}

export function getConfig(): ProviderConfig | null {
  if (!_config) {
    _config = loadFromDisk();
  }
  return _config;
}

export function setConfig(config: ProviderConfig): void {
  _config = config;
  saveToDisk(config);
}

export function clearConfig(): void {
  _config = null;
  deleteConfigFile();
}

export function isConfigured(): boolean {
  const cfg = getConfig();
  return cfg !== null && !!cfg.provider && !!cfg.apiKey;
}
