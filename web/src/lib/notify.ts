import { toast as sonnerToast } from 'sonner'
import { t } from './i18n'

function translated(args: unknown[]) {
  const [message, options, ...rest] = args
  const settings =
    options && typeof options === 'object' ? (options as Record<string, unknown>) : null
  const action = settings?.action
  return [
    typeof message === 'string' ? t(message) : message,
    settings && action && typeof action === 'object' && 'label' in action
      ? {
          ...settings,
          action: {
            ...action,
            label: typeof action.label === 'string' ? t(action.label) : action.label,
          },
        }
      : options,
    ...rest,
  ]
}

/** All toast entry points share the same translation boundary. */
export const toast = new Proxy(sonnerToast, {
  apply(target, thisArg, args) {
    return Reflect.apply(target, thisArg, translated(args))
  },
  get(target, property, receiver) {
    const value = Reflect.get(target, property, receiver)
    return typeof value === 'function' &&
      ['success', 'error', 'info', 'warning', 'message', 'loading'].includes(String(property))
      ? (...args: unknown[]) => Reflect.apply(value, target, translated(args))
      : value
  },
})
