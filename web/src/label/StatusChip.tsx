import type { UiStatus } from '../copy'
import { useI18n } from '../i18n'

export function StatusChip({ status, small = false }: { status: UiStatus; small?: boolean }) {
  const { t } = useI18n()
  return (
    <span className={`chip chip-${status}${small ? ' chip-sm' : ''}`} data-status={status}>
      {t.status[status]}
    </span>
  )
}
