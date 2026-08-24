# 中古車在庫管理システム

中古車販売店のフロント担当者向けの在庫車両管理システム。
要件・設計の唯一の根拠は [SPEC.md](SPEC.md)（v1.1 / MVP）。

> **現在の状態：骨組みのみ。** ディレクトリ構成・依存関係・DB マイグレーション・
> ローカル実行手順が整った段階で、業務ロジックは未実装。
> 各エンドポイントは `501 NOT_IMPLEMENTED` を返す。

## 技術スタック

| レイヤー | 選定 |
|---|---|
| バックエンド | FastAPI / Python 3.12 |
| データベース | SQLite（WAL モード必須） |
| ORM | SQLAlchemy 2.x |
| マイグレーション | Alembic |
| フロントエンド | React 18 + Vite + TypeScript |

## 必要なもの

- Python 3.12 以上
- Node.js 20 以上

## バックエンドのセットアップ

```bash
cd backend

# 仮想環境の作成（uv を使う場合）
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# uv を使わない場合
# python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 環境変数（既定値のままで動くため、変更が不要なら省略可）
cp .env.example .env

# DB の作成／マイグレーションの適用
.venv/bin/alembic upgrade head
```

### 起動

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

| URL | 内容 |
|---|---|
| http://localhost:8000/health | ヘルスチェック |
| http://localhost:8000/docs | OpenAPI ドキュメント（Swagger UI） |

### テスト

```bash
cd backend
.venv/bin/pytest
```

全テストは `MockParser` を使用し、ネットワーク接続を行わない（SPEC §7.8）。
Gemini への実通信を伴う結合テストは `-m integration` を付けた場合のみ実行される。

## フロントエンドのセットアップ

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

`/api` へのリクエストは Vite の開発サーバーが `http://localhost:8000` へプロキシする
（[vite.config.ts](frontend/vite.config.ts)）。バックエンドを先に起動しておくこと。

```bash
npm run build   # 本番ビルド（tsc の型検査を含む）
npm run lint
```

## マイグレーションの運用

```bash
cd backend

# モデル（app/models.py）を変更した後、差分から新しいリビジョンを生成する
.venv/bin/alembic revision --autogenerate -m "変更内容の説明"

# 適用 / 1 つ戻す / 履歴
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic history
```

接続先の DB は `alembic.ini` ではなく [backend/app/config.py](backend/app/config.py) の
`DB_PATH` が唯一の真実で、[backend/alembic/env.py](backend/alembic/env.py) がそれを読み取る。

## seed データ

担当者3名と日本の中古車約30台を投入する（SPEC §11.1）。**未実装。**

```bash
cd backend
.venv/bin/python -m app.seed
```

## 設定項目

環境変数は `backend/.env` に置く。既定値と意味は [.env.example](backend/.env.example)
および SPEC §13 を参照。`GEMINI_API_KEY` が未設定の場合、`/api/parse` は自動的に
`MockParser` にフォールバックする。

## ディレクトリ構成

構成は SPEC §10 に準拠する。

```
backend/
  app/
    main.py              # FastAPI エントリポイント、CORS、例外ハンドラ
    config.py            # 環境変数
    db.py                # 接続管理、WAL/PRAGMA、BEGIN IMMEDIATE
    models.py            # SQLAlchemy モデル
    schemas.py           # Pydantic のリクエスト／レスポンスモデル
    deps.py              # X-User-Id の解決、ロール検証
    errors.py            # 業務例外と HTTP エラーコードの対応
    routers/             # users / parse / vehicles
    services/            # vehicle_service / lock_service / event_service
    llm/                 # base / gemini / mock / normalize / prompt
    seed.py
  alembic/               # マイグレーション
  tests/
frontend/
  src/
    api/client.ts        # fetch ラッパー
    pages/               # Login / Console / VehicleList
    components/          # VehicleCard / StatusBadge / ConfirmDialog
    types.ts
```

## 実装方針（抜粋）

- **言語ポリシー**（SPEC §1.2）：ドキュメント・コメント・UI 文言・テストデータは日本語、
  変数名・API パス・DB の enum 値は英語。
- **書き込みは必ず二次確認を経る**（SPEC §1.1）。LLM の解析結果が直接 DB 書き込みを
  引き起こすことはない。
- **同時実行制御**（SPEC §6）：条件付き UPDATE ＋ `version` による楽観ロック。
  書き込みトランザクションは必ず `BEGIN IMMEDIATE`。
- **期限切れは遅延書き戻し**（SPEC §5.3）：バックグラウンドタスクは使わず、
  車両を読み書きする全ての入口で `expire_if_needed()` を実行する。
