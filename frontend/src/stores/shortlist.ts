import { ref } from 'vue'

/*
 * Shortlist (saved scholarships): browser-local list of scholarship ids.
 * The backend has no persistence yet (Future API Requirement P1); the UI
 * states plainly that items are saved in this browser only.
 */

const STORAGE_KEY = 'polaris.shortlist.v1'

function load(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : []
  } catch {
    return []
  }
}

const ids = ref<string[]>(load())

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.value))
}

export function useShortlist() {
  function has(id: string): boolean {
    return ids.value.includes(id)
  }

  function toggle(id: string): boolean {
    if (has(id)) {
      ids.value = ids.value.filter((existing) => existing !== id)
      persist()
      return false
    }
    ids.value = [...ids.value, id]
    persist()
    return true
  }

  /** Drop ids that no longer resolve (detail returned 404). */
  function remove(id: string) {
    ids.value = ids.value.filter((existing) => existing !== id)
    persist()
  }

  return { ids, has, toggle, remove }
}
