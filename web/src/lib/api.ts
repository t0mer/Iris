import { apiErrorMessage } from './apiErrors'
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    credentials: 'same-origin',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, apiErrorMessage(body.detail ?? res.statusText, res.status))
  }
  if (res.status === 204 || res.status === 205) return undefined as T
  return res.json() as Promise<T>
}
