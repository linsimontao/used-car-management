/**
 * fetch ラッパー（SPEC §10）。
 *
 * - 全リクエストに X-User-Id ヘッダーを付与する（/api/users を除く）
 * - 2xx 以外は ApiError として投げる。message はバックエンドが返す日本語をそのまま使う
 */

import type {
  ApiErrorBody,
  ParseResult,
  User,
  Vehicle,
  VehicleListResponse,
  WriteRequestBase,
} from '../types'

const USER_STORAGE_KEY = 'used_car.current_user'

/** バックエンドのエラーレスポンスを保持する例外。 */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/** localStorage に保持している担当者を取得する（SPEC §3）。 */
export function getCurrentUser(): User | null {
  throw new Error('骨組みのみ。実装は次段階')
}

/** 担当者選択画面で選ばれた担当者を保存する。 */
export function setCurrentUser(_user: User): void {
  throw new Error('骨組みのみ。実装は次段階')
}

/** 担当者の選択を破棄する（ログアウト相当）。 */
export function clearCurrentUser(): void {
  window.localStorage.removeItem(USER_STORAGE_KEY)
}

/** 共通の fetch 処理。X-User-Id の付与とエラー変換を行う。 */
async function request<T>(_path: string, _init?: RequestInit): Promise<T> {
  throw new Error('骨組みのみ。実装は次段階')
}

// ---------------------------------------------------------------- API

/** GET /api/users —— 選択可能な担当者一覧（X-User-Id 不要）。 */
export function fetchUsers(): Promise<User[]> {
  return request<User[]>('/api/users')
}

/** POST /api/parse —— 発話テキストの意図解析。副作用なし。 */
export function parseText(_text: string): Promise<ParseResult> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** GET /api/vehicles —— 車両一覧。 */
export function fetchVehicles(_params?: {
  status?: string
  q?: string
  page?: number
  page_size?: number
}): Promise<VehicleListResponse> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** GET /api/vehicles/{no} —— 単一車両。ここで version を取得する（SPEC §6.4）。 */
export function fetchVehicle(_vehicleNo: string): Promise<Vehicle> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** POST /api/vehicles/{no}/lock —— ロック／延長。 */
export function lockVehicle(
  _vehicleNo: string,
  _body: WriteRequestBase & { note?: string | null },
): Promise<Vehicle> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** POST /api/vehicles/{no}/unlock —— 解除／強制解除。 */
export function unlockVehicle(
  _vehicleNo: string,
  _body: WriteRequestBase & { force?: boolean; reason?: string | null },
): Promise<Vehicle> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** POST /api/vehicles/{no}/sold —— 売却済。 */
export function markSold(
  _vehicleNo: string,
  _body: WriteRequestBase,
): Promise<Vehicle> {
  throw new Error('骨組みのみ。実装は次段階')
}

/** POST /api/vehicles/{no}/unsold —— 売却済の取り消し（admin のみ）。 */
export function markUnsold(
  _vehicleNo: string,
  _body: WriteRequestBase & { reason?: string | null },
): Promise<Vehicle> {
  throw new Error('骨組みのみ。実装は次段階')
}
