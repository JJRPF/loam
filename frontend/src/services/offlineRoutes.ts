import type { RouteResponse } from '../types';

// The last routes the rider looked at, kept in IndexedDB so they can be viewed (and their GPX
// rebuilt) without a connection. Everything here is best effort: with storage blocked it does nothing.
const DB_NAME = 'loam_offline';
const STORE = 'recent_routes';
const KEEP = 10;

interface Entry {
  key: string;
  viewedAt: number;
  route: RouteResponse;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'key' });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

const keyOf = (r: RouteResponse) => r.id || `${r.name}|${r.distance_miles}|${r.coordinates?.length ?? 0}`;

export async function rememberRoute(route: RouteResponse): Promise<void> {
  try {
    if (!route.coordinates?.length) return;
    const db = await open();
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    store.put({ key: keyOf(route), viewedAt: Date.now(), route } as Entry);
    const all = store.getAll();
    all.onsuccess = () => {
      const entries = (all.result as Entry[]).sort((a, b) => b.viewedAt - a.viewedAt);
      entries.slice(KEEP).forEach((e) => store.delete(e.key));
    };
    await new Promise<void>((res) => { tx.oncomplete = () => res(); tx.onerror = () => res(); tx.onabort = () => res(); });
    db.close();
  } catch {
    // storage unavailable (private window, blocked site data)
  }
}

export async function recentRoutes(): Promise<RouteResponse[]> {
  try {
    const db = await open();
    const entries = await new Promise<Entry[]>((resolve) => {
      const req = db.transaction(STORE).objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result as Entry[]);
      req.onerror = () => resolve([]);
    });
    db.close();
    return entries.sort((a, b) => b.viewedAt - a.viewedAt).map((e) => e.route);
  } catch {
    return [];
  }
}
