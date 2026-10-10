import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { useLiveUpdates } from '../../src/lib/live'

type Listener = (e: { data: string }) => void

class FakeSource {
  static all: FakeSource[] = []
  listeners: Record<string, Listener[]> = {}
  onerror: (() => void) | null = null
  closed = false
  readyState = 0
  url: string
  constructor(url: string) {
    this.url = url
    FakeSource.all.push(this)
  }
  addEventListener(name: string, fn: Listener) {
    ;(this.listeners[name] ??= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(name: string, data: unknown = {}) {
    for (const fn of this.listeners[name] ?? []) fn({ data: JSON.stringify(data) })
  }
}

function setup(onAlert = vi.fn()) {
  const qc = new QueryClient()
  const spy = vi.spyOn(qc, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useLiveUpdates(onAlert), { wrapper })
  return { ...hook, spy, onAlert, source: () => FakeSource.all[FakeSource.all.length - 1] }
}

beforeEach(() => {
  FakeSource.all = []
  vi.stubGlobal('EventSource', FakeSource)
})

test('connects to the stream and shows live once the server says hello', () => {
  const { result, source, spy } = setup()
  expect(source().url).toBe('/api/events')
  expect(result.current).toBe('reconnecting')
  act(() => source().emit('hello'))
  expect(result.current).toBe('live')
  expect(spy).toHaveBeenCalledWith() // catch-up: everything is refetched
})

test('a change refetches only the queries of the topics that changed', () => {
  const { source, spy } = setup()
  spy.mockClear()
  act(() => source().emit('change', { topics: ['alerts', 'stats'] }))
  const keys = spy.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0])
  expect(keys).toEqual(['alerts', 'alert', 'stats', 'alert-readiness', 'schedules', 'audit'])
})

test('an unknown topic or a broken frame does nothing', () => {
  const { source, spy } = setup()
  spy.mockClear()
  act(() => source().emit('change', { topics: ['nope', 7] }))
  act(() => source().listeners.change![0]!({ data: 'not json' }))
  expect(spy).not.toHaveBeenCalled()
})

test('a new alert tells the page its id', () => {
  const { source, onAlert } = setup()
  act(() => source().emit('alert', { id: 12 }))
  expect(onAlert).toHaveBeenCalledWith(12)
})

test('a dropped connection says reconnecting and the next hello catches up', () => {
  const { result, source, spy } = setup()
  act(() => source().emit('hello'))
  act(() => source().onerror?.())
  expect(result.current).toBe('reconnecting')
  spy.mockClear()
  act(() => source().emit('hello'))
  expect(result.current).toBe('live')
  expect(spy).toHaveBeenCalledWith()
})

test('coming back to the tab refetches everything', () => {
  const { spy } = setup()
  spy.mockClear()
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
  expect(spy).toHaveBeenCalledWith()
})

test('leaving the page closes the stream', () => {
  const { unmount, source } = setup()
  const s = source()
  unmount()
  expect(s.closed).toBe(true)
})

test('a browser without EventSource is reported as unsupported', () => {
  vi.stubGlobal('EventSource', undefined)
  const { result } = setup()
  expect(result.current).toBe('unsupported')
})

test('a refused stream (signed out, too many portals) is reopened after a pause', () => {
  vi.useFakeTimers()
  try {
    const { result, source } = setup()
    const first = source()
    first.readyState = 2 // the browser gave up
    act(() => first.onerror?.())
    expect(result.current).toBe('reconnecting')
    expect(first.closed).toBe(true)
    expect(FakeSource.all.length).toBe(1)
    act(() => vi.advanceTimersByTime(5_000))
    expect(FakeSource.all.length).toBe(2)
    act(() => source().emit('hello'))
    expect(result.current).toBe('live')
  } finally {
    vi.useRealTimers()
  }
})

test('a network blip is left to the browser to retry', () => {
  const { source } = setup()
  act(() => source().onerror?.())
  expect(FakeSource.all.length).toBe(1)
})
