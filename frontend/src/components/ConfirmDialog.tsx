/**
 * 二次確認ダイアログ（SPEC §7.6、§9.2）。
 *
 * 書き込み操作（lock / unlock / sold）は確信度に関わらず必ずここを通す。
 * 確認の状態はフロントエンドのメモリ上にのみ保持し、バックエンドは関知しない。
 */

import type { ReactNode } from 'react'

export interface ConfirmDialogProps {
  open: boolean
  title: string
  children?: ReactNode
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog(_props: ConfirmDialogProps) {
  // TODO: 骨組みのみ。実装は次段階
  return null
}
