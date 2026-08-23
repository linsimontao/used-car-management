# 中古車在庫管理システム —— 要件・設計仕様書

> バージョン：v1.1（MVP）
> 最終更新：2026-08-23
> 本ドキュメントが実装の唯一の根拠となる。全ての決定事項はヒアリングにて確認済み。未確定事項は末尾の「未解決事項」に集約する。

---

## 1. プロジェクト概要

中古車販売店のフロント担当者向けの**在庫車両管理システム**。接客中の担当者が**口語による入力**（MVP 段階ではテキスト入力欄。音声認識結果の入力口を想定）で以下の3点を行う。

1. 特定の車両の**現在のステータスと詳細情報を照会する**
2. 車両を**「商談中」としてロックする**（他の担当者が同じ車両を別の顧客に同時に提案するのを防ぐ）
3. **ロック解除**、または車両を**売却済**にする

本システムの中核的価値は**排他制御**にある。一台の車両は同一時刻に一人の担当者しか占有できず、その占有には明確な所有者・明確な有効期限・完全な追跡記録が伴う。

### 1.1 設計原則

- **書き込み操作は必ず明示的な確認を経る**：LLM の解析結果が直接 DB 書き込みを引き起こすことは絶対にない。必ずユーザーの二次確認を挟む。
- **LLM は理解のみを担当し、実行はしない**：LLM の唯一の責務は自然言語を構造化された意図に変換すること。業務ルール・権限検証・同時実行制御は全てバックエンドの決定的なコードが担う。
- **データベースが真実である**：「画面表示とデータベースが一致しない」中間状態は存在しない。期限切れロックは遅延書き戻しにより即座に永続化される。
- **REST API は非音声の入口からも再利用可能とする**：一覧画面、将来のモバイル対応、外部連携は全て同一の業務 API を通す。

### 1.2 実装規約（言語ポリシー）

本プロジェクトは日本のお客様向けである。以下を全工程で徹底する。

| 対象 | 言語 |
|---|---|
| 仕様書・設計ドキュメント | **日本語** |
| コード内コメント・docstring | **日本語** |
| テストデータ・seed データ | **日本語**（実在感のある日本の中古車・日本人の氏名） |
| エンドユーザー向けエラーメッセージ・UI 文言 | **日本語** |
| 変数名・関数名・DB カラム名・API パス | **英語**（スネークケース） |
| ステータス等の enum 値（DB 格納値） | **英語**（`IN_STOCK` 等。表示ラベルは日本語） |
| コミットメッセージ | 日本語 |

> **enum を英語にする理由**：DB に格納する値と画面に表示する文言を分離する。表示文言の変更が DB マイグレーションを引き起こさず、`event_type` 等の既存の英語 enum とも一貫する。

---

## 2. 技術スタック

| レイヤー | 選定 | 備考 |
|---|---|---|
| バックエンド | FastAPI | OpenAPI ドキュメントと Pydantic バリデーションが標準装備 |
| データベース | SQLite | 単一ファイル配置。WAL モードを必須で有効化する |
| ORM | SQLAlchemy 2.x | または sqlite3 直叩き。ただし条件付き UPDATE の意味論を保証すること |
| LLM | Google Gemini（`gemini-3.5-flash`） | モデル ID は環境変数 `GEMINI_MODEL` で設定 |
| フロントエンド | React 18 + Vite + TypeScript | SPA。SSR なし |
| フロント状態管理 | React 標準の state + fetch ラッパー | MVP 規模では Redux/Zustand は不要 |
| テスト | pytest（バックエンド） | フロントエンドの自動テストは MVP 対象外 |
| タイムゾーン | 保存は UTC、表示は `Asia/Tokyo` | DB には ISO8601 UTC 文字列で格納 |

> **モデル ID に関する注記**：`gemini-3.5-flash` という ID は未検証である。実装時はモデル名を環境変数 `GEMINI_MODEL` に置き、デフォルト値を `gemini-3.5-flash` とすること。API が「モデルが存在しない」を返した場合、環境変数の変更のみで対応でき、コード修正は不要とする。

---

## 3. ロールと認証

**簡易的な認証モデル**を採用する。ユーザーテーブルを事前投入し、担当者は始業時に一度だけ自分を選択する。フロントエンドはこれを `localStorage` に保持し、以降の全リクエストに `X-User-Id` ヘッダーを付与する。

| ロール | 権限 |
|---|---|
| `staff`（フロント担当・営業） | 全車両の照会／在庫車両のロック／**自分がロックした**車両の解除／売却済への変更 |
| `admin`（管理者） | `staff` の全権限に加えて：**他人がロックした**車両の強制解除／「売却済」の取り消し |

**これは意図的な簡略化であり、セキュリティ対策ではない。** MVP ではパスワード・JWT・トークン有効期限のいずれも実装しない。`user_id` を知っていれば誰でもなりすませる。本格的な認証は対象外とする（§12.2 参照）。

---

## 4. データモデル

### 4.1 `users`（担当者）

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,              -- 表示名（例：「佐藤 健」）
    role        TEXT    NOT NULL CHECK (role IN ('staff', 'admin')),
    active      INTEGER NOT NULL DEFAULT 1,    -- 退職者は 0 にして選択肢から除外
    created_at  TEXT    NOT NULL               -- ISO8601 UTC
);
```

### 4.2 `vehicles`（車両）

```sql
CREATE TABLE vehicles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_no        TEXT    NOT NULL UNIQUE,  -- 管理番号：3〜4桁の数字文字列（例："101" / "2035"）
    maker             TEXT    NOT NULL,         -- メーカー（例：「トヨタ」）
    model             TEXT    NOT NULL,         -- 車種・グレード（例：「プリウス S ツーリング」）
    model_year        INTEGER NOT NULL,         -- 初度登録年（西暦）
    mileage_km        INTEGER NOT NULL,         -- 走行距離（km）
    color             TEXT    NOT NULL,         -- ボディカラー（例：「パールホワイト」）
    displacement      TEXT,                     -- 排気量（例：「1.8L」）
    price_yen         INTEGER NOT NULL,         -- 車両本体価格（円・整数）
    shaken_expires_on TEXT,                     -- 車検満了日（YYYY-MM-DD）。車検切れは NULL
    repair_history    INTEGER NOT NULL DEFAULT 0, -- 修復歴の有無（0=なし / 1=あり）
    location          TEXT,                     -- 展示場所（例：「A区画 3番」）
    remark            TEXT,                     -- 車両状態に関する備考

    status            TEXT    NOT NULL DEFAULT 'IN_STOCK'
                              CHECK (status IN ('IN_STOCK', 'NEGOTIATING', 'SOLD')),

    -- ロック情報：3フィールドは常に運命を共にする（全て NULL か、全て値を持つか）
    locked_by         INTEGER REFERENCES users(id),
    locked_at         TEXT,                     -- ISO8601 UTC
    lock_expires_at   TEXT,                     -- ISO8601 UTC
    lock_note         TEXT,                     -- ロック時のメモ（例：「田中様と商談中」）

    version           INTEGER NOT NULL DEFAULT 1,  -- 楽観ロックのバージョン番号。書き込みごとに +1
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE INDEX idx_vehicles_status ON vehicles(status);
```

**ステータスの表示ラベル対応表：**

| DB 格納値 | 画面表示 | バッジ色 |
|---|---|---|
| `IN_STOCK` | 在庫 | 緑 |
| `NEGOTIATING` | 商談中 | オレンジ |
| `SOLD` | 売却済 | グレー |

**実装が保証すべき不変条件：**

- `status = 'NEGOTIATING'` ⟺ `locked_by IS NOT NULL AND lock_expires_at IS NOT NULL`
- `status = 'IN_STOCK'` または `'SOLD'` ⟹ ロック関連3フィールドは全て `NULL`
- `version` は**全ての**書き込み成功後に 1 増加する（遅延期限切れ書き戻しを含む）

> **ロック情報を独立した `locks` テーブルにせず `vehicles` に内包する理由**：ロックとステータスは同一の不変条件の裏表であり、テーブルを分けると両者が不整合になる余地が生まれる。また単一の条件付き UPDATE 文で両者を同時に制約できなくなる。

### 4.3 `vehicle_events`（イベント履歴）

追記のみの不変ログ。全てのステータス変更を記録し、事後の追跡根拠と LLM 精度改善のための実データを兼ねる。

```sql
CREATE TABLE vehicle_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id     INTEGER NOT NULL REFERENCES vehicles(id),
    event_type     TEXT    NOT NULL,   -- 下記の列挙を参照
    actor_id       INTEGER REFERENCES users(id),  -- システムによる自動処理の場合は NULL
    from_status    TEXT,
    to_status      TEXT,
    raw_text       TEXT,               -- ユーザーの入力原文。非音声経路からの操作では NULL
    parsed_intent  TEXT,               -- LLM が返した JSON 全体の文字列。非音声経路では NULL
    detail         TEXT,               -- 補足（強制解除の理由、メモの内容など）
    created_at     TEXT    NOT NULL
);

CREATE INDEX idx_events_vehicle ON vehicle_events(vehicle_id, created_at);
```

**`event_type` の列挙：**

| 値 | 発生タイミング | actor |
|---|---|---|
| `locked` | ロック成功 | 操作者 |
| `unlocked` | ロック所有者による自主的な解除 | 操作者 |
| `force_unlocked` | 管理者が他人のロックを強制解除 | 管理者 |
| `lock_expired` | 遅延チェックで期限切れを検出 | NULL |
| `lock_renewed` | ロック所有者による延長 | 操作者 |
| `sold` | 売却済にした | 操作者 |
| `unsold` | 管理者が売却済を取り消した | 管理者 |

---

## 5. ステートマシンとロック規則

### 5.1 状態遷移表

```
                   lock                       sold
       ┌───────────────────────┐   ┌───────────────────────┐
       │                       ▼   │                       ▼
  ┌──────────┐          ┌─────────────┐            ┌────────┐
  │ IN_STOCK │          │ NEGOTIATING │            │  SOLD  │
  │  (在庫)  │          │  (商談中)   │            │(売却済)│
  └──────────┘          └─────────────┘            └────────┘
       ▲                       │   ▲                    │
       │ unlock / force_unlock │   │ renew（自己ループ）  │
       └───────────────────────┘   └──                   │
       ▲                                                 │
       │            unsold（admin のみ）                   │
       └─────────────────────────────────────────────────┘
```

| # | 遷移 | 操作 | 前提条件 | 許可ロール |
|---|---|---|---|---|
| T1 | 在庫 → 商談中 | `lock` | 現在「在庫」であること | staff / admin |
| T2 | 商談中 → 在庫 | `unlock` | 実行者 == `locked_by` | ロック所有者本人 |
| T3 | 商談中 → 在庫 | `force_unlock` | 実行者 != `locked_by` | **admin のみ** |
| T4 | 商談中 → 在庫 | `lock_expired` | `now > lock_expires_at` | システム（遅延実行） |
| T5 | 商談中 → 商談中 | `renew` | 実行者 == `locked_by` | ロック所有者本人 |
| T6 | 在庫 → 売却済 | `sold` | 現在「在庫」であること | staff / admin |
| T7 | 商談中 → 売却済 | `sold` | 実行者 == `locked_by`、または実行者が admin | ロック所有者 / admin |
| T8 | 売却済 → 在庫 | `unsold` | —— | **admin のみ** |

**上記に列挙されていない遷移は全て拒否**し、`409 INVALID_TRANSITION` を返す。

### 5.2 ロックの詳細な意味論

- **ロックの所有権**：`locked_by` がロックした担当者を指す。ロックは**排他的**である。
- **既定の有効期間**：2時間。環境変数 `LOCK_TTL_MINUTES` で設定し、既定値は `120`。
- **ロック時のパラメータ**：必須なのは `vehicle_no` のみ。`note`（メモ）は任意。顧客氏名や電話番号の入力は求めない。
- **有効期間はユーザーが指定できない**：MVP ではグローバル設定の TTL に一本化する。「1時間だけ押さえて」といった発話中の時間指定はパラメータとして解析しない。
- **延長（T5）**：ロック所有者が自分がロック済みの車両に対して再度 `lock` を呼んだ場合、エラーではなく**延長**として扱う。`lock_expires_at` を `now + TTL` にリセットし、`lock_renewed` イベントを記録する。これにより `lock` API は同一ユーザーに対して自然に冪等となる。
- **他人がロック済みの車両への `lock`**：拒否し `409 VEHICLE_LOCKED` を返す。レスポンスには**ロック所有者の氏名**と**残り時間**を含め、フロントで担当者同士がその場で調整できるようにする。

### 5.3 期限切れの遅延書き戻し機構

バックグラウンドの定期タスクは使用しない。代わりに以下を徹底する。

> **車両を読み書きする全ての入口で、業務ロジックに入る前に `expire_if_needed(vehicle_no)` を実行する。**

`expire_if_needed` の挙動：

```
BEGIN IMMEDIATE;
  SELECT status, lock_expires_at, version FROM vehicles WHERE vehicle_no = ?;
  IF status == 'NEGOTIATING' AND now() > lock_expires_at:
      UPDATE vehicles
         SET status = 'IN_STOCK',
             locked_by = NULL, locked_at = NULL,
             lock_expires_at = NULL, lock_note = NULL,
             version = version + 1,
             updated_at = now()
       WHERE vehicle_no = ? AND version = <読み取った version>;
      INSERT INTO vehicle_events (event_type = 'lock_expired', actor_id = NULL, ...);
COMMIT;
```

**一覧 API にも同様に適用する**：まず一括で期限切れ処理（`UPDATE ... WHERE status='NEGOTIATING' AND lock_expires_at < now()`、対象行に対して `lock_expired` イベントを一括 INSERT）を行ってから検索を実行する。

これにより**いかなる時点でもデータベースを直接 `SELECT` した結果が正しい現在状態である**ことが保証され、アプリケーション層で「実効ステータス」を再計算するという概念が不要になる。

---

## 6. 同時実行制御

### 6.1 想定シナリオ

2名の営業担当が同一秒に `101` 番の車両へ `lock` を実行する。ちょうど一人だけが成功し、もう一人には明確な失敗理由が返り、失敗した側が成功した側のロックを上書きしてはならない。

### 6.2 方式：条件付き UPDATE + `version` による楽観ロック

**全ての書き込み API のリクエストボディに、クライアントが保持する `version` を必須で含める。**

```sql
UPDATE vehicles
   SET status = 'NEGOTIATING',
       locked_by = :user_id,
       locked_at = :now,
       lock_expires_at = :now_plus_ttl,
       lock_note = :note,
       version = version + 1,
       updated_at = :now
 WHERE vehicle_no = :no
   AND status = 'IN_STOCK'          -- ステータスの前提条件
   AND version = :client_version;   -- 楽観ロック
```

**`rowcount` で結果を判定する：**

- `rowcount == 1` → 成功。更新後の車両（新しい `version` を含む）を返す
- `rowcount == 0` → 失敗。**該当行を再読み込み**して原因を特定し、的確なエラーを返す：
  - 行が存在しない → `404 VEHICLE_NOT_FOUND`
  - `status == 'NEGOTIATING'` → `409 VEHICLE_LOCKED`（ロック所有者名・残り分数を付与）
  - `status == 'SOLD'` → `409 INVALID_TRANSITION`
  - `status == 'IN_STOCK'` だが `version` が変化 → `409 VERSION_CONFLICT`（「車両情報が更新されました。再度照会してください」）

### 6.3 SQLite に対する要件

- 接続確立時に `PRAGMA journal_mode=WAL;` と `PRAGMA foreign_keys=ON;` を実行する
- `PRAGMA busy_timeout=3000;`（ミリ秒）を設定し、瞬間的な書き込み競合が即座に `database is locked` を投げないようにする
- **全ての書き込みトランザクションは `BEGIN IMMEDIATE` を使用する**。トランザクション開始時点で書き込みロックを取得し、SQLite の遅延ロック昇格に起因するデッドロックを回避する
- 単一の条件付き UPDATE 文は原子的であり、`version` の検査と書き込みの間に競合の窓は存在しない

### 6.4 `version` の入手経路

標準的な音声フローでは `version` は自然に手に入る（詳細は §9.2）。ユーザーが発話 → フロントが `/api/parse` を呼ぶ → フロントが `GET /api/vehicles/{no}` を呼んで確認カードを描画（この時点で `version` を取得）→ ユーザーが確認ボタンを押す → フロントがその `version` を添えて書き込み API を呼ぶ。一覧画面も同様に各行がそれぞれの `version` を保持する。

---

## 7. LLM による意図解析

### 7.1 責務の境界

LLM が行うのは**ただ一つ**、自然言語のテキストを構造化された単一意図の JSON に変換することのみ。DB の読み書き、権限判定、ユーザー向け返答文の生成は一切行わない。

### 7.2 意図の列挙

| `intent` | 意味 | 必須パラメータ | 任意パラメータ | 書き込み |
|---|---|---|---|---|
| `query_vehicle` | 車両のステータス・詳細照会 | `vehicle_no` | —— | いいえ |
| `lock_vehicle` | 商談中にしてロック | `vehicle_no` | `note` | はい |
| `unlock_vehicle` | ロック解除 | `vehicle_no` | —— | はい |
| `mark_sold` | 売却済にする | `vehicle_no` | —— | はい |
| `unknown` | 認識不能 | —— | —— | —— |

**各意図の代表的な発話例（プロンプトにも同等の例を含めること）：**

| 意図 | 発話例 |
|---|---|
| `query_vehicle` | 「101番の車、今どうなってる？」「イチマルイチの状態教えて」「2035番って空いてる？」 |
| `lock_vehicle` | 「101番を商談中にして」「イチマルイチ、押さえといて」「101番、田中様と商談中です」 |
| `unlock_vehicle` | 「101番のロック外して」「イチマルイチ、商談終わりました」「101番戻していいよ」 |
| `mark_sold` | 「101番、売れました」「イチマルイチ、ご成約です」「101番を売却済にして」 |

### 7.3 出力の契約

```jsonc
{
  "intent": "lock_vehicle",       // 上表の列挙のいずれか。必須
  "params": {
    "vehicle_no": "101",          // 正規化済みの3〜4桁の数字文字列。特定できない場合は null
    "note": "田中様と商談中"        // 無ければ null
  },
  "confidence": 0.93,             // 0.0 〜 1.0
  "missing": [],                  // 欠落している必須パラメータ名の配列（例：["vehicle_no"]）
  "raw_text": "101番、田中様と商談中です"  // バックエンドが埋め戻す。LLM の出力ではない
}
```

**実装要件：** Gemini の **function calling / structured output** を用いてスキーマを強制すること。「JSON で出力せよ」と指示して文字列を自前でパースする方式は採らない。それでもスキーマに合致しない応答が返った場合は、バックエンドで例外を捕捉し `{"intent": "unknown", "confidence": 0.0}` にフォールバックする。

### 7.4 入力の契約

```jsonc
// POST /api/parse
{
  "text": "イチマルイチ番の車を商談中にして"
}
```

### 7.5 車両番号の正規化

**本システムの音声経路において最も誤りが生じやすい箇所であり、バックエンドで決定的な後処理を必ず行う。LLM のみに依存してはならない。**

LLM が返した `vehicle_no` に対し、以下を順に適用する。

1. 全角文字を半角に変換する
2. 漢数字をアラビア数字に変換する：`〇零一二三四五六七八九` → `0123456789`
3. 数字の読み（ひらがな・カタカナ）を変換する：
   - `まる` / `マル` / `ぜろ` / `ゼロ` / `れい` → `0`
   - `いち` / `イチ` → `1`、`に` / `ニ` → `2`、`さん` / `サン` → `3`
   - `よん` / `し` / `ヨン` → `4`、`ご` / `ゴ` → `5`、`ろく` / `ロク` → `6`
   - `なな` / `しち` / `ナナ` → `7`、`はち` / `ハチ` → `8`、`きゅう` / `く` / `キュウ` → `9`
4. 位取りの読みを解決する：`ひゃく`／`百` = 100 の位、`せん`／`千` = 1000 の位
   （例：「ひゃくいちばん」→ `101`、「にせんさんじゅうご」→ `2035`）
5. 接尾辞・指示語を除去する：`番`、`番の車`、`号車`、`番車`、`の車`、`あの車`、`この車`、`さん`
6. 残った非数字文字と空白を全て除去する
7. 結果が3〜4桁の数字であることを検証する。満たさない場合は `vehicle_no` を `null` とし、`missing` に `"vehicle_no"` を追加する

変換例：`「イチマルイチ番の車」` → `101`／`「一〇一番」` → `101`／`「二〇三五」` → `2035`／`「ひゃくいちばん」` → `101`

**正規化後も DB 上の存在確認は別途必要**：`/api/parse` は解析のみを担い DB を参照しない。存在確認は後続の `GET /api/vehicles/{no}` が `404` を返すことで表現される。

### 7.6 確信度と二次確認の方針

| 状況 | システムの挙動 |
|---|---|
| `intent` が照会系 | **即座に実行**。フロントは直ちに `GET /api/vehicles/{no}` を呼びカードを描画する |
| `intent` が書き込み系（lock / unlock / sold） | **確信度に関わらず必ず確認ダイアログを表示**。ダイアログには車両カード＋実行しようとしている操作＋「実行 / キャンセル」を表示する |
| `missing` が空でない | 不足項目をフロントで提示し、言い直しを促す。確認フローには進まない |
| `confidence < 0.6` | 「うまく聞き取れませんでした。次の操作でよろしいですか？」と表示し、解析結果を編集可能な形で提示する |
| `intent == "unknown"` | 「認識できませんでした。言い方を変えてお試しください」と表示し、対応している言い回しの例を提示する |

> **書き込み操作を無条件に二次確認とする理由**：車両のロックは同僚の業務に直接影響する。誤操作のコストは、クリックが一回増えるコストを明確に上回る。確信度のしきい値は提示文言の調整にのみ用い、確認の省略には用いない。

### 7.7 System Prompt に含めるべき要素

- 役割設定：中古車販売店のフロント業務アシスタント。店舗スタッフの指示を理解することのみを担当する
- 意図の列挙と、それぞれに対する実際の口語表現例（各意図につき3〜5例。§7.2 の表を使用）
- 車両番号は3〜4桁の数字であり、漢数字やカタカナの読みで発話される可能性があること
- 明確な指示：**言及されていない番号を推測してはならない**。番号が不確かな場合は `vehicle_no` に `null` を入れること
- 明確な指示：一度に認識する意図は一つのみ。複数の用件が述べられた場合は最初の一件のみを取ること
- `confidence` の意味：「意図＋パラメータ」全体に対する確信の度合いであること

### 7.8 パーサーの抽象化とテスト

`parse(text: str) -> ParseResult` という単一メソッドを持つインターフェース `IntentParser` を定義し、実装を2つ用意する。

- `GeminiParser`：本番実装。Gemini API を呼び出す
- `MockParser`：キーワードと正規表現による決定的な実装。**バックエンドの全単体テストで使用する**

テストは依存性注入により `MockParser` を用いる。したがって**バックエンドのテストスイートはネットワーク接続を必要とせず、トークンを消費せず、結果が安定する**。`GeminiParser` の実通信は独立したマーカー付きの結合テスト（`pytest -m integration`）でのみ検証し、既定では skip する。

---

## 8. API 設計

共通プレフィックスは `/api`。全リクエストに `X-User-Id: <int>` ヘッダーを付与する（`/api/users` を除く）。全ての日時フィールドは ISO8601 UTC 文字列とする。

### 8.1 担当者

**`GET /api/users`** —— 選択可能な担当者一覧（ログイン画面用）

```jsonc
// 200
[{ "id": 1, "name": "佐藤 健",   "role": "staff" },
 { "id": 2, "name": "鈴木 美咲", "role": "staff" },
 { "id": 3, "name": "田中 隆",   "role": "admin" }]
```

### 8.2 解析

**`POST /api/parse`** —— 解析のみ。副作用は一切発生しない

```jsonc
// リクエスト
{ "text": "101番の車、今どうなってる？" }

// 200
{
  "intent": "query_vehicle",
  "params": { "vehicle_no": "101", "note": null },
  "confidence": 0.97,
  "missing": [],
  "raw_text": "101番の車、今どうなってる？"
}
```

### 8.3 車両の照会

**`GET /api/vehicles`** —— 一覧

クエリパラメータ：`status`（任意。`IN_STOCK|NEGOTIATING|SOLD`）、`q`（任意。管理番号・メーカー・車種の部分一致）、`page`（既定 1）、`page_size`（既定 50）

```jsonc
// 200
{
  "total": 28,
  "items": [ /* 車両オブジェクト。構造は下記と同一 */ ]
}
```

**`GET /api/vehicles/{vehicle_no}`** —— 単一車両の詳細

```jsonc
// 200
{
  "vehicle_no": "101",
  "maker": "トヨタ", "model": "プリウス S ツーリングセレクション",
  "model_year": 2019, "mileage_km": 62000, "color": "パールホワイト",
  "displacement": "1.8L", "price_yen": 1780000,
  "shaken_expires_on": "2027-03-31", "repair_history": false,
  "location": "A区画 3番", "remark": "禁煙車・ワンオーナー・記録簿あり",
  "status": "NEGOTIATING",
  "status_label": "商談中",
  "lock": {
    "locked_by": { "id": 1, "name": "佐藤 健" },
    "locked_at": "2026-08-23T02:10:00Z",
    "expires_at": "2026-08-23T04:10:00Z",
    "remaining_minutes": 87,
    "note": "田中様と商談中"
  },
  "version": 7,
  "updated_at": "2026-08-23T02:10:00Z"
}
// status が IN_STOCK / SOLD の場合、lock は null
// 404 車両が存在しない
```

### 8.4 車両の書き込み操作

全ての書き込み API は成功時に**更新後の車両オブジェクト全体**（構造は `GET /api/vehicles/{no}` と同一）を返す。フロントはこれをそのまま使ってカードを再描画でき、追加のリクエストは不要である。

**`POST /api/vehicles/{vehicle_no}/lock`**

```jsonc
// リクエスト
{ "version": 7, "note": "田中様と商談中", "raw_text": "...", "parsed_intent": "..." }
// note / raw_text / parsed_intent は任意。後2者はイベント履歴への記録に使う
```

- 「在庫」の場合 → ロック（T1）。イベント `locked`
- 「商談中」かつ `locked_by == 実行者` → 延長（T5）。イベント `lock_renewed`
- 「商談中」かつ他人のロック → `409 VEHICLE_LOCKED`
- 「売却済」の場合 → `409 INVALID_TRANSITION`

**`POST /api/vehicles/{vehicle_no}/unlock`**

```jsonc
{ "version": 7, "force": false, "reason": null, "raw_text": "...", "parsed_intent": "..." }
```

- 実行者 == `locked_by` → 解除（T2）。イベント `unlocked`
- 実行者 != `locked_by` かつ実行者が `admin` かつ `force == true` → 強制解除（T3）。イベント `force_unlocked`、`detail` に `reason` を記録
- 実行者 != `locked_by` かつ admin でない → `403 NOT_LOCK_OWNER`（レスポンスにロック所有者名を付与）
- 実行者が admin だが `force != true` → `409 FORCE_REQUIRED`（フロント側で「他人のロックを強制解除する」旨の明示的な確認を求める）
- 車両が「商談中」でない → `409 INVALID_TRANSITION`

**`POST /api/vehicles/{vehicle_no}/sold`**

```jsonc
{ "version": 7, "raw_text": "...", "parsed_intent": "..." }
```

- 「在庫」→「売却済」（T6）
- 「商談中」かつ実行者 == `locked_by`、または実行者が admin →「売却済」（T7）。同時にロック関連フィールドをクリアする
- 「商談中」かつ他人のロックで、実行者が admin でない → `403 NOT_LOCK_OWNER`
- 既に「売却済」→ `409 INVALID_TRANSITION`

**`POST /api/vehicles/{vehicle_no}/unsold`** —— 売却済の取り消し（T8。admin のみ）

```jsonc
{ "version": 9, "reason": "ローン審査が通らなかったため" }
```

- admin でない → `403 FORBIDDEN`
- 車両が「売却済」でない → `409 INVALID_TRANSITION`
- 成功 → ステータスを「在庫」に戻し、イベント `unsold` を記録

### 8.5 イベント履歴

**`GET /api/vehicles/{vehicle_no}/events`** —— 車両のイベントタイムライン

バックエンドは MVP 段階からこの API を提供する（データは書き込み経路で既に蓄積される）。フロントエンドは MVP では対応画面を作らない。

```jsonc
// 200
[{
  "id": 42, "event_type": "locked",
  "actor": { "id": 1, "name": "佐藤 健" },
  "from_status": "IN_STOCK", "to_status": "NEGOTIATING",
  "raw_text": "101番を商談中にして",
  "detail": null,
  "created_at": "2026-08-23T02:10:00Z"
}]
```

### 8.6 エラーレスポンスの形式

2xx 以外のレスポンスは全て以下の構造に統一する。`message` は**そのまま画面に表示できる日本語**とする。

```jsonc
{
  "code": "VEHICLE_LOCKED",
  "message": "101番の車両は佐藤 健さんが商談中です（残り87分）",
  "detail": { "locked_by_name": "佐藤 健", "remaining_minutes": 87 }
}
```

| HTTP | `code` | 意味 | 表示メッセージ例 |
|---|---|---|---|
| 400 | `INVALID_VEHICLE_NO` | 管理番号の形式が不正（3〜4桁の数字でない） | 「管理番号は3〜4桁の数字で指定してください」 |
| 401 | `NO_IDENTITY` | `X-User-Id` が無いか不正 | 「担当者が選択されていません。再度ログインしてください」 |
| 403 | `NOT_LOCK_OWNER` | ロック所有者以外による解除・売却 | 「この車両は佐藤 健さんが商談中のため操作できません」 |
| 403 | `FORBIDDEN` | ロール権限が不足（admin 以外による unsold 等） | 「この操作には管理者権限が必要です」 |
| 404 | `VEHICLE_NOT_FOUND` | 管理番号が存在しない | 「101番の車両は登録されていません」 |
| 409 | `VEHICLE_LOCKED` | 他の担当者がロック済み | 「101番の車両は佐藤 健さんが商談中です（残り87分）」 |
| 409 | `VERSION_CONFLICT` | 楽観ロックのバージョン不一致 | 「車両情報が更新されました。もう一度お試しください」 |
| 409 | `INVALID_TRANSITION` | 現在のステータスでは許可されない遷移 | 「売却済の車両は商談中にできません」 |
| 409 | `FORCE_REQUIRED` | 管理者が他人のロックを解除するには明示的な `force=true` が必要 | 「佐藤 健さんのロックを強制的に解除しますか？」 |
| 502 | `LLM_UNAVAILABLE` | Gemini の呼び出しに失敗 | 「音声解析サービスに接続できません。しばらくしてお試しください」 |

---

## 9. フロントエンド設計

### 9.1 画面構成

| 画面 | ルート | 内容 |
|---|---|---|
| 担当者選択 | `/login` | `/api/users` を取得し、選択後 `localStorage` に保存してコンソールへ遷移 |
| 音声コンソール | `/` | 主画面：入力欄＋解析結果＋車両カード＋確認ダイアログ |
| 車両一覧 | `/vehicles` | 全在庫の一覧表。ステータスで絞り込み可能。各行にステータスバッジとロック所有者を表示 |

### 9.2 音声コンソールの標準インタラクションフロー

```
ユーザーがテキストを入力（MVP：テキスト欄。将来：音声認識結果を同じ欄に流し込む）
        │
        ▼
POST /api/parse ──────────────► { intent, params, confidence, missing }
        │
        ├─ intent == unknown または missing が非空 ──► 言い直しを促して終了
        │
        ▼
GET /api/vehicles/{no}  ──────► 車両オブジェクト（version を含む）
        │
        ├─ 404 ──► 「101番の車両は登録されていません」と表示して終了
        │
        ▼
車両カードを描画
        │
        ├─ intent == query_vehicle ──► ここで完了。カードが最終結果
        │
        ▼（書き込み操作の場合）
確認ダイアログ：「101番の車両を商談中にします。よろしいですか？」
        │
        ├─ キャンセル ──► 終了。書き込みリクエストは一切発生しない
        │
        ▼ 実行
POST /api/vehicles/{no}/lock  { version, note, raw_text, parsed_intent }
        │
        ├─ 2xx ──► 返却された車両オブジェクトでカードを更新し、完了メッセージを表示
        └─ 409 VERSION_CONFLICT ──► 自動で再 GET し、確認ダイアログを再表示（最大1回）
        └─ その他 4xx ──► message フィールドをそのまま表示
```

**要点：**

- **二次確認の状態はフロントエンドのメモリ上にのみ保持する**。バックエンドは pending セッションテーブルを持たず、期限切れの掃除も不要。
- `version` は確認前の `GET` が提供する。これにより「ユーザーが見たものが、ユーザーが承認したバージョンそのものである」ことが自然に保証される。
- `VERSION_CONFLICT` の場合は自動で1回だけリトライする（再 GET ＋ 確認の再表示）。大半のケースは他の担当者が直前に延長やメモ更新を行っただけで、車両自体はまだロック可能なためである。

### 9.3 結果の提示方法

バックエンドが返すのは**構造化データのみ**。フロントエンドが固定テンプレートで描画する。**LLM による返答文の生成は行わない**。数値の復唱ミスを避けるためと、余計な呼び出し遅延を発生させないためである。

車両カードで目立たせるべき情報：

- 管理番号（最大の文字サイズ）
- ステータスバッジ：`在庫`（緑）／`商談中`（オレンジ）／`売却済`（グレー）
- 「商談中」の場合：ロック所有者の氏名＋残り分数＋メモ
- メーカー・車種・年式、走行距離、ボディカラー、排気量、車両本体価格、車検満了日、修復歴の有無、展示場所、備考

### 9.4 車両一覧画面

- 表の列：管理番号／メーカー・車種／年式／走行距離／価格／ステータス／ロック所有者／残り時間
- 上部のステータス絞り込み：すべて／在庫／商談中／売却済
- **行内に書き込み操作のボタンは置かない**。MVP における全ての書き込み操作は音声コンソールからのみ発行させ、全てのイベントに `raw_text` が残ることを保証する

---

## 10. ディレクトリ構成

```
backend/
  app/
    main.py              # FastAPI アプリのエントリポイント、CORS、例外ハンドラ
    config.py            # 環境変数：GEMINI_API_KEY / GEMINI_MODEL / LOCK_TTL_MINUTES / DB_PATH
    db.py                # 接続管理、WAL/PRAGMA 設定、BEGIN IMMEDIATE トランザクション
    models.py            # SQLAlchemy モデル
    schemas.py           # Pydantic のリクエスト／レスポンスモデル
    deps.py              # X-User-Id の解決、現在ユーザーの依存、ロール検証
    errors.py            # 業務例外クラスと HTTP エラーコードの対応（日本語メッセージを含む）
    routers/
      users.py
      parse.py
      vehicles.py
    services/
      vehicle_service.py # 照会、一覧、expire_if_needed
      lock_service.py    # lock / unlock / sold / unsold の条件付き UPDATE と状態遷移検証
      event_service.py   # イベントの記録
    llm/
      base.py            # IntentParser インターフェースと ParseResult データクラス
      gemini.py          # GeminiParser
      mock.py            # MockParser（テスト用および API キー未設定時のフォールバック）
      normalize.py       # 車両番号の正規化（漢数字・カナ読み・接尾辞処理）
      prompt.py          # System prompt と function schema
    seed.py              # 日本の中古車30台＋担当者3名の投入
  tests/
    test_normalize.py    # 番号正規化の境界値テスト
    test_state_machine.py# T1〜T8 の全遷移と拒否されるべき遷移
    test_concurrency.py  # 同時 lock で成功が1件のみであること
    test_expiry.py       # 遅延期限切れ書き戻し
    test_api.py          # E2E API テスト（MockParser を注入）
  requirements.txt

frontend/
  src/
    api/client.ts        # fetch ラッパー、X-User-Id 付与、エラーコードから日本語文言への対応
    pages/
      Login.tsx
      Console.tsx        # 音声コンソール
      VehicleList.tsx
    components/
      VehicleCard.tsx
      StatusBadge.tsx
      ConfirmDialog.tsx
    types.ts
  package.json
  vite.config.ts
```

---

## 11. テスト戦略

バックエンドのテストは以下を必ず網羅する。全て `MockParser` を使用し、ネットワーク接続を行わない。

| テストケース | 要点 |
|---|---|
| 番号の正規化 | 漢数字、カナ読み（イチマルイチ）、全角、「番の車」等の接尾辞、位取り読み、不正入力で null |
| 状態遷移 | T1〜T8 を1件ずつ検証。拒否される各遷移が正しい `code` を返すこと |
| ロックの所有権 | 所有者以外の解除が拒否されること。管理者の `force=true` が成功し `force_unlocked` イベントが記録されること |
| 延長の冪等性 | 所有者による再 lock で `lock_expires_at` が延長され、イベントが `locked` ではなく `lock_renewed` であること |
| 遅延期限切れ | 期限切れロックを作った上で GET を呼ぶと、DB 上の `status` が `IN_STOCK` になり `lock_expired` イベントが存在すること |
| 同時実行 | スレッドプールから N 件の lock を同時発行し、ちょうど1件が 200、N-1 件が 409 であること |
| 楽観ロック | 古い `version` で書き込み API を呼ぶと `409 VERSION_CONFLICT` になること |
| イベントの完全性 | 書き込み成功のたびに `vehicle_events` がちょうど1件増え、`raw_text` が正しく保存されていること |

### 11.1 テストデータ・seed データの方針

**実在感のある日本のデータを用いる。** 中国語や英語のダミーデータは使用しない。

- **担当者**：`佐藤 健`（staff）、`鈴木 美咲`（staff）、`田中 隆`（admin）
- **車両**：国産中古車を中心に約30台。メーカーは トヨタ／日産／ホンダ／スズキ／ダイハツ／マツダ／スバル。車種は プリウス、アクア、ノート、セレナ、フィット、N-BOX、ワゴンR、タント、デミオ、フォレスター 等
- **価格**：日本の中古車相場に沿った円建ての金額（例：軽自動車 `598,000`、コンパクトカー `1,280,000`、ミニバン `2,180,000`）
- **走行距離**：`12,000`〜`120,000` km の範囲で現実的に分散させる
- **ボディカラー**：`パールホワイト`、`ブラックマイカ`、`シルバーメタリック` 等
- **車検満了日**：一部は期限切れ（NULL）、大半は今後1〜2年内の日付
- **備考**：`禁煙車・ワンオーナー`、`記録簿あり`、`ドライブレコーダー装備`、`修復歴あり（左フロント）` 等
- **展示場所**：`A区画 3番`、`B区画 12番`、`屋内展示場` 等
- **テスト内の発話文字列**：全て日本語の口語表現とする（「イチマルイチ番、押さえといて」等）

---

## 12. スコープ

### 12.1 MVP に含むもの

- 照会／ロック／解除／売却済 の4本の主要フロー。二次確認、楽観ロックの競合処理、期限切れの遅延解放、イベント履歴を含む
- 車両一覧画面（ステータス絞り込み付き）
- `/api/parse` の Gemini 接続。番号正規化と `MockParser` フォールバックを含む
- seed スクリプトによる日本の中古車 約30台と担当者3名（うち管理者1名）の投入
- 管理者による強制解除と売却済取り消しの**バックエンド機能**（`unlock force=true`、`unsold`）

### 12.2 明確に対象外とするもの

以下は MVP の範囲外だが、設計上その居場所は確保してある。

- **実際の音声入力**：STT は実装しない。コンソールのテキスト欄が音声認識結果の入力口を兼ねる。将来 Web Speech API を接続する際は、認識結果を同じ欄に流し込むだけでよく、バックエンドの改修は発生しない。
- **管理者専用画面**：強制解除と売却済取り消しは API のみ。専用の管理画面は作らない。管理者も MVP では音声コンソールから同じフローを通り、バックエンドがロールで判定する。
- **車両履歴のタイムライン画面**：`GET /api/vehicles/{no}/events` は実装済みでデータも蓄積され続けるが、フロントエンドの表示画面は作らない。
- **車両情報の登録・編集・CSV 取り込み**：データは seed スクリプト経由でのみ投入する。
- **本格的な認証**：パスワードなし、JWT なし、セッション有効期限なし。`X-User-Id` は偽装可能である。
- **一文での複数操作**：LLM の契約は単一意図であり、「101番を解除して、205番を商談中に」は最初の一件のみ処理する。
- **ロック時間のユーザー指定**：発話中の時間指定は解析せず、常にグローバル TTL を用いる。
- **LLM による返答文生成 / 音声読み上げ（TTS）**：結果は常にフロントエンドのテンプレートで描画する。
- **仕入価格・原価・粗利などの機微な項目**：DB に持たない。したがって項目レベルの権限制御も不要とする。
- **複数店舗 / マルチテナント**。

---

## 13. 設定項目

| 環境変数 | 既定値 | 説明 |
|---|---|---|
| `DB_PATH` | `./data/app.db` | SQLite ファイルのパス |
| `GEMINI_API_KEY` | なし | 未設定の場合 `/api/parse` は自動的に `MockParser` にフォールバックする |
| `GEMINI_MODEL` | `gemini-3.5-flash` | モデル ID。コード改修なしで差し替え可能 |
| `LOCK_TTL_MINUTES` | `120` | ロックの有効期間（分） |
| `LOW_CONFIDENCE_THRESHOLD` | `0.6` | この値を下回るとフロントが「うまく聞き取れませんでした」を表示する |
| `CORS_ORIGINS` | `http://localhost:5173` | フロントエンド開発サーバーのアドレス |
| `TZ_DISPLAY` | `Asia/Tokyo` | 画面表示用のタイムゾーン |

---

## 14. 未解決事項

以下は MVP の開発を妨げるものではないが、実運用の開始前に確認すべき事項である。

1. **管理番号の再利用の有無**：車両が売却された後、`101` という番号が新規入庫車に割り当てられるか。割り当てられる場合、`vehicle_no` の UNIQUE 制約を「在庫中の車両内で一意」に変更する必要があり、イベント履歴も前後2台の車両を区別できる必要がある。
2. **店舗の実際の営業時間**：現在の TTL は固定2時間である。閉店時刻をまたぐロックが実運用で問題になる場合、「毎日決まった時刻に一斉失効」という規則を追加できる。
3. **管理者による強制解除を元の所有者へ通知するか**：MVP ではイベント履歴に記録するのみで、能動的な通知は行わない。
4. **書き込み競合の実際の発生頻度**：店舗規模の拡大により `VERSION_CONFLICT` が頻発する場合、「メモの編集」など競合の弱い操作を `version` 検査の対象から除外することを検討する。
5. **車検満了日・修復歴の要否**（v1.1 で追加）：日本の中古車販売では顧客からほぼ必ず尋ねられる項目のため `shaken_expires_on` と `repair_history` を追加した。不要であれば削除してよい。
6. **敬称・呼称の表記ルール**：ロック所有者の表示を「佐藤 健さん」とするか「佐藤」とするか。現状は「さん」付けで統一している。
