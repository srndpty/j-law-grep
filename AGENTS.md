# AGENTS.md

コーディングエージェント向けのプロジェクトガイドです。詳細な手順は [README.md](README.md) を参照してください。

## 応答ルール

- 返答は日本語で。

## プロジェクト概要

日本の法令テキストを全文検索する grep.app クローン。

- backend: Django + Django REST Framework + OpenSearch (`backend/`)
- indexer: コーパス変換・OpenSearch 投入・検証 CLI (`indexer/`)
- frontend: Vite + React + TypeScript + Tailwind CSS (`frontend/`)
- deploy: Dockerfile と docker-compose (`deploy/`)
- tests: pytest と golden query (`tests/`)

## 環境

- Windows + PowerShell + Docker Desktop を想定。シェル構文は PowerShell に合わせる (`$env:VAR`、`$null` など)。
- 起動・投入・検証はすべて `make` ターゲット経由が基本 (Makefile を一次情報とする)。
- フルコーパス投入はホスト側 Python から `http://127.0.0.1:9200` に対して行う。サンプルコーパスは Docker 内 backend から投入する。

## よく使うコマンド

```powershell
make up            # OpenSearch / Backend / Frontend を起動
make reindex       # サンプルコーパスを versioned index に投入し alias 切替 (標準導線)
make smoke         # healthz/readyz/metrics + backend/api + frontend proxy の到達確認
make check         # lint + typecheck + test + frontend-check (コミット前に通す)
```

個別: `make lint` / `make typecheck` / `make test` / `make coverage` / `make frontend-check` / `make golden`。

## コーディング規約

- Python: Ruff (line-length=100, target py310) で lint/format、mypy で型チェック。`make lint` と `make typecheck` を通すこと。
- frontend: ESLint + Prettier + `tsc --noEmit` + Vitest。`make frontend-check` を通すこと。
- pytest は既定で `integration` マーカーを除外 (`addopts = -m 'not integration'`)。
- 周囲のコードのスタイル・命名・コメント密度に合わせる。
- pre-commit は高速化のため軽量チェック (Ruff + frontend-check) のみ。mypy / pytest は含まないので、提出前・大きな変更後は必ず `make check` を実行する。フル品質ゲートは `make check` と CI (`.github/workflows/ci.yml`) で担保する。

## 変更時の注意 (契約)

- **検索仕様は golden query が契約**。analyzer / mapping / クエリ組み立てを変えたら必ず golden を通す。`tests/golden_queries/sample.json` (サンプル) と `full_corpus.json` (フルコーパス) がある。
- **インデックス入れ替えは `make reindex` (versioned + golden ゲート + alias 切替) が標準導線**。`make reindex-dev` は開発専用で本番不可。
- mapping / analyzer を変えたら `OPENSEARCH_SCHEMA_VERSION` の整合に注意 (`/readyz` と `ensure_index` が version 不一致を検出する)。
- API の制限・エラー形式 (size/page/q の上限、503 の扱い、`X-Request-ID`) を変えるときは README の「API の制限とエラー」と合わせる。

## 触らない / 注意するファイル

- `.env` はコミットしない (`.env.example` のみ追跡)。
- `indexer/data/*` と `data/egov-xml/` はローカル専用コーパス置き場 (git/Docker から除外済み)。
- `tmp/` は reindex レポート等の一時出力。
