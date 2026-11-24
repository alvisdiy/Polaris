/*
 * Types mirroring api/schemas.py exactly. Fields the backend does not
 * return are intentionally absent; do not add fields without a backend
 * change (docs/web-design.md, section 25).
 */

export type DeadlineState = 'active' | 'rolling' | 'unknown' | 'expired' | 'legacy'

export interface ScholarshipSummary {
  scholarship_id: string
  scholarship_name: string
  /** Null when the record has no provider resolved. Never the string "Unknown". */
  provider_name: string | null
  country: string | null
  degree: string | null
  /** The award's levels when the page stated several. */
  degree_levels?: string[]
  funding_type: string
  field_of_study: string[]
  deadline: string | null
  /** When the record was last checked against its official page. Null when never recorded. */
  last_verified_at: string | null
  official_url: string
}

export interface ScholarshipListResponse {
  results: ScholarshipSummary[]
  total: number
}

export interface ScholarshipRequirement {
  minimum_gpa: number | null
  ielts_required: boolean
  minimum_ielts: number | null
  toefl_required: boolean
  minimum_toefl: number | null
  work_experience: string | null
  research_experience: string | null
  publication: string | null
}

export interface ScholarshipBenefit {
  tuition_fee: boolean
  monthly_allowance: boolean
  accommodation: boolean
  health_insurance: boolean
  travel_ticket: boolean
  research_grant: boolean
}

export interface ScholarshipTimeline {
  application_open: string | null
  application_deadline: string | null
  application_cycle: string | null
  interview_date: string | null
  result_date: string | null
  study_start: string | null
}

export interface ScholarshipDetail {
  scholarship_id: string
  scholarship_name: string
  provider_name: string | null
  provider_type: string | null
  country: string | null
  degree: string | null
  /** The award's levels when the page stated several. */
  degree_levels?: string[]
  funding_type: string
  field_of_study: string[]
  official_url: string
  application_url: string | null
  /** When the record was last checked against its official page. */
  last_verified_at: string | null
  /** The detail schema has no top-level deadline; it lives on timeline. */
  deadline?: string | null
  requirement: ScholarshipRequirement | null
  benefit: ScholarshipBenefit | null
  timeline: ScholarshipTimeline | null
}

export interface RecommendationRequest {
  target_country: string
  degree: string
  field_of_study: string[]
  current_gpa: number
  ielts_score: number | null
  toefl_score: number | null
  research_experience: string
  work_experience: string
  publication: string
  leadership: boolean
  funding_preference: string
}

export interface Recommendation {
  scholarship_id: string
  scholarship_name: string
  deadline: string | null
  provider_name: string | null
  country: string | null
  match_score: number
  recommendation_category: string
  explanation: string
  strengths: string[]
  gaps: string[]
  next_steps: string[]
  official_url: string
}

export interface RecommendationListResponse {
  results: Recommendation[]
  /** Every approved, non-expired scholarship that matched the profile. */
  total: number
  /** How many are in `results`; capped at the engine's Top-N. */
  returned: number
}

export type ListParams = {
  q?: string
  country?: string
  degree?: string
  sort?: 'deadline' | 'name'
  limit?: number
  offset?: number
}
