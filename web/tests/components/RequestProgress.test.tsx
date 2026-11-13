import { act, render, screen } from '@testing-library/react'
import { RequestProgress } from '../../src/components/RequestProgress'
import { api } from '../../src/lib/api'

test('shows accessible progress for overlapping requests and clears it when both finish', async () => {
  vi.useFakeTimers()
  const completions: ((response: Response) => void)[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>((resolve) => completions.push(resolve))),
  )
  try {
    render(<RequestProgress />)
    let first!: Promise<unknown>
    let second!: Promise<unknown>
    act(() => {
      first = api('/api/settings')
      second = api('/api/review')
    })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(screen.getByRole('progressbar', { name: 'Iris is working' })).toBeInTheDocument()
    await act(async () => {
      completions[0](Response.json({}))
      await first
    })
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    await act(async () => {
      completions[1](Response.json({}))
      await second
    })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})
