import { cn } from '../lib/utils'

interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'important' | 'newsletter' | 'notification' | 'spam' | 'social' | 'finance' | 'shipping'
  className?: string
}

const variantStyles: Record<string, string> = {
  default: 'bg-secondary text-secondary-foreground',
  important: 'bg-red-500/15 text-red-400 border-red-500/20',
  newsletter: 'bg-purple-500/15 text-purple-400 border-purple-500/20',
  notification: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
  spam: 'bg-orange-500/15 text-orange-400 border-orange-500/20',
  social: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/20',
  finance: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  shipping: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border border-transparent',
      variantStyles[variant] || variantStyles.default,
      className
    )}>
      {children}
    </span>
  )
}

export function CategoryBadge({ category }: { category: string }) {
  const variant = (variantStyles[category] ? category : 'default') as BadgeProps['variant']
  return <Badge variant={variant}>{category}</Badge>
}
