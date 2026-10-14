/** Hosts that are never redirected: local development and LAN use of the Pi. */
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', 'core-node.local']);

/**
 * Production builds know where the app lives (VITE_PUBLIC_APP_ORIGIN). If the page is loaded from any
 * other origin, say an old installed copy on the API's Funnel host, move to the public one, keeping
 * path, query and hash. Returns true when a redirect was started.
 */
export function redirectToPublicOrigin(
  target: string | undefined = import.meta.env.VITE_PUBLIC_APP_ORIGIN as string | undefined,
  loc: Pick<Location, 'origin' | 'hostname' | 'pathname' | 'search' | 'hash' | 'replace'> = window.location,
  production: boolean = import.meta.env.PROD,
): boolean {
  if (!production || !target) return false;
  const origin = target.replace(/\/+$/, '');
  if (loc.origin === origin || LOCAL_HOSTS.has(loc.hostname)) return false;
  loc.replace(origin + loc.pathname + loc.search + loc.hash);
  return true;
}
