/** Thin fetch wrapper. Same-origin via the Vite proxy in dev. */

export class ApiError extends Error {
  // Written out rather than declared as constructor parameter properties: the Vite
  // template sets erasableSyntaxOnly, which forbids syntax that emits runtime code.
  readonly status: number
  readonly path: string

  constructor(message: string, status: number, path: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // A non-JSON error body is still an error; the status carries the meaning.
    }
    throw new ApiError(detail, response.status, path)
  }
  return (await response.json()) as T
}

export interface Health {
  status: string
  engine_version: string
  today: string
  database: { path: string; ok: boolean; tables?: number; error?: string }
  packs: { id: string; name: string; version?: string; ok: boolean }[]
  default_pack: string
  assist_enabled: boolean
}

export const getHealth = () => api<Health>('/health')
