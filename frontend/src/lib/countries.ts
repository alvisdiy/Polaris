import { listCountries } from '../api/client'

/**
 * The country list for filter/profile dropdowns, from the API.
 *
 * This used to be hardcoded in two components, and the copies disagreed
 * (12 entries in Discover, 10 in the profile form). The catalogue is the
 * only honest source: it lists exactly the countries that have a
 * published scholarship. Cached per page load; a failed fetch yields an
 * empty list rather than a stale invented one.
 */
let cached: Promise<string[]> | null = null

export function loadCountries(): Promise<string[]> {
  if (!cached) {
    cached = listCountries().catch(() => [] as string[])
  }
  return cached
}
