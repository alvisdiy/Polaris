import { describe, it, expect, vi, afterEach } from 'vitest'
import { approveRecord, getReviewQueue, patchRecord } from '../api/review'
import { ApiError } from '../api/client'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('review API client', () => {
  it('sends the operator token and queue parameters', async () => {
    const fetchMock = mockFetch(200, { results: [], total: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await getReviewQueue('secret-token', 'pending_review', 50, 0)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/admin/review/scholarships?state=pending_review&limit=50&offset=0')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-token')
  })

  it('posts an approval with actor, reason and the override flag', async () => {
    const fetchMock = mockFetch(200, {
      scholarship_id: 'abc',
      previous_state: 'pending_review',
      new_state: 'approved',
      action: 'approve',
      quality_report: null,
    })
    vi.stubGlobal('fetch', fetchMock)

    await approveRecord('t', 'abc', { actor: 'kai', reason: 'verified', override_quality: true })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/admin/review/scholarships/abc/approve')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      actor: 'kai',
      reason: 'verified',
      override_quality: true,
    })
  })

  it('patches corrections as a changes dict with a reason', async () => {
    const fetchMock = mockFetch(200, {
      scholarship_id: 'abc',
      previous_state: 'pending_review',
      new_state: 'pending_review',
      action: 'correct',
      quality_report: null,
    })
    vi.stubGlobal('fetch', fetchMock)

    await patchRecord('t', 'abc', {
      actor: 'kai',
      reason: 'official page moved the deadline',
      changes: { deadline: '2027-05-01' },
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/admin/review/scholarships/abc')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string).changes).toEqual({ deadline: '2027-05-01' })
  })

  it('surfaces a rejected token as an actionable error', async () => {
    vi.stubGlobal('fetch', mockFetch(401, { detail: 'Admin authentication required' }))
    await expect(getReviewQueue('wrong', 'pending_review')).rejects.toMatchObject({
      message: expect.stringContaining('token was rejected'),
    })
  })

  it('surfaces a disabled review surface distinctly', async () => {
    vi.stubGlobal('fetch', mockFetch(503, { detail: 'disabled' }))
    await expect(getReviewQueue('t', 'pending_review')).rejects.toBeInstanceOf(ApiError)
    await expect(getReviewQueue('t', 'pending_review')).rejects.toMatchObject({
      message: expect.stringContaining('disabled on this server'),
    })
  })
})
