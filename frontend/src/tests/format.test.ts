import { describe, it, expect, vi } from 'vitest'
import { formatDate, hostOf, isPastDeadline, deadlineDisplay } from '../lib/format'

describe('formatDate', () => {
  it('formats an ISO date in a readable form', () => {
    expect(formatDate('2027-03-01')).toBe('March 1, 2027')
  })

  it('returns null for null and invalid input', () => {
    expect(formatDate(null)).toBeNull()
    expect(formatDate('not-a-date')).toBeNull()
  })
})

describe('hostOf', () => {
  it('extracts the host from a URL', () => {
    expect(hostOf('https://www.studyinjapan.go.jp/en/')).toBe('www.studyinjapan.go.jp')
  })

  it('returns null for invalid URLs', () => {
    expect(hostOf('not a url')).toBeNull()
  })
})

describe('isPastDeadline', () => {
  it('detects past dates', () => {
    expect(isPastDeadline('2001-01-01')).toBe(true)
  })

  it('detects future dates', () => {
    expect(isPastDeadline('2099-01-01')).toBe(false)
  })

  it('returns false for null', () => {
    expect(isPastDeadline(null)).toBe(false)
  })
})

describe('deadlineDisplay', () => {
  it('maps a future date to active', () => {
    const result = deadlineDisplay('2099-01-01')
    expect(result.state).toBe('active')
    expect(result.date).not.toBeNull()
  })

  it('maps a past date to expired', () => {
    const result = deadlineDisplay('2001-01-01')
    expect(result.state).toBe('expired')
  })

  it('maps a missing deadline to unknown without inventing a date', () => {
    const result = deadlineDisplay(null)
    expect(result.state).toBe('unknown')
    expect(result.date).toBeNull()
    expect(result.label).toBe('Deadline unknown')
  })

  it('keeps today as active, not expired', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2027-03-01T12:00:00Z'))
    const result = deadlineDisplay('2027-03-01')
    expect(result.state).toBe('active')
    vi.useRealTimers()
  })
})
