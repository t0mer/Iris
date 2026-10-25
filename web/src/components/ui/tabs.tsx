import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '../../lib/cn'
import { useLanguage } from '../../lib/i18n'

export function Tabs(props: TabsPrimitive.TabsProps) {
  const { dir } = useLanguage()
  return <TabsPrimitive.Root dir={dir} {...props} />
}

export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return <TabsPrimitive.List className={cn('flex gap-1 overflow-x-auto', className)} {...props} />
}

export function TabsTrigger({ className, ...props }: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'min-h-10 shrink-0 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-primary-soft data-[state=active]:text-primary',
        className,
      )}
      {...props}
    />
  )
}

export const TabsContent = TabsPrimitive.Content
