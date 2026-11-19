import { reactive, watch } from 'vue'
import type { RecommendationRequest } from '../api/types'

/*
 * Profile store: a typed reactive draft of the matching profile. Persisted
 * to localStorage only after a successful match, per web-design.md section
 * 26. There is no server persistence (Future API Requirement P1).
 */

const STORAGE_KEY = 'polaris.profile.v1'

export type ProfileDraft = RecommendationRequest

export function emptyProfile(): ProfileDraft {
  return {
    target_country: '',
    degree: '',
    field_of_study: [],
    current_gpa: 0,
    ielts_score: null,
    toefl_score: null,
    research_experience: '',
    work_experience: '',
    publication: '',
    leadership: false,
    funding_preference: '',
  }
}

function loadStored(): ProfileDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<ProfileDraft>
    // Merge over an empty profile so schema evolution cannot produce a
    // partial object with missing keys.
    return { ...emptyProfile(), ...parsed }
  } catch {
    return null
  }
}

const storedProfile = loadStored()

const state = reactive<{ profile: ProfileDraft }>({
  profile: storedProfile ?? emptyProfile(),
})

let hasStored = storedProfile !== null

watch(
  () => state.profile,
  (value) => {
    if (hasStored) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    }
  },
  { deep: true },
)

export function useProfile() {
  function markSaved() {
    hasStored = true
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.profile))
  }

  function clear() {
    localStorage.removeItem(STORAGE_KEY)
    hasStored = false
    Object.assign(state.profile, emptyProfile())
  }

  return {
    profile: state.profile,
    isStored: hasStored,
    markSaved,
    clear,
  }
}
