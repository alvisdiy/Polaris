import type {
  ScholarshipDetail,
  ScholarshipListResponse,
  RecommendationListResponse,
  RecommendationRequest,
  ListParams,
} from './types'

export type ApiErrorKind = 'network' | 'not-found' | 'validation' | 'server' | 'empty-payload'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  /** Field-level messages parsed from a 422 response ('field -> message' strings). */
  readonly fieldErrors: string[]

  constructor(kind: ApiErrorKind, message: string, status?: number, fieldErrors: string[] = []) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

const API_BASE = '/api/v1'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError('network', 'Unable to reach Polaris. Check your connection and try again.')
  }

  if (response.ok) {
    if (response.status === 204) {
      throw new ApiError('empty-payload', 'The server returned an empty response.')
    }
    const text = await response.text()
    if (!text) {
      throw new ApiError('empty-payload', 'The server returned an empty response.')
    }
    try {
      return JSON.parse(text) as T
    } catch {
      throw new ApiError('server', 'The server response could not be read.', response.status)
    }
  }

  if (response.status === 404) {
    throw new ApiError('not-found', 'Not found.', 404)
  }

  if (response.status === 422) {
    const fieldErrors = await parseValidationErrors(response)
    throw new ApiError(
      'validation',
      fieldErrors[0] ?? 'Please review the highlighted fields.',
      422,
      fieldErrors,
    )
  }

  throw new ApiError('server', 'Something went wrong on our side. Please try again.', response.status)
}

async function parseValidationErrors(response: Response): Promise<string[]> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return [detail]
    if (Array.isArray(detail)) {
      return detail
        .map((item: unknown) => {
          if (typeof item === 'string') {
            // Backend formats seen: 'field -> message' and
            // 'body -> field: message' (nested Pydantic validation).
            // Both are normalized to 'field: message'.
            let normalized = item
            if (item.includes(' -> ')) {
              const [left, right] = item.split(' -> ')
              normalized = right.includes(':') ? right : `${left}: ${right}`
            }
            const [field, ...rest] = normalized.split(':')
            const message = rest.join(':').trim()
            return message ? `${field.trim()}: ${message}` : normalized
          }
          if (item && typeof item === 'object' && 'msg' in (item as Record<string, unknown>)) {
            const record = item as Record<string, unknown>
            const loc = Array.isArray(record.loc) ? record.loc.filter(Boolean).join('.') : ''
            return loc ? `${loc}: ${String(record.msg)}` : String(record.msg)
          }
          return String(item)
        })
        .filter(Boolean)
    }
  } catch {
    // fall through
  }
  return []
}

export function listScholarships(params: ListParams = {}): Promise<ScholarshipListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.country) search.set('country', params.country)
  if (params.degree) search.set('degree', params.degree)
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  const qs = search.toString()
  return request<ScholarshipListResponse>(`${API_BASE}/scholarships${qs ? `?${qs}` : ''}`)
}

export function getScholarship(id: string): Promise<ScholarshipDetail> {
  return request<ScholarshipDetail>(`${API_BASE}/scholarships/${encodeURIComponent(id)}`)
}

export function matchScholarships(
  profile: RecommendationRequest,
): Promise<RecommendationListResponse> {
  return request<RecommendationListResponse>(`${API_BASE}/recommendations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  })
}
