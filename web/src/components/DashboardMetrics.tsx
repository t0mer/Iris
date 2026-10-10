import { Slot } from '@radix-ui/react-slot'
import { useId } from 'react'
import { Cpu, HardDrive, MemoryStick } from 'lucide-react'

export interface CapacityMetric {
  percentage: number | null
  usedBytes: number | null
  totalBytes: number | null
  freeBytes?: number | null
}
export interface DashboardMetricsProps {
  disk: CapacityMetric
  memory: CapacityMetric
  cpu: { percentage: number | null; cores: number | null }
  dir?: 'rtl' | 'ltr'
}

function bytes(value: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const index = value > 0 ? Math.min(5, Math.floor(Math.log(value) / Math.log(1000))) : 0
  return `${(value / 1000 ** index).toLocaleString('he-IL', { maximumFractionDigits: 1 })} ${units[index]}`
}
function percent(value: number | null) {
  return value !== null && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null
}

/** Disk is the Iris filesystem; CPU and memory describe the Iris container. */
export function DashboardMetrics({ disk, memory, cpu, dir = 'rtl' }: DashboardMetricsProps) {
  const id = useId()
  const diskPercent = percent(disk.percentage)
  const cpuPercent = percent(cpu.percentage)
  const memoryPercent = percent(memory.percentage)
  const metrics = [
    {
      key: 'disk',
      name: 'דיסק',
      value: diskPercent,
      icon: HardDrive,
      description: 'הכונן שבו Iris מאחסנת נתונים, כולל קבצים נוספים בכונן.',
      data: disk,
    },
    {
      key: 'cpu',
      name: 'מעבד',
      value: cpuPercent,
      icon: Cpu,
      description: 'שימוש במעבד של מכולת Iris. דגימה של 250 מילישניות.',
      data: null,
    },
    {
      key: 'memory',
      name: 'זיכרון',
      value: memoryPercent,
      icon: MemoryStick,
      description: 'זיכרון מכולת Iris, כולל מטמון קבצים.',
      data: memory,
    },
  ] as const
  return (
    <div dir={dir} lang="he" className="grid gap-5 lg:grid-cols-3">
      {metrics.map(({ key, name, value, icon: Icon, description, data }) => {
        const critical = value !== null && value > 90
        return (
          <article
            key={key}
            aria-labelledby={`${id}-${key}`}
            className="relative isolate flex min-w-0 flex-col overflow-hidden rounded-3xl border border-purple-200 bg-gradient-to-br from-purple-50 via-white to-indigo-50 p-6 text-purple-950 dark:border-purple-800/70 dark:from-[#211735] dark:via-[#1a1630] dark:to-indigo-950 dark:text-purple-50 shadow-[0_14px_40px_-22px_rgba(88,28,135,0.4)]"
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -end-16 -top-16 size-48 rounded-full bg-violet-200/50 blur-3xl dark:bg-violet-600/15"
            />
            <div className="relative flex items-center justify-between gap-2">
              <h3 id={`${id}-${key}`} className="flex items-center gap-2 font-semibold">
                <span className="rounded-xl border border-purple-200 bg-white/80 p-2 shadow-sm dark:border-purple-700/60 dark:bg-purple-900/50">
                  <Icon
                    aria-hidden="true"
                    className="size-4 text-purple-600 dark:text-purple-300"
                  />
                </span>
                {name}
              </h3>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs font-medium ${critical ? 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-700 dark:bg-rose-950/60 dark:text-rose-200' : 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-700 dark:bg-purple-900/50 dark:text-purple-200'}`}
              >
                {value === null ? 'לא זמין' : critical ? 'עומס גבוה' : 'תקין'}
              </span>
            </div>
            <Slot
              role={value === null ? 'img' : 'meter'}
              aria-label={`${name}: ${value === null ? 'לא זמין' : `${value}% בשימוש`}`}
              aria-valuemin={value === null ? undefined : 0}
              aria-valuemax={value === null ? undefined : 100}
              aria-valuenow={value ?? undefined}
              className="relative mt-5 flex h-48 items-center justify-center"
            >
              <div>
                {key === 'disk' && (
                  <div aria-hidden="true" className="relative h-44 w-32">
                    <div className="absolute inset-x-0 -bottom-2 h-5 rounded-[50%] bg-purple-900/20 blur-md" />
                    <div className="relative h-full overflow-hidden rounded-t-2xl rounded-b-[2.5rem] border-2 border-white bg-white/40 dark:border-purple-300/50 dark:bg-purple-200/5 shadow-[inset_0_0_0_1px_rgba(168,85,247,0.25),0_10px_25px_-10px_rgba(109,40,217,0.4)]">
                      <div
                        className={`absolute inset-x-0 bottom-0 transition-[height] duration-1000 motion-reduce:transition-none ${critical ? 'bg-gradient-to-t from-rose-800 via-rose-500 to-amber-400' : 'bg-gradient-to-t from-purple-900 via-violet-600 to-indigo-400'}`}
                        style={{ height: `${value ?? 0}%` }}
                      >
                        {(value ?? 0) > 0 && (
                          <div className="absolute inset-x-0 -top-2 h-5 rounded-[50%] border-t border-white/60 bg-white/30 motion-safe:animate-[pulse_5s_ease-in-out_infinite]" />
                        )}
                        <div className="absolute inset-0 bg-gradient-to-r from-white/20 via-transparent to-purple-950/20" />
                      </div>
                      <div className="absolute inset-y-3 start-3 w-2.5 rounded-full bg-gradient-to-b from-white/90 to-white/10" />
                      <div className="absolute inset-x-0 top-0 h-4 rounded-[50%] border border-purple-200/80 bg-white/60 dark:border-purple-300/40 dark:bg-purple-200/10" />
                    </div>
                  </div>
                )}
                {key === 'cpu' && (
                  <div
                    aria-hidden="true"
                    className="relative w-full overflow-hidden rounded-2xl border border-purple-800 bg-gradient-to-br from-purple-950 to-indigo-950 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]"
                  >
                    <div className="absolute inset-0 bg-[linear-gradient(rgba(167,139,250,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(167,139,250,0.08)_1px,transparent_1px)] bg-[size:20px_20px]" />
                    <svg viewBox="0 0 280 110" fill="none" className="relative w-full">
                      <path
                        d="M0 58H45L58 48L72 68L87 58H108L121 21L138 91L153 40L168 58H195L209 48L223 68L238 58H280"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className={`${critical ? 'text-rose-400' : 'text-violet-400'} ${value !== null ? 'motion-safe:animate-pulse' : 'opacity-25'}`}
                        style={{
                          animationDuration: `${3.5 - ((value ?? 0) / 100) * 2.7}s`,
                          filter: `drop-shadow(0 0 ${3 + (value ?? 0) / 10}px ${critical ? '#fb7185' : '#a78bfa'})`,
                        }}
                      />
                    </svg>
                    <div className="relative mt-2 flex justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-violet-300/80">
                      <span>CPU</span>
                      <span>LIVE SAMPLE</span>
                    </div>
                  </div>
                )}
                {key === 'memory' && (
                  <div
                    aria-hidden="true"
                    className="w-full rounded-2xl border border-purple-800 bg-gradient-to-br from-purple-950 to-indigo-950 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]"
                  >
                    <div className="grid grid-cols-8 gap-2">
                      {Array.from({ length: 32 }, (_, segment) => (
                        <span
                          key={segment}
                          className={`h-5 rounded border transition-colors duration-700 motion-reduce:transition-none ${value !== null && segment < Math.ceil((value / 100) * 32) ? (critical ? 'border-rose-300/60 bg-gradient-to-t from-rose-600 to-rose-300 shadow-[0_0_10px_rgba(251,113,133,0.5)]' : 'border-violet-300/60 bg-gradient-to-t from-violet-600 to-violet-300 shadow-[0_0_10px_rgba(167,139,250,0.5)]') : 'border-purple-800/60 bg-purple-900/40'}`}
                        />
                      ))}
                    </div>
                    <div className="mt-4 flex justify-between text-[10px] font-medium uppercase tracking-[0.18em] text-violet-300/80">
                      <span>RAM</span>
                      <span>32 SEGMENTS</span>
                    </div>
                  </div>
                )}
              </div>
            </Slot>
            <p className="mt-4 flex items-baseline gap-2">
              <span className="text-5xl font-semibold tracking-tight tabular-nums">
                {value === null
                  ? '—'
                  : `${value.toLocaleString('he-IL', { maximumFractionDigits: 1 })}%`}
              </span>
              <span className="text-sm text-purple-600 dark:text-purple-300">
                {value === null ? 'לא זמין' : 'בשימוש'}
              </span>
            </p>
            <div className="mt-3 min-h-12 text-sm leading-relaxed text-purple-800 dark:text-purple-200">
              {data?.usedBytes != null && data.totalBytes != null && (
                <p>
                  <bdi>{bytes(data.usedBytes)}</bdi> בשימוש מתוך <bdi>{bytes(data.totalBytes)}</bdi>
                </p>
              )}
              {data?.freeBytes != null && (
                <p className="font-medium text-indigo-700 dark:text-indigo-300">
                  <bdi>{bytes(data.freeBytes)}</bdi> פנויים
                </p>
              )}
              {key === 'cpu' && cpu.cores !== null && (
                <p>
                  <bdi>{cpu.cores.toLocaleString('he-IL', { maximumFractionDigits: 2 })}</bdi> ליבות
                  זמינות
                </p>
              )}
            </div>
            <p className="mt-auto border-t border-purple-200/60 pt-3 text-xs leading-relaxed text-purple-700 dark:border-purple-800/70 dark:text-purple-300">
              {description}
            </p>
          </article>
        )
      })}
    </div>
  )
}
