import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import { cn } from '../../lib/cn'
import { useLanguage } from '../../lib/i18n'

export function DropdownMenu(props: MenuPrimitive.DropdownMenuProps) {
  const { dir } = useLanguage()
  return <MenuPrimitive.Root dir={dir} {...props} />
}
export const DropdownMenuTrigger = MenuPrimitive.Trigger
export const DropdownMenuLabel = MenuPrimitive.Label
export const DropdownMenuSeparator = ({ className }: { className?: string }) => (
  <MenuPrimitive.Separator className={cn('my-1 h-px bg-border', className)} />
)

export function DropdownMenuContent({
  className,
  ...props
}: MenuPrimitive.DropdownMenuContentProps) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        sideOffset={6}
        align="end"
        className={cn(
          'z-50 min-w-44 rounded-md border border-border bg-surface p-1 shadow-overlay',
          className,
        )}
        {...props}
      />
    </MenuPrimitive.Portal>
  )
}

export function DropdownMenuItem({ className, ...props }: MenuPrimitive.DropdownMenuItemProps) {
  return (
    <MenuPrimitive.Item
      className={cn(
        'flex min-h-10 cursor-pointer select-none items-center gap-2 rounded-sm px-3 text-sm outline-none data-[highlighted]:bg-surface-2 [&_svg]:size-4',
        className,
      )}
      {...props}
    />
  )
}
