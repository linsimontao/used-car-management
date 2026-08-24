/**
 * 音声コンソール（SPEC §9.1、§9.2、ルート /）。
 *
 * 標準フロー：
 *   テキスト入力 → POST /api/parse → GET /api/vehicles/{no} → 車両カード描画
 *   → （書き込み系なら）確認ダイアログ → POST /api/vehicles/{no}/{操作}
 *
 * VERSION_CONFLICT の場合は自動で 1 回だけ再 GET し、確認ダイアログを再表示する。
 * MVP では入力欄はテキスト。将来は音声認識結果を同じ欄に流し込む。
 */

export function Console() {
  // TODO: 骨組みのみ。実装は次段階
  return (
    <main>
      <h1>音声コンソール</h1>
    </main>
  )
}
