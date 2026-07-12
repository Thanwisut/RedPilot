/** Model types — shared across ModelCatalog service, SetupWizard, and MainConsole. */

export interface ModelInfo {
  id: string;
  name: string;
  context_window: number;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  capabilities: string[];
  free: boolean;
}

export interface ProviderConfig {
  provider: string;
  apiKey: string;
  model?: string;
}

/** Normalized result from ModelCatalog.getModels() */
export interface ModelCatalogResult {
  models: ModelInfo[];
  /** Human-readable error message (null if successful) */
  error: string | null;
  /** When the cache was last refreshed (null if never) */
  cachedAt: number | null;
}
