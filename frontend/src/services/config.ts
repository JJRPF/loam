import { useSyncExternalStore } from 'react';

/** Public server settings from GET /api/config. Defaults are the safe production values. */
export interface AppConfig {
  midpoints_enabled: boolean;
  min_unique_riders: number;
  seed_heat_public: boolean;
  connectors: Record<string, boolean>;
  source_url: string;
}

const DEFAULTS: AppConfig = {
  midpoints_enabled: false,
  min_unique_riders: 3,
  seed_heat_public: true,
  connectors: {},
  source_url: 'https://github.com/JJRPF/loam'
};

let config: AppConfig = DEFAULTS;
let loaded: Promise<AppConfig> | null = null;
const listeners = new Set<() => void>();

export function getAppConfig(): AppConfig {
  return config;
}

/** Fetches the config once (3 s timeout); on failure the defaults stay (midpoints and connectors off). */
export function loadAppConfig(apiBase: string): Promise<AppConfig> {
  if (!loaded) {
    loaded = (async () => {
      try {
        const res = await fetch(`${apiBase}/api/config`, { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
          config = { ...DEFAULTS, ...(await res.json()) };
          listeners.forEach((l) => l());
        }
      } catch {
        // offline or the API is down: keep the defaults
      }
      return config;
    })();
  }
  return loaded;
}

export function useAppConfig(): AppConfig {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => config
  );
}

export const MIDPOINTS_OFF_NOTICE = 'Midpoints are turned off for now, so this route ignores them.';
