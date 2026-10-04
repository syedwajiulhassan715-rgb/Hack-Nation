import { STATUS_WORD, type UiStatus } from '../copy'

export function StatusChip({ status, small = false }: { status: UiStatus; small?: boolean }) {
  return (
    <span className={`chip chip-${status}${small ? ' chip-sm' : ''}`} data-status={status}>
      {STATUS_WORD[status]}
    </span>
  )
}
