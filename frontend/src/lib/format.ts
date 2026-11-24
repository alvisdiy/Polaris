import type { DeadlineState } from '../api/types'

/*
 * Presentation helpers. Scholarship data itself is never modified; only
 * formatting. Deadline display derives from the real `deadline` value only
 * (the backend does not expose deadline_state yet; see web-design.md section
 * 12 and the P0 future API list). No invented dates. The countdown label is
 * arithmetic on the stated date — the number of whole days between today
 * and the deadline the source published — not an additional fact.
 */

const UNKNOWN_DEADLINE = 'Deadline unknown'

/** Parse an ISO date (YYYY-MM-DD) as a UTC calendar date. */
function parseUtcDate(iso: string): Date | null {
  const date = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Today's calendar date in UTC, so comparisons are zone-independent. */
function todayUtc(): Date {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
}

export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = parseUtcDate(iso)
  if (!date) return null
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export function hostOf(url: string): string | null {
  try {
    return new URL(url).host
  } catch {
    return null
  }
}

/** True when the deadline date is strictly before today (UTC calendar). */
export function isPastDeadline(iso: string | null | undefined): boolean {
  if (!iso) return false
  const date = parseUtcDate(iso)
  if (!date) return false
  return date.getTime() < todayUtc().getTime()
}

export type DeadlineDisplay = {
  state: DeadlineState
  label: string
  date: string | null
}

/**
 * Derive the deadline display from the fields the API actually returns.
 * Mapping:
 *  - real future date -> active
 *  - real past date   -> expired (possible on detail / saved items)
 *  - null deadline    -> unknown (the source does not say)
 * The backend's rolling/unclassified states are not yet exposed; when the
 * P0 field lands this function is the single place to update.
 */
/** Whole UTC days from today until the deadline; null when unparseable. */
export function daysUntilDeadline(deadline: string | null | undefined): number | null {
  if (!deadline) return null
  const date = parseUtcDate(deadline)
  if (!date) return null
  return Math.round((date.getTime() - todayUtc().getTime()) / 86_400_000)
}

export function deadlineDisplay(deadline: string | null): DeadlineDisplay {
  if (!deadline) {
    return { state: 'unknown', label: UNKNOWN_DEADLINE, date: null }
  }
  const formatted = formatDate(deadline)
  if (!formatted) {
    return { state: 'unknown', label: UNKNOWN_DEADLINE, date: null }
  }
  if (isPastDeadline(deadline)) {
    return { state: 'expired', label: 'Past deadline', date: formatted }
  }
  // "Active" alone gives a student no sense of urgency; the countdown is
  // the same date, expressed as time remaining. Beyond roughly two
  // quarters the exact count stops being actionable, so the plain state
  // label returns.
  const days = daysUntilDeadline(deadline)
  if (days !== null && days <= 180) {
    if (days === 0) return { state: 'active', label: 'Closes today', date: formatted }
    if (days === 1) return { state: 'active', label: 'Closes tomorrow', date: formatted }
    return { state: 'active', label: `Closes in ${days} days`, date: formatted }
  }
  return { state: 'active', label: 'Active', date: formatted }
}
