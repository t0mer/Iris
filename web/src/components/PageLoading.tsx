import { Skeleton } from './ui/skeleton'

/** Shown inside the app shell while a page's code loads, so the sidebar and tab bar never flash away. */
export function PageLoading() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading">
      <span role="status" className="sr-only">
        Loading Iris…
      </span>
      <Skeleton className="h-9 w-56" />
      <Skeleton className="h-48" />
    </div>
  )
}
