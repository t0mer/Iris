import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import { setShowContentByDefault } from './prefs'

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api<{ username: string; role: 'admin' | 'parent' | 'watch'; id: number }>(
          '/api/auth/me',
        )
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    retry: false,
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return async () => {
    await api('/api/auth/logout', { method: 'POST' })
    setShowContentByDefault(false) // the next person at this screen starts hidden
    await qc.invalidateQueries({ queryKey: ['me'] })
  }
}
