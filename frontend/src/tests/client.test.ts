import { describe, it, expect, vi, afterEach } from 'vitest'
import { listScholarships, getScholarship, matchScholarships, ApiError } from '../api/client'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('API client', () => {
  it('builds the list URL with filters and pagination', async () => {
    const fetchMock = mockFetch(200, { results: [], total: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await listScholarships({ q: 'mext', country: 'Japan', degree: 'Master', limit: 20, offset: 40 })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/scholarships?q=mext&country=Japan&degree=Master&limit=20&offset=40')
  })

  it('matches against the canonical recommendations path, not the legacy alias', async () => {
    // Two server routes return the same payload, so nothing breaks if the
    // client drifts to the wrong one. Only a test stops the drift: the
    // canonical path is the one documented as the contract.
    const fetchMock = mockFetch(200, { results: [], total: 0, returned: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await matchScholarships({
      target_country: 'United Kingdom',
      degree: 'Master',
      field_of_study: ['Computer Science'],
      current_gpa: 3.5,
      ielts_score: 7.0,
      toefl_score: null,
      funding_preference: 'Fully Funded',
      research_experience: 'Not Required',
      work_experience: 'Optional',
      publication: 'Not Required',
      leadership: false,
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/recommendations')
    expect(init?.method).toBe('POST')
  })

  it('normalizes a 404 into a not-found ApiError', async () => {
    vi.stubGlobal('fetch', mockFetch(404, { detail: 'Not found' }))
    await expect(getScholarship('abc')).rejects.toMatchObject({ kind: 'not-found', status: 404 })
  })

  it('parses 422 field errors from the backend detail format', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(422, {
        detail: ['target_country -> Select a valid country.', 'current_gpa -> must be finite'],
      }),
    )
    const error = await getScholarship('abc').then(
      () => null,
      (err: unknown) => err as ApiError,
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error!.kind).toBe('validation')
    expect(error!.fieldErrors).toEqual([
      'target_country: Select a valid country.',
      'current_gpa: must be finite',
    ])
  })

  it('normalizes network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(listScholarships()).rejects.toMatchObject({ kind: 'network' })
  })
})
