/**
 * 車両カード（SPEC §9.3）。
 *
 * 目立たせる情報：管理番号（最大の文字サイズ）、ステータスバッジ、
 * 商談中ならロック所有者・残り分数・メモ。
 * 表示は固定テンプレートで行い、LLM による文章生成は使わない。
 */

import type { Vehicle } from '../types'

export function VehicleCard({ vehicle }: { vehicle: Vehicle }) {
  // TODO: 骨組みのみ。詳細項目の描画は次段階
  return <div className="vehicle-card">{vehicle.vehicle_no}</div>
}
