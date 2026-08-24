/** API の型定義（SPEC §8）。バックエンドの schemas.py と一対一で対応させる。 */

export type VehicleStatus = 'IN_STOCK' | 'NEGOTIATING' | 'SOLD'

/** ステータスの表示ラベル（SPEC §4.2）。DB 格納値は英語、表示は日本語。 */
export const STATUS_LABELS: Record<VehicleStatus, string> = {
  IN_STOCK: '在庫',
  NEGOTIATING: '商談中',
  SOLD: '売却済',
}

export type UserRole = 'staff' | 'admin'

export interface User {
  id: number
  name: string
  role: UserRole
}

export interface Actor {
  id: number
  name: string
}

/** 商談中の車両が持つロック情報。在庫・売却済の場合は null。 */
export interface VehicleLock {
  locked_by: Actor
  locked_at: string
  expires_at: string
  remaining_minutes: number
  note: string | null
}

/** 車両オブジェクト。書き込み API も同じ構造を返す（SPEC §8.4）。 */
export interface Vehicle {
  vehicle_no: string
  maker: string
  model: string
  model_year: number
  mileage_km: number
  color: string
  displacement: string | null
  price_yen: number
  shaken_expires_on: string | null
  repair_history: boolean
  location: string | null
  remark: string | null
  status: VehicleStatus
  status_label: string
  lock: VehicleLock | null
  version: number
  updated_at: string
}

export interface VehicleListResponse {
  total: number
  items: Vehicle[]
}

export type Intent =
  | 'query_vehicle'
  | 'lock_vehicle'
  | 'unlock_vehicle'
  | 'mark_sold'
  | 'unknown'

/** POST /api/parse のレスポンス（SPEC §7.3）。 */
export interface ParseResult {
  intent: Intent
  params: {
    vehicle_no: string | null
    note: string | null
  }
  confidence: number
  missing: string[]
  raw_text: string
}

/** エラーレスポンス（SPEC §8.6）。message はそのまま画面に表示できる日本語。 */
export interface ApiErrorBody {
  code: string
  message: string
  detail: Record<string, unknown> | null
}

/** 書き込み API に共通のリクエスト項目（SPEC §6.2）。 */
export interface WriteRequestBase {
  version: number
  raw_text?: string | null
  parsed_intent?: string | null
}
