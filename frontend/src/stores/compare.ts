import { ref } from 'vue'

/*
 * Compare selection: in-memory list of scholarship ids (max 4), synced to
 * the /compare URL by the view. Deliberately not persisted across sessions
 * (web-design.md section 26); the shortlist is the persistent list.
 */

export const COMPARE_MAX = 4

const ids = ref<string[]>([])

export function useCompare() {
  function has(id: string): boolean {
    return ids.value.includes(id)
  }

  function isFull(): boolean {
    return ids.value.length >= COMPARE_MAX
  }

  /** Returns false when the list is full and the id is new. */
  function toggle(id: string): boolean {
    if (has(id)) {
      ids.value = ids.value.filter((existing) => existing !== id)
      return true
    }
    if (isFull()) return false
    ids.value = [...ids.value, id]
    return true
  }

  function remove(id: string) {
    ids.value = ids.value.filter((existing) => existing !== id)
  }

  function clear() {
    ids.value = []
  }

  return { ids, has, isFull, toggle, remove, clear }
}
