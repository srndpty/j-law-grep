# j-law-grep.app

日本の法令テキストを高速に全文検索する grep.app クローンの最小実装です。バックエンドは Django + OpenSearch、フロントエンドは Vite + React + Tailwind CSS で構成しています。

## リポジトリ構成

```
backend/           Django プロジェクト (search API, citation parser)
indexer/           サンプル法令コーパスと OpenSearch への投入 CLI
frontend/          Vite + React UI (検索バーと結果一覧)
deploy/            Dockerfile と docker-compose 定義
scripts/           補助スクリプト (wait-for.sh)
```

## 必要要件

- Docker Desktop (Windows + PowerShell を想定)
- make
- Python 3.10
- Node.js / npm

## セットアップ

```powershell
cp .env.example .env
make up
make reindex
```

`make up` は OpenSearch / Backend / Frontend を起動します。`make reindex` はサンプルコーパス (民法709条/710条) を OpenSearch に投入し、`manifest.json` を生成します。

### 開発用ツールのセットアップ

品質ゲート用に backend は Ruff / mypy / pytest-cov / pre-commit、frontend は ESLint / Prettier / TypeScript / Vitest を使います。

```powershell
uv pip install -r requirements-dev.txt
cd frontend
npm install
cd ..
.\.venv\Scripts\python.exe -m pre_commit install
```

通常の確認は次でまとめて実行できます。

```powershell
make check
```

個別に見る場合は次を使います。

```powershell
make lint
make typecheck
make test
make coverage
make frontend-check
.\.venv\Scripts\python.exe -m pre_commit run --all-files
```

### e-Gov XML からの取り込みと再インデックス

1. e-Gov から法令 XML をダウンロードし、任意のディレクトリ (例: `data/egov-xml`) に展開する。
2. `python -m indexer.egov_importer --xml-dir data/egov-xml --output indexer/data` で XML を `indexer/data/*.json` に変換する。変換後に `indexer/data/manifest.json` も生成されます。
3. `make reindex INDEX_INPUT=indexer/data` で変換済み JSON を OpenSearch に投入する。

### 世代付きインデックスと alias 切替

mapping や analyzer を変えた場合は、既存 index に上書きせず versioned index を作って alias を切り替えます。

```powershell
make reindex-versioned INDEX_INPUT=indexer/sample_corpus INDEX_ALIAS=jlaw-current
```

このターゲットは `jlaw-current-vYYYYMMDDHHMMSS` のような index を作成し、投入件数と OpenSearch 件数を検証してから `jlaw-current` alias を切り替えます。
フルコーパスを検索したい場合は、sample ではなく次を実行します。

```powershell
make reindex-versioned INDEX_INPUT=indexer/data INDEX_ALIAS=jlaw-current
```

`indexer/data` はフルコーパス用のローカル置き場です。`.dockerignore` で Docker image から除外し、`.gitignore` でも Git 管理外にしています。この場合はホスト側 Python から `http://localhost:9200` の OpenSearch に投入します。
フルコーパス投入時は Docker image build をスキップし、bulk chunk は既定で `1000` 件です。`BULK_CHUNK=20000` のように増やせますが、request size は既定 `BULK_MAX_MB=40` で自動分割します。
OpenSearch はフルコーパス向けに既定 4 shards / 2GB heap です。既存コンテナに heap 変更を反映するには OpenSearch コンテナを再作成してください。

## API スモークテスト

```
make api-smoke
```

`/api/search` に対して "民法 709条" を検索し、最初のヒットを表示します。

## Golden query

検索品質の最低限の回帰確認として `tests/golden_queries/sample.json` を使います。

```powershell
make golden
```

期待 top hit、期待 contains、期待 not contains を JSON で追加できます。

## Index validation

alias が指す index の件数が manifest と一致するかを確認します。

```powershell
make validate-index INDEX_ALIAS=jlaw-current MANIFEST=indexer/data/manifest.json
```

## Health / metrics

運用確認用の軽量 endpoint です。

```powershell
make health-smoke
```

- `/healthz`: Django process の生存確認
- `/readyz`: OpenSearch、concrete index の存在、mapping schema version、count API の疎通確認
- `/metrics`: HTTP request count / 5xx count / latency sum。値は process-local なので、multi worker 構成では worker ごとの値になります。

各 response には `X-Request-ID` が付与されます。リクエストログは JSON 1 行で標準出力に出ます。

## 検索モード

- `auto`: 引用だけなら citation、引用 + 残余語なら citation filter 付き全文検索、そうでなければ通常全文検索
- `literal`: 入力文字列をフレーズとして検索
- `boolean`: `A B`, `A | B`, `-C`, `"..."` を解釈
- `citation`: `民法709条` のような条文位置検索
- `regex`: 制限付き正規表現検索。自動検索では実行しません。OpenSearch の term-level regexp を使うため、grep の行単位 regex と完全に同じ挙動ではありません。

## 将来拡張メモ

- OpenSearch のアナライザ設定を `search/open_search_client.py` で一元管理しているため、`analysis-kuromoji` プラグインへの切替が容易です。compose は現時点では 2.9.0 を維持しています。3.x 系へ上げる場合は analyzer / highlight / alias switch の integration test を先に通してください。
- コーパスは `manifest.json` の digest と件数で追跡し、法令本文は必要に応じて外部ディレクトリへ切り離します。
- analyzer や mapping を変える場合は `make reindex-versioned` で alias 切替を使います。

## 動作確認

1. `make up` でコンテナを起動し、OpenSearch のヘルスチェックが通るまで待つ。
2. 別ターミナルで `make reindex` を実行し、"Indexed 2 records" のログを確認する。
3. `make api-smoke` を実行して `/api/search` から "民法 709条" にヒットすることを確認する。
4. ブラウザで `http://localhost:5173` を開き、検索 UI から "過失" や "不法行為" を検索してハイライト付きで結果が表示されることを確認する。
