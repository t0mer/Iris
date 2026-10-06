import { cva } from 'class-variance-authority'

export const buttonVariants = cva(
  'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:brightness-110',
        secondary: 'bg-surface-2 text-foreground hover:bg-primary-soft',
        outline: 'border border-border-strong bg-surface text-foreground hover:bg-surface-2',
        ghost: 'text-foreground hover:bg-surface-2',
        danger: 'bg-danger text-primary-foreground hover:brightness-110 dark:text-[#14122b]',
        'danger-outline': 'border border-danger/50 text-danger hover:bg-danger-soft',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'min-h-10 px-4 py-2',
        sm: 'min-h-9 px-3 text-sm',
        lg: 'min-h-11 px-5 text-base',
        icon: 'size-10',
      },
    },
    defaultVariants: { variant: 'outline', size: 'default' },
  },
)
