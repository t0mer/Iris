// The API marks FTS matches with control characters (never HTML), so message content is
// always rendered as plain text.
const START = '\x02'
const END = '\x03'

export function Highlight({ snippet }: { snippet: string }) {
  const parts: { text: string; hit: boolean }[] = []
  let rest = snippet
  while (rest.length > 0) {
    const s = rest.indexOf(START)
    if (s === -1) {
      parts.push({ text: rest, hit: false })
      break
    }
    if (s > 0) parts.push({ text: rest.slice(0, s), hit: false })
    const e = rest.indexOf(END, s)
    const stop = e === -1 ? rest.length : e
    parts.push({ text: rest.slice(s + 1, stop), hit: true })
    rest = e === -1 ? '' : rest.slice(e + 1)
  }
  return (
    <span dir="auto">
      {parts.map((p, i) =>
        p.hit ? (
          <mark key={i} className="rounded-sm bg-mark px-0.5 text-foreground">
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </span>
  )
}
