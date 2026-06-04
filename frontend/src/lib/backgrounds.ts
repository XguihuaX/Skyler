// v3.5 chunk 5a — frontend API client for /api/backgrounds.
// 2026-06-04 · Round 5 step 2 — add upload + delete + ``source`` discrimination
// (bundled = read-only shipped sample, user = appData-stored writable upload),
// plus ``resolveBackgroundUrl`` so SceneSection / SceneBackground don't have to
// branch on source for ``<img src>`` themselves.
//
// Backend single source of truth for schema (FastAPI TypedDict response_model);
// drift here triggers TS errors via the consumer call sites.

const BACKEND_BASE = 'http://127.0.0.1:8000';

export type BackgroundSource = 'bundled' | 'user';

export interface BackgroundItem {
  name: string;             // display name (no suffix)
  path: string;              // relative URL:
                             //   bundled → /backgrounds/<name>.<ext>  (Vite serves)
                             //   user    → /userdata/backgrounds/<name>.<ext>  (backend mount)
  type: 'image' | 'video';
  size: number;
  source: BackgroundSource;
}

export interface BackgroundsScanResponse {
  scan_dirs: string[];       // diagnostics: list of dirs that were scanned
  items: BackgroundItem[];
}

export async function fetchBackgrounds(): Promise<BackgroundsScanResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/backgrounds`);
  if (!res.ok) throw new Error(`fetch backgrounds failed: ${res.status}`);
  return (await res.json()) as BackgroundsScanResponse;
}

/** Build a browser-consumable URL from a {@link BackgroundItem}.
 *
 * - bundled: relative ``/backgrounds/...`` — Vite serves from frontend/public.
 * - user:    backend serves via StaticFiles mount, needs ``BACKEND_BASE`` prefix.
 *
 * Use this whenever you put a path into ``<img src>`` or ``store.globalScene.path``;
 * once persisted to localStorage the URL is opaque to consumers.
 */
export function resolveBackgroundUrl(item: BackgroundItem): string {
  return item.source === 'user' ? `${BACKEND_BASE}${item.path}` : item.path;
}

/** Upload a single image/video to the user backgrounds dir.
 *
 * @param file  the asset (suffix whitelist enforced by backend)
 * @param name  optional display name (form text). Empty → backend uses the
 *              file's original stem. Backend sanitizes + suffixes duplicates.
 */
export async function uploadBackground(
  file: File,
  name: string,
): Promise<BackgroundItem> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('name', name);
  const res = await fetch(`${BACKEND_BASE}/api/backgrounds/upload`, {
    method: 'POST',
    body: fd,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch { /* swallow body parse error, use status code */ }
    throw new Error(`upload failed: ${detail}`);
  }
  return (await res.json()) as BackgroundItem;
}

/** Delete a user-uploaded background by **filename** (with extension).
 *
 * ``name`` must come from a ``BackgroundItem.path`` (last segment of the
 * /userdata/backgrounds/ URL) for a ``user`` item. Bundled items hit 400 from
 * backend; do not call for them.
 */
export async function deleteBackground(filename: string): Promise<void> {
  const res = await fetch(
    `${BACKEND_BASE}/api/backgrounds/${encodeURIComponent(filename)}`,
    { method: 'DELETE' },
  );
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch { /* swallow */ }
    throw new Error(`delete failed: ${detail}`);
  }
}

/** Extract the filename (with extension) from a user item's path. */
export function userFilenameFromItem(item: BackgroundItem): string | null {
  if (item.source !== 'user') return null;
  const i = item.path.lastIndexOf('/');
  return i >= 0 ? item.path.slice(i + 1) : item.path;
}
