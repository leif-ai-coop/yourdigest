import type { LucideIcon } from 'lucide-react'
import { GripVertical, ChevronUp, ChevronDown, ArrowUpRight } from 'lucide-react'

/** Reusable dashboard card with native drag&drop (desktop) + up/down (mobile)
 *  reorder, optional click-to-navigate, and column span. Pattern lifted from
 *  HealthPage and generalized for the Dashboard. */
export function DashboardCard({
  title, icon: Icon, children, cardId, span = '1',
  dragging, onDragStart, onDragOver, onDrop, onDragEnd,
  onMoveUp, onMoveDown, isFirst, isLast, onOpen,
}: {
  title: string
  icon: LucideIcon
  children: React.ReactNode
  cardId: string
  span?: '1' | '2'
  dragging: string | null
  onDragStart: (id: string) => void
  onDragOver: (e: React.DragEvent, id: string) => void
  onDrop: (id: string) => void
  onDragEnd: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  isFirst: boolean
  isLast: boolean
  onOpen?: () => void
}) {
  const stop = (e: React.MouseEvent) => e.stopPropagation()
  return (
    <div
      className={`bg-card border rounded-lg p-4 transition-opacity ${dragging === cardId ? 'opacity-40 border-primary' : 'border-border'} ${span === '2' ? 'md:col-span-2' : ''} ${onOpen ? 'cursor-pointer hover:border-primary/50' : ''} group`}
      onDragOver={(e) => { e.preventDefault(); onDragOver(e, cardId) }}
      onDrop={() => onDrop(cardId)}
      onClick={onOpen}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          draggable
          onClick={stop}
          onDragStart={() => onDragStart(cardId)}
          onDragEnd={onDragEnd}
          className="hidden md:block cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
        >
          <GripVertical className="w-4 h-4" />
        </div>
        <Icon className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-medium text-foreground flex-1">{title}</h3>
        {onOpen && <ArrowUpRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />}
        <div className="flex md:hidden gap-0.5" onClick={stop}>
          <button onClick={onMoveUp} disabled={isFirst} className="p-0.5 text-muted-foreground disabled:opacity-20">
            <ChevronUp className="w-4 h-4" />
          </button>
          <button onClick={onMoveDown} disabled={isLast} className="p-0.5 text-muted-foreground disabled:opacity-20">
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>
      </div>
      {children}
    </div>
  )
}
