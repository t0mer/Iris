import { Slot } from '@radix-ui/react-slot'
import { type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'
import { buttonVariants } from './button-variants'
import { Children } from 'react'
import { t } from '../../lib/i18n'

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export function Button({ className, variant, size, asChild, type, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...(asChild ? {} : { type: type ?? 'button' })}
      {...props}
      title={props.title ? t(props.title) : undefined}
      aria-label={props['aria-label'] ? t(props['aria-label']) : undefined}
      children={
        asChild
          ? props.children
          : Children.map(props.children, (child) => (typeof child === 'string' ? t(child) : child))
      }
    />
  )
}
