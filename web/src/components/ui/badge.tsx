import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium [&_svg]:size-3',
  {
    variants: {
      tone: {
        neutral: 'bg-surface-2 text-muted-foreground',
        info: 'bg-primary-soft text-primary',
        danger: 'bg-danger-soft text-danger',
        warning: 'bg-warning-soft text-warning',
        success: 'bg-success-soft text-success',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export type Tone = NonNullable<VariantProps<typeof badgeVariants>['tone']>

export function Badge({
  className,
  tone,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
