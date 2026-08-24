/** ステータスバッジ（SPEC §4.2）：在庫（緑）／商談中（オレンジ）／売却済（グレー）。 */

import { STATUS_LABELS, type VehicleStatus } from '../types'

const COLORS: Record<VehicleStatus, string> = {
  IN_STOCK: '#16a34a',
  NEGOTIATING: '#ea580c',
  SOLD: '#6b7280',
}

export function StatusBadge({ status }: { status: VehicleStatus }) {
  return (
    <span className="status-badge" style={{ backgroundColor: COLORS[status] }}>
      {STATUS_LABELS[status]}
    </span>
  )
}
