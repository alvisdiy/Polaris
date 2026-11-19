import { describe, it, expect, beforeEach } from 'vitest'
import { useCompare, COMPARE_MAX } from '../stores/compare'

describe('compare store', () => {
  beforeEach(() => {
    useCompare().clear()
  })

  it('starts empty', () => {
    expect(useCompare().ids.value).toEqual([])
  })

  it('toggles membership', () => {
    const compare = useCompare()
    expect(compare.toggle('a')).toBe(true)
    expect(compare.has('a')).toBe(true)
    expect(compare.toggle('a')).toBe(true)
    expect(compare.has('a')).toBe(false)
  })

  it('caps the selection at four', () => {
    const compare = useCompare()
    for (const id of ['a', 'b', 'c', 'd']) {
      expect(compare.toggle(id)).toBe(true)
    }
    expect(compare.isFull()).toBe(true)
    // A fifth item is rejected.
    expect(compare.toggle('e')).toBe(false)
    expect(compare.ids.value).toHaveLength(COMPARE_MAX)
  })

  it('removes a single item', () => {
    const compare = useCompare()
    compare.toggle('a')
    compare.toggle('b')
    compare.remove('a')
    expect(compare.has('a')).toBe(false)
    expect(compare.has('b')).toBe(true)
  })
})
