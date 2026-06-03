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

`make up` は OpenSearch / Backend / Frontend を起動します。`make reindex` はサンプルコーパス (民法709条/710条) を投入する**標準導線**です。新しい versioned index を作成し、schema 検証と golden query を新 index に対して通してから `jlaw-current` alias を切り替えます。いずれかの検証が失敗した場合は alias を切り替えず、作りかけの index を削除して既存 index を生かしたままにします (安全なロールバック)。`manifest.json` も生成します。

> 補足: 上書き型 (非 versioned) の高速 reindex は開発専用として `make reindex-dev` に残しています。alias 切替も世代管理も行わず、削除済み文書が index に残り得るため本番運用には使いません。

### frontend と backend の接続

frontend は `/api/search` への相対パスで検索 API を呼びます。backend への到達は Vite の proxy が担います。

- 開発 (`npm run dev`, port 5173): `vite.config.ts` の `server.proxy` が `/api` を `VITE_BACKEND_URL` (既定 `http://backend:8000`) に転送します。Docker を使わずローカルで backend を起動している場合は `VITE_BACKEND_URL=http://localhost:8000` を指定してください。
- Docker / preview (`vite preview`, container 4173 → host 5173): `vite.config.ts` の `preview.proxy` が同じく `/api` を backend に転送します。`vite preview` は `server.proxy` を参照しないため `preview.proxy` が必須です。

docker-compose では frontend コンテナに `VITE_BACKEND_URL=http://backend:8000` を渡し、`5173:4173` を公開しています。ブラウザは `http://localhost:5173` を開けば、proxy 経由で backend に届きます。

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
2. `python -m indexer.egov_importer --xml-dir data/egov-xml --output indexer/data` で XML を `indexer/data/*.json` に変換する。変換後に `indexer/data/manifest.json` と `indexer/data/import_warnings.jsonl` を生成します。

   - 条番号は `Article` の `Num` 属性から取得します。枝番条文 (`Num="2_2"` = 第2条の2) は `2の2` に正規化します。`Num` を見ていなかった旧実装では article_no が空になり citation 検索が当たらない原因になっていました。
   - 変換後の各法令は `indexer/schema.py` の `validate_law_document` で構造検証し、問題を warning として JSONL 1 行ずつ出力します (変換は中断しません)。warning コード: `empty_law_id` / `empty_law_name` / `empty_law` / `missing_article_no` / `short_content` / `unsupported_item_no` / `lost_table` / `appendix_skipped`。
   - 別表 (`AppdxTable` 等) と、条ではなく項だけで構成された附則 (`SupplProvision`) は現状そのままでは検索対象に変換されないため、それぞれ `lost_table` / `appendix_skipped` として記録します。
   - 変換後はコード別の集計が標準エラーに出ます (例: `Wrote 2 parse warnings -> ... (appendix_skipped=1, lost_table=1)`)。フルコーパス投入前に `import_warnings.jsonl` を確認すると「入ったつもりで入っていない」事故を防げます。
3. `make reindex INDEX_INPUT=indexer/data GOLDEN_FILE=` でフルコーパスを投入する。`GOLDEN_FILE=` を空にしているのは、現状の golden (`tests/golden_queries/sample.json`) がサンプルコーパス前提で、フルコーパスでは通らないためです。フルコーパス向けの golden を整備したら `GOLDEN_FILE` に指定してゲートを有効化できます。

### 世代付きインデックスと alias 切替 (標準導線)

`make reindex` は常に versioned index を作って alias を切り替えます。mapping や analyzer を変えた場合もこの導線で安全に入れ替えられます。

```powershell
make reindex INDEX_INPUT=indexer/sample_corpus INDEX_ALIAS=jlaw-current
```

このターゲットは `jlaw-current-vYYYYMMDDHHMMSS` のような index を作成し、次を順に検証してから `jlaw-current` alias を切り替えます。

1. 投入件数 == manifest 件数
2. OpenSearch 件数 == manifest 件数
3. 新 index の mapping schema version 一致
4. golden query (新 index に対して実行。`GOLDEN_FILE=` で無効化可能)

いずれかが失敗すると alias は切り替わらず、作りかけの index は削除されます。`switch_alias()` 自体も切替直前に target index の存在と schema を再確認します。`reindex-versioned` は後方互換のため `reindex` の別名として残しています。

フルコーパスを検索したい場合は、sample ではなく次を実行します。

```powershell
make reindex INDEX_INPUT=indexer/data INDEX_ALIAS=jlaw-current GOLDEN_FILE=
```

`indexer/data` はフルコーパス用のローカル置き場です。`.dockerignore` で Docker image から除外し、`.gitignore` でも Git 管理外にしています。この場合はホスト側 Python から `http://localhost:9200` の OpenSearch に投入します。
フルコーパス投入時は Docker image build をスキップし、bulk chunk は既定で `1000` 件です。`BULK_CHUNK=20000` のように増やせますが、request size は既定 `BULK_MAX_MB=40` で自動分割します。
OpenSearch はフルコーパス向けに既定 4 shards / 2GB heap です。既存コンテナに heap 変更を反映するには OpenSearch コンテナを再作成してください。

## API スモークテスト

```
make api-smoke
```

`/api/search` に対して全文キーワード "損害" を検索し、最初のヒットと総件数を表示します。リクエスト本文は `scripts/smoke_search.py` 内で組み立てて送信するため、Windows のコンソール codepage (cp932) による日本語クエリの文字化けを受けません。

`make frontend-smoke` は frontend の `http://localhost:5173/api/search` 経由で同じ検索を行い、proxy → backend の到達を確認します。`make smoke` は `health-smoke` → `api-smoke` → `frontend-smoke` をまとめて実行し、`make up` 後にブラウザ検索が確実に動く構成かを一発で確認できます。

```powershell
make smoke
```

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

## API の制限とエラー

`POST /api/search` には以下の防御を入れています。

- `size`: 1〜100 (既定 20)。
- `page`: 1〜10000。さらに `(page-1)*size + size`（深さ）が `10000`（OpenSearch の `index.max_result_window`）を超える場合は `400` で拒否します。深いページングは将来 `search_after` / cursor に置き換える前提です。
- `q`: 最大 500 文字 (regex モードは 120 文字)。
- OpenSearch への接続不能・タイムアウト (`opensearchpy.ConnectionError`) は `500` ではなく `503` を返し、body に `detail` と `request_id` を含めます。
- バリデーションエラーは DRF 形式の JSON (`{"<field>": ["..."]}` または `{"detail": "..."}`) を返します。frontend はこの detail を解析して表示します。
- すべての response に `X-Request-ID` ヘッダが付きます。frontend は検索設定パネルと Debug パネルに `request_id` を表示するので、エラー報告時に紐付けられます。

## 将来拡張メモ

- OpenSearch のアナライザ設定を `search/open_search_client.py` で一元管理しているため、`analysis-kuromoji` プラグインへの切替が容易です。compose は現時点では 2.9.0 を維持しています。3.x 系へ上げる場合は analyzer / highlight / alias switch の integration test を先に通してください。
- コーパスは `manifest.json` の digest と件数で追跡し、法令本文は必要に応じて外部ディレクトリへ切り離します。
- analyzer や mapping を変える場合は標準導線の `make reindex` (versioned + golden ゲート + alias 切替) を使います。

## 動作確認

1. `make up` でコンテナを起動し、OpenSearch のヘルスチェックが通るまで待つ。
2. 別ターミナルで `make reindex` を実行し、"Indexed 2 records" → "Golden gate passed" → "Switched alias jlaw-current -> ..." のログを確認する。
3. `make smoke` を実行し、`/healthz` `/readyz` `/metrics`、backend の `/api/search`、frontend proxy 経由の `/api/search` がすべて通ることを確認する。
4. ブラウザで `http://localhost:5173` を開き、検索 UI から "過失" や "不法行為" を検索してハイライト付きで結果が表示されることを確認する。
