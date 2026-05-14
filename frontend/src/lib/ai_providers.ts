/**
 * bugfix-3.2: AI Providers REST client.
 *
 * 跟 bugfix-3.1 backend endpoint 1:1 对齐:
 *   GET    /api/ai-vendors
 *   POST   /api/ai-vendors
 *   PATCH  /api/ai-vendors/{id}
 *   DELETE /api/ai-vendors/{id}
 *   POST   /api/ai-vendors/{id}/credentials
 *   DELETE /api/ai-vendors/{id}/credentials
 *
 *   GET    /api/ai-providers?type=llm|asr|tts
 *   POST   /api/ai-providers
 *   PATCH  /api/ai-providers/{id}
 *   DELETE /api/ai-providers/{id}
 *   POST   /api/ai-providers/{id}/activate
 *
 * 错误处理:fetch 失败 / non-2xx 一律抛 ``Error(msg)``, caller catch 后 toast。
 * detail 优先(后端 HTTPException), 否则用 status code。
 */

const BACKEND_BASE = 'http://127.0.0.1:8000';

export type ProviderType = 'llm' | 'asr' | 'tts';
export type VendorKind = 'builtin' | 'custom';
export type ProviderKind = 'builtin' | 'custom';

export type CredentialSource = 'db' | 'env' | 'none';

export interface AIVendor {
  id: string;
  name: string;
  vendor_kind: VendorKind;
  default_endpoint: string | null;
  credential_key_name: string;
  endpoint_env_name: string | null;  // bugfix-3.2.6
  color: string | null;
  icon: string | null;
  has_credential: boolean;
  credential_source: CredentialSource;  // bugfix-3.2.6
}

export interface AIProvider {
  id: number;
  vendor_id: string | null;
  type: ProviderType;
  name: string;
  model: string;
  endpoint: string | null;
  extra_json: string | null;
  provider_kind: ProviderKind;
  enabled: boolean;
  is_active: boolean;
}

// VendorGroup is grouped response —— bugfix-3.2.6 起 backend 回全套 AIVendor
// 字段(credentials modal 需要 credential_key_name / endpoint_env_name)。
export interface VendorGroup extends AIVendor {
  providers: AIProvider[];
}

export interface GroupedProvidersResponse {
  vendors: VendorGroup[];
  ungrouped: AIProvider[];
}

// ---------------------------------------------------------------------------
// Internal: typed fetch wrapper
// ---------------------------------------------------------------------------

async function _req<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BACKEND_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Vendors
// ---------------------------------------------------------------------------

export function listVendors(): Promise<AIVendor[]> {
  return _req<AIVendor[]>('/api/ai-vendors');
}

export interface CreateVendorBody {
  id: string;
  name: string;
  default_endpoint?: string | null;
  credential_key_name: string;
  endpoint_env_name?: string | null;  // bugfix-3.2.6
  color?: string | null;
  icon?: string | null;
}

export function createVendor(body: CreateVendorBody): Promise<AIVendor> {
  return _req<AIVendor>('/api/ai-vendors', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface UpdateVendorBody {
  name?: string;
  default_endpoint?: string | null;
  credential_key_name?: string;
  endpoint_env_name?: string | null;  // bugfix-3.2.6
  color?: string | null;
  icon?: string | null;
}

export function updateVendor(id: string, body: UpdateVendorBody): Promise<AIVendor> {
  return _req<AIVendor>(`/api/ai-vendors/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function deleteVendor(id: string): Promise<void> {
  return _req<void>(`/api/ai-vendors/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function setVendorCredentials(id: string, key_value: string): Promise<void> {
  return _req<void>(`/api/ai-vendors/${encodeURIComponent(id)}/credentials`, {
    method: 'POST',
    body: JSON.stringify({ key_value }),
  });
}

export function clearVendorCredentials(id: string): Promise<void> {
  return _req<void>(`/api/ai-vendors/${encodeURIComponent(id)}/credentials`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

export function listProvidersByType(type: ProviderType): Promise<GroupedProvidersResponse> {
  return _req<GroupedProvidersResponse>(`/api/ai-providers?type=${type}`);
}

export interface CreateProviderBody {
  vendor_id?: string | null;
  type: ProviderType;
  name: string;
  model: string;
  endpoint?: string | null;
  extra_json?: string | null;
}

export function createProvider(body: CreateProviderBody): Promise<AIProvider> {
  return _req<AIProvider>('/api/ai-providers', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export interface UpdateProviderBody {
  name?: string;
  model?: string;
  endpoint?: string | null;
  extra_json?: string | null;
  enabled?: boolean;
}

export function updateProvider(id: number, body: UpdateProviderBody): Promise<AIProvider> {
  return _req<AIProvider>(`/api/ai-providers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export function deleteProvider(id: number): Promise<void> {
  return _req<void>(`/api/ai-providers/${id}`, { method: 'DELETE' });
}

export function activateProvider(id: number): Promise<AIProvider> {
  return _req<AIProvider>(`/api/ai-providers/${id}/activate`, { method: 'POST' });
}
