import { ApiError } from './client'

/*
 * Review / curation client — the operator surface under
 * /api/v1/admin/review. Every call carries the operator bearer token;
 * the server fails closed (503) when no token is configured and 401s on
 * a wrong one. Types mirror api/schemas.py's review section; they are
 * deliberately separate from the public scholarship types because a
 * reviewer sees uncertainty and provenance the public API never exposes.
 */

const REVIEW_BASE = '/api/v1/admin/review'

export type FieldQuality = {
  field: string
  quality: 'KNOWN' | 'UNKNOWN' | 'NOT_APPLICABLE' | 'MISSING' | 'CONFLICTING' | string
  value: unknown
  detail: string
}

export type QualityReport = {
  publishable: boolean
  blocking: string[]
  conflicting: string[]
  overridden_fields: string[]
  fields: Record<string, FieldQuality>
}

export type ReviewItemSummary = {
  scholarship_id: string
  scholarship_name: string
  provider_name: string | null
  country: string | null
  official_url: string | null
  extraction_status: string
  provenance_origin: string | null
  extraction_confidence: number | null
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
  blocking_fields: string[]
  conflicting_fields: string[]
}

export type ReviewListResponse = {
  results: ReviewItemSummary[]
  total: number
}

export type ReviewPacket = {
  scholarship_id: string
  extraction_status: string
  identity: {
    scholarship_name: string
    provider_name: string | null
    provider_type: string | null
    country: string | null
    country_id: string | null
    university: string | null
    official_url: string | null
    application_url: string | null
    source_id: string
    source_name: string | null
    source_official_url: string | null
    source_verification_state: string | null
  }
  eligibility: {
    degree: string | null
    funding_type: string | null
    field_of_study: string[]
    minimum_gpa: number | null
    ielts_required: boolean | null
    minimum_ielts: number | null
    toefl_required: boolean | null
    minimum_toefl: number | null
    work_experience: string | null
    research_experience: string | null
    publication: string | null
  }
  funding: Record<string, boolean | null>
  timeline: {
    application_open: string | null
    application_deadline: string | null
    application_cycle: string | null
    interview_date: string | null
    result_date: string | null
    study_start: string | null
  }
  quality: QualityReport
  provenance_origin: string | null
  extraction_confidence: number | null
  conflicts: unknown[]
  source_documents: {
    document_id: string
    source_url: string
    fetched_at: string
    status_code: number | null
    processing_status: string | null
  }[]
  history: {
    review_action_id: string
    action: string
    actor: string
    occurred_at: string
    previous_state: string | null
    new_state: string
    reason: string | null
  }[]
  reviewed_at: string | null
}

export type ReviewMetrics = {
  total: number
  by_state: Record<string, number>
  by_origin: Record<string, number>
  pending_review: number
  approved: number
  rejected: number
  needs_correction: number
  approval_rate: number | null
}

export type ReviewOutcome = {
  scholarship_id: string
  previous_state: string
  new_state: string
  action: string
  quality_report: QualityReport | null
}

async function reviewRequest<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${REVIEW_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError('network', 'Unable to reach Polaris. Check your connection and try again.')
  }

  if (response.ok) {
    return (await response.json()) as T
  }
  if (response.status === 401 || response.status === 403) {
    throw new ApiError('server', 'The operator token was rejected. Check it and try again.', response.status)
  }
  if (response.status === 503) {
    throw new ApiError(
      'server',
      'The review API is disabled on this server (POLARIS_ADMIN_TOKEN is not set).',
      503,
    )
  }
  if (response.status === 404) {
    throw new ApiError('not-found', 'That record is no longer in the queue.', 404)
  }
  // Domain refusals (gate blocks, invalid transitions, bad corrections)
  // arrive as 409/422 with a detail message written for the reviewer.
  let detail = ''
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    /* fall through to the generic message */
  }
  throw new ApiError(
    'server',
    detail || `The server refused the action (${response.status}).`,
    response.status,
  )
}

export function getReviewQueue(
  token: string,
  state = 'pending_review',
  limit = 50,
  offset = 0,
): Promise<ReviewListResponse> {
  const search = new URLSearchParams({ state, limit: String(limit), offset: String(offset) })
  return reviewRequest<ReviewListResponse>(token, `/scholarships?${search}`)
}

export function getReviewPacket(token: string, id: string): Promise<ReviewPacket> {
  return reviewRequest<ReviewPacket>(token, `/scholarships/${encodeURIComponent(id)}`)
}

export function getReviewMetrics(token: string): Promise<ReviewMetrics> {
  return reviewRequest<ReviewMetrics>(token, '/metrics')
}

export type DecisionBody = {
  actor: string
  reason?: string | null
  evidence_url?: string | null
}

export function approveRecord(
  token: string,
  id: string,
  body: DecisionBody & { override_quality?: boolean },
): Promise<ReviewOutcome> {
  return reviewRequest<ReviewOutcome>(token, `/scholarships/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rejectRecord(token: string, id: string, body: DecisionBody): Promise<ReviewOutcome> {
  return reviewRequest<ReviewOutcome>(token, `/scholarships/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function requestCorrection(
  token: string,
  id: string,
  body: DecisionBody,
): Promise<ReviewOutcome> {
  return reviewRequest<ReviewOutcome>(
    token,
    `/scholarships/${encodeURIComponent(id)}/request-correction`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function patchRecord(
  token: string,
  id: string,
  body: DecisionBody & { changes: Record<string, unknown>; requeue?: boolean },
): Promise<ReviewOutcome> {
  return reviewRequest<ReviewOutcome>(token, `/scholarships/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
