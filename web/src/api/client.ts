/** Thin fetch wrapper. Same-origin via the Vite proxy in dev. */

export class ApiError extends Error {
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
      const body = (await response.json()) as { detail?: unknown }
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // A non-JSON error body is still an error; the status carries the meaning.
    }
    throw new ApiError(detail, response.status, path)
  }
  return (await response.json()) as T
}

export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

// --- shapes ---------------------------------------------------------------

export type Severity = 'BLOCKER' | 'CRITICAL' | 'WARNING' | 'INFO'

export interface Health {
  status: string
  engine_version: string
  today: string
  database: { path: string; ok: boolean; tables?: number; error?: string }
  packs: { id: string; name: string; version?: string; ok: boolean }[]
  default_pack: string
  assist_enabled: boolean
}

export interface NodeStat {
  node_id: string
  type: string
  label: string
  status: string
  rows_in: number
  rows_out: number
  quarantined: number
  duration_ms: number | null
  flags: Record<Severity, number>
  error: string | null
}

export interface RunDetail {
  run_id: string
  started_at: string | null
  finished_at: string | null
  status: string
  pack: string
  as_of: string | null
  duration_ms: number | null
  flags: Partial<Record<Severity, number>>
  nodes: NodeStat[]
  files: {
    original_name: string
    detected_source: string | null
    detect_confidence: number | null
    media_kind: string
    size_bytes: number
    is_duplicate: boolean
  }[]
  records: number
  segments: number
}

export interface Entity {
  type: string
  id: string
  display: string
}

export interface Flag {
  flag_id: string
  run_id: string
  rule_code: string
  severity: Severity
  category: string
  title: string
  message: string
  entities: Entity[]
  suggested_action: string
  owner_role: string
  status: string
  occurrence_count: number
  node_id: string | null
  params: Record<string, unknown>
}

export interface EvidenceItem {
  file_id: string | null
  file: string | null
  media_kind: string | null
  source_type: string | null
  row: number | null
  page: number | null
  column: string | null
  raw_value: string | null
  bbox: number[] | null
}

export interface FlagDetail extends Flag {
  evidence: EvidenceItem[]
  rule: { meaning: string; priority: string; severity_note: string; configured_by: string[] }
}

export interface PersonSummary {
  person_id: string
  display_name: string
  status: string
  employee_id: string | null
  role: string | null
  home_facility: string | null
  credentials: { type: string; expires_on: string | null }[]
  flags: Partial<Record<Severity, number>>
}

export interface Claim {
  value: string
  raw: string
  source: string
  observed_on: string | null
  file_id: string | null
  locator: Record<string, unknown>
  claim_id: string
}

export interface PersonDetail {
  run_id: string
  person: {
    person_id: string
    display_name: string
    status: string
    employee_id: string | null
    role: string | null
    home_facility: string | null
  }
  attributes: {
    attribute: string
    value: string
    won_because: string
    source: string
    raw: string | null
    conflicts: number
    all_claims: Claim[]
  }[]
  credentials: Record<string, unknown>[]
  shifts: Record<string, unknown>[]
  weeks: Record<string, unknown>[]
}

export interface FeatureScore {
  feature: string
  level: string
  label: string
  weight: number
  left: string
  right: string
  detail: string
}

export interface PersonGraph {
  run_id: string
  nodes: {
    id: string
    kind: 'person' | 'record' | 'credential'
    label: string
    source?: string
    status?: string
    row?: number | null
    expires_on?: string | null
    payload?: Record<string, unknown>
  }[]
  edges: {
    source: string
    target: string
    score?: number | null
    band?: string
    decided_by?: string
    explanation?: { total: number | null; band: string; label: string; features: FeatureScore[] }
  }[]
}

export interface StaffingRow {
  facility: string
  work_date: string
  person_id: string
  display_name: string
  role: string
  pbj_job_code: string
  scheduled_hours: number
  meal_deduction: number
  pbj_hours: number
  tier: 'VERIFIED' | 'CONFLICT' | 'SCHEDULE_ONLY' | 'UNALLOCATED'
}

export interface StaffingSummary {
  facility: string
  period_start: string
  period_end: string
  total_hours: number
  verified_hours: number
  unallocated_hours: number
  pct_verified: number
  pct_unallocated: number
  zero_rn_days: number
  zero_rn_warn: number
  zero_rn_critical: number
  cap_violations: number
  traceability_variance_pct: number
  traceability_threshold: number
  quarter: string | null
  quarter_due: string | null
  hours_by_role: Record<string, number>
}

export interface StaffingView {
  run_id: string
  as_of: string | null
  rows: StaffingRow[]
  assumptions: Record<string, unknown>
  summaries: StaffingSummary[]
}

export interface ExpiryRow {
  holder_type: string
  holder_id: string
  holder: string
  credential_type: string
  number: string
  facility: string
  expires_on: string | null
  days_left: number | null
  band: string
  last_verified: string | null
  verified_age_days: number | null
  verification_stale: boolean
  next_shift_after_expiry: string | null
  shifts_worked_after_expiry: number
  recert_hours_found: number | null
  recert_hours_required: number | null
  recert_ready: boolean | null
}

export interface Referral {
  facility: string
  date: string
  verdict: 'YES' | 'NO' | 'UNKNOWN'
  reasons: string[]
  rn_covered: string
  rn_longest_run: number
  rn_required_hours: number
  rn_windows: string[]
  licensed_hours: number
  aide_hours: number
  total_hours: number
  tours: Record<string, boolean>
  on_duty: {
    person_id: string
    display_name: string
    role_code: string
    hours: number
    window: string
    credential_status: string
  }[]
  open_critical: { rule_code: string; message: string }[]
  census: number | null
  hprd: Record<string, number>
  hprd_plus_one: Record<string, number>
  hprd_minimums: Record<string, number>
  note: string
}

export interface PipelineNode {
  id: string
  type: string
  label: string
  description: string
  consumes: string[]
  produces: string[]
  optional: boolean
  stats: Partial<NodeStat>
}

export interface PipelineGraph {
  version: number
  pack: string
  run_id: string | null
  order: string[]
  nodes: PipelineNode[]
  edges: { source: string; target: string; port: string; rows?: number | null }[]
}

export interface Param {
  key: string
  label: string
  unit: string
  type: string
  min: number | null
  max: number | null
  value: unknown
  overridden: boolean
  default: unknown
}

// --- calls ----------------------------------------------------------------

export const getHealth = () => api<Health>('/health')
export const listRuns = () => api<{ runs: RunDetail[] }>('/runs')
export const getRun = (runId: string) => api<RunDetail>(`/runs/${runId}`)
export const rerun = (runId: string) =>
  api<{ run_id: string }>(`/runs/${runId}/rerun`, { method: 'POST' })
export const replay = (runId: string) =>
  api<{ run_id: string; events: number; stream: string }>(`/runs/${runId}/replay`, {
    method: 'POST',
  })

export const listFlags = (params: Record<string, string | undefined>) =>
  api<{ run_id: string | null; flags: Flag[]; total: number; counts: Record<string, number> }>(
    `/flags${qs(params)}`,
  )
export const getFlag = (flagId: string, runId?: string) =>
  api<FlagDetail>(`/flags/${flagId}${qs({ run_id: runId })}`)

export const listPersons = (runId?: string) =>
  api<{ persons: PersonSummary[] }>(`/persons${qs({ run_id: runId })}`)
export const getPerson = (personId: string, runId?: string) =>
  api<PersonDetail>(`/persons/${personId}${qs({ run_id: runId })}`)
export const getPersonGraph = (personId: string, runId?: string) =>
  api<PersonGraph>(`/persons/${personId}/graph${qs({ run_id: runId })}`)

export const getStaffing = (params: Record<string, string | undefined>) =>
  api<StaffingView>(`/views/staffing${qs(params)}`)
export const getExpirations = (params: Record<string, string | undefined>) =>
  api<{ rows: ExpiryRow[]; counts: Record<string, number>; windows: number[]; as_of: string }>(
    `/views/expirations${qs(params)}`,
  )
export const getReferral = (params: Record<string, string | number | boolean | undefined>) =>
  api<Referral>(`/views/referral${qs(params)}`)

export const getPipeline = (runId?: string) =>
  api<PipelineGraph>(`/pipeline${qs({ run_id: runId })}`)
export const getParams = () => api<{ pack: string; params: Param[] }>('/pipeline/params')
export const putParams = (values: Record<string, unknown>) =>
  api<{ updated: string[] }>('/pipeline/params', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
export const resetParams = () => api<unknown>('/pipeline/params', { method: 'DELETE' })

export interface Decision {
  decision_id: string
  type: string
  key: string
  value: string
  actor: string | null
  reason: string | null
  created_at: string | null
  active: boolean
}
export const listDecisions = () =>
  api<{ decisions: Decision[]; count: number; digest: string }>('/decisions')
export const createDecision = (body: {
  decision_type: string
  key: Record<string, unknown>
  value?: Record<string, unknown>
  reason?: string
}) =>
  api<{ decision_id: string }>('/decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export async function uploadFiles(
  files: File[],
  options: { asOf?: string; pack?: string },
): Promise<{ run_id: string }> {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  if (options.asOf) form.append('as_of', options.asOf)
  if (options.pack) form.append('pack', options.pack)
  const response = await fetch('/api/ingest', { method: 'POST', body: form })
  if (!response.ok) throw new ApiError(await response.text(), response.status, '/ingest')
  return (await response.json()) as { run_id: string }
}
