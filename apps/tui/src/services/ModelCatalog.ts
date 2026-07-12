/** ModelCatalog — singleton service for fetching and caching model catalogs.
 *
 * Uses provider adapters from src/providers/ to fetch model lists.
 * No hardcoded models — all data comes from real API calls.
 */

import type { ModelInfo, ModelCatalogResult } from "./model-types.js";
import { getAdapter } from "../providers/registry.js";

interface CacheEntry {
  models: ModelInfo[];
  fetchedAt: number;
}

const DEFAULT_TTL_MS = 10 * 60 * 1000;

export class ModelCatalog {
  private static cache = new Map<string, CacheEntry>();
  private static ttl = DEFAULT_TTL_MS;

  static setTTL(ms: number): void {
    ModelCatalog.ttl = ms;
  }

  static clearCache(): void {
    ModelCatalog.cache.clear();
  }

  static invalidate(providerId: string): void {
    ModelCatalog.cache.delete(providerId);
  }

  static isCached(providerId: string): boolean {
    const entry = ModelCatalog.cache.get(providerId);
    if (!entry) return false;
    return Date.now() - entry.fetchedAt < ModelCatalog.ttl;
  }

  static cachedAt(providerId: string): number | null {
    return ModelCatalog.cache.get(providerId)?.fetchedAt ?? null;
  }

  static async getModels(
    providerId: string,
    apiKey?: string,
    baseUrl?: string,
  ): Promise<ModelCatalogResult> {
    const entry = ModelCatalog.cache.get(providerId);
    if (entry && Date.now() - entry.fetchedAt < ModelCatalog.ttl) {
      return {
        models: entry.models,
        error: null,
        cachedAt: entry.fetchedAt,
      };
    }

    const adapter = getAdapter(providerId);
    if (!adapter) {
      return {
        models: [],
        error: `Unknown provider: "${providerId}"`,
        cachedAt: null,
      };
    }

    if (!apiKey && providerId !== "ollama") {
      return {
        models: [],
        error: `API key required for provider "${providerId}"`,
        cachedAt: null,
      };
    }

    try {
      const rawModels = await adapter.listModels(apiKey ?? "", baseUrl);
      const models: ModelInfo[] = rawModels.map((m) => ({
        id: m.id,
        name: m.name,
        context_window: 0,
        cost_per_1k_input: 0,
        cost_per_1k_output: 0,
        capabilities: ["streaming"],
        free: false,
      }));
      const fetchedAt = Date.now();
      ModelCatalog.cache.set(providerId, { models, fetchedAt });
      return { models, error: null, cachedAt: fetchedAt };
    } catch (err) {
      if (entry) {
        return {
          models: entry.models,
          error: `Could not refresh — using cached data (${String(err)})`,
          cachedAt: entry.fetchedAt,
        };
      }
      return {
        models: [],
        error: String(err),
        cachedAt: null,
      };
    }
  }
}
