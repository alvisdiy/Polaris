import { ref, shallowRef } from 'vue'
import {
  ApiError,
  getScholarship,
  listScholarships,
  matchScholarships,
} from './client'
import type {
  ListParams,
  Recommendation,
  RecommendationRequest,
  ScholarshipDetail,
  ScholarshipListResponse,
} from './types'

export type RequestState = 'idle' | 'loading' | 'success' | 'error'

export function useScholarshipList(initial: ListParams = {}) {
  const data = shallowRef<ScholarshipListResponse | null>(null)
  const state = ref<RequestState>('idle')
  const error = shallowRef<ApiError | null>(null)
  const loadedParams = ref<ListParams>(initial)

  async function fetchList(params: ListParams) {
    state.value = 'loading'
    error.value = null
    loadedParams.value = params
    try {
      const response = await listScholarships(params)
      // Defensive: an empty page with a nonzero total is treated as an error
      // (web-design.md section 8).
      if (response.results.length === 0 && response.total > 0 && (params.offset ?? 0) > 0) {
        throw new ApiError('empty-payload', 'The requested page is outside the result set.')
      }
      data.value = response
      state.value = 'success'
    } catch (err) {
      error.value = err instanceof ApiError ? err : new ApiError('server', 'Something went wrong.')
    }
  }

  return { data, state, error, fetchList, loadedParams }
}

export function useScholarshipDetail() {
  const data = shallowRef<ScholarshipDetail | null>(null)
  const state = ref<RequestState>('idle')
  const error = shallowRef<ApiError | null>(null)

  async function fetchDetail(id: string) {
    state.value = 'loading'
    error.value = null
    data.value = null
    try {
      data.value = await getScholarship(id)
      state.value = 'success'
    } catch (err) {
      error.value = err instanceof ApiError ? err : new ApiError('server', 'Something went wrong.')
    }
  }

  return { data, state, error, fetchDetail }
}

export function useMatching() {
  const results = shallowRef<Recommendation[]>([])
  /** Size of the whole match set, which can exceed the Top-N page. */
  const total = ref(0)
  /** How many results are actually on screen. */
  const returned = ref(0)
  const state = ref<RequestState>('idle')
  const error = shallowRef<ApiError | null>(null)

  async function submitMatch(profile: RecommendationRequest) {
    state.value = 'loading'
    error.value = null
    try {
      const response = await matchScholarships(profile)
      results.value = response.results
      total.value = response.total
      returned.value = response.returned
      state.value = 'success'
    } catch (err) {
      results.value = []
      total.value = 0
      returned.value = 0
      error.value = err instanceof ApiError ? err : new ApiError('server', 'Something went wrong.')
    }
  }

  return { results, total, returned, state, error, submitMatch }
}
