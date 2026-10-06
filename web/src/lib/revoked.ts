import type { Message } from './types'

/** The red border for a message its sender deleted for everyone (the text is kept). */
export function revokedClass(
  m: Pick<Message, 'revoked_at'>,
  shape: 'bubble' | 'row' = 'bubble',
): string {
  if (!m.revoked_at) return ''
  return shape === 'bubble' ? 'border-2 border-danger' : 'ring-2 ring-inset ring-danger'
}
