# j-law-grep.app

日本の法令テキストを高速に全文検索する grep.app クローンの最小実装です。バックエンドは Django + OpenSearch、フロントエンドは Vite + React + Tailwind CSS で構成しています。

## リポジトリ構成

```
backend/           Django プロジェクト (search API, citation parser)
indexer/           コーパス変換・OpenSearch 投入・検証 CLI
frontend/          Vite + React UI (検索バーと結果一覧)
deploy/            Dockerfile と docker-compose 定義
scripts/           補助スクリプト (smoke_search.py など)
tests/             pytest と golden query 定義
```

## 必要要件

- Docker Desktop (Windows + PowerShell を想定)
- make
- Python 3.10 / Node.js / npm (フルコーパス投入や開発時に使用)

## クイックセットアップ

クローンからブラウザで検索できるまでの最短手順です。

### 1. サンプルコーパスで起動する (Docker のみ)

民法 1/2/90/709/710/711 条のサンプルで UI をすぐに確認したい場合はこれだけで完了します。

```powershell
git clone https://github.com/srndpty/j-law-grep.git j-law-grep
cd j-law-grep
cp .env.example .env
make up           # OpenSearch / Backend / Frontend を起動
make reindex      # サンプルコーパスを versioned index に投入し alias を切替
```

ブラウザで <http://localhost:5173> を開き、"過失" や "不法行為" を検索すればハイライト付きで結果が出ます。

### 2. フルコーパスを投入する

実データで使う場合は、e-Gov の法令 XML を変換してから投入します。フルコーパス投入はホスト側 Python から OpenSearch に投入するため、indexer の依存をホストに入れておきます。

```powershell
# 0. ホスト側に indexer/backend の依存を入れる (未実施なら)
make setup-dev

# 1. e-Gov から法令 XML をダウンロードし data/egov-xml に展開する
# https://laws.e-gov.go.jp/bulkdownload/

# 2. XML を indexer/data/*.json に変換する
python -m indexer.egov_importer --xml-dir data/egov-xml --output indexer/data

# 3. (任意) 取り込み warning のコード別件数を確認する
make warning-summary

# 4. フルコーパスを投入する (sample 用 golden は使わないので GOLDEN_FILE= で外す)
make reindex INDEX_INPUT=indexer/data GOLDEN_FILE= BULK_CHUNK=20000 BULK_MAX_MB=40
```

投入後は <http://localhost:5173> で全コーパスを検索できます。`make smoke` を実行すると `/healthz` `/readyz` `/metrics`・backend `/api/search`・frontend proxy 経由 `/api/search` の到達をまとめて確認できます。

> `indexer/data` はフルコーパス用のローカル置き場です。`.dockerignore` と `.gitignore` で Docker image / Git 管理から除外しています。

### 3. 国会会議録を取得・投入する

国会会議録は `indexer/diet_data` にローカル保存し、法令とは別 alias の `jdiet-current` に投入します。UI では検索元を `法令` / `国会` / `質問主意書` / `横断` で切り替えられます。
`国会` / `横断` では、院・会議名・発言者・日付範囲で絞り込めます。発言者は前方一致です (`山田` → `山田太郎` は拾うが `太郎` では拾わない)。

`横断` の filter は source ごとに掛かります。たとえば `横断` で発言者だけ指定すると、法令側は素通しで横断結果に残り、国会・質問主意書側だけ発言者で絞られます。逆に法令名で絞ると他は素通しで残ります。「両方に同じ条件を AND したい」用途ではなく「片側を絞っても反対側は消えない」挙動です。

```powershell
# 小さく試す
make diet-fetch DIET_ARGS="--all-houses --session-from 212 --session-to 212 --limit-discovered 20"
make reindex-diet

# 日付範囲で取得する (例: 直近1年)
make diet-fetch-range DIET_FROM_DATE=2025-06-09 DIET_UNTIL_DATE=2026-06-09
make reindex-diet

# バックフィル (第1回から指定回まで、衆参両院)
# DIET_SESSION_TO は最新回次を確認して置き換える (212 は例)
make diet-fetch-backfill DIET_SESSION_TO=212
make reindex-diet
```

`diet-fetch-backfill` は第1回から指定回までを対象にする全量取得用です。通常の確認や部分投入では `diet-fetch-range` か `diet-fetch DIET_ARGS="..."` で日付・回次・件数を絞ってください。件数で止めたいときは基準を選べます: `--limit-discovered N` は「N 件発見したら停止」(skip も含む)、`--limit-fetched N` は「N 件新規取得したら停止」(skip は数えない) です。`--limit-meetings` は `--limit-fetched` の旧称 (fetched 基準) です。既存ファイルが多い状態で「小さく試す」なら、想定外に先まで走らない `--limit-discovered` を使ってください。取得は途中停止を前提に、既存 JSON と `_fetch_state.json` を見て取得済み `issueID` を skip します。失敗した会議は `_fetch_errors.jsonl` に記録し、次回実行時に再試行できます。再取得したい場合は `DIET_ARGS="--overwrite"` を追加してください。公式 API への負荷を避けるため、既定でリクエスト間隔は 3 秒です (`DIET_DELAY_SECONDS=...` で調整)。

`reindex-diet` は既定で bulk request を4並列にします。OpenSearchのCPU・メモリが逼迫する場合は `DIET_BULK_WORKERS=2`、直列へ戻す場合は `DIET_BULK_WORKERS=1` を指定してください。chunk件数とrequest上限も `BULK_CHUNK` / `BULK_MAX_MB` で調整できます。

> `indexer/diet_data` はローカル専用です。`.gitkeep` 以外は Git 管理から除外しています。

### 4. 質問主意書を取得・投入する

質問主意書とその答弁書 (閣議決定を経た政府の公式見解) は `indexer/shuisho_data` にローカル保存し、`jshuisho-current` alias に投入します。UI の検索元タブに `質問主意書` が増え、院・会期・提出者・日付範囲・質問/答弁の別で絞り込めます。

公式 API が無いため衆参両院サイトの HTML をスクレイピングします。URL は会期と提出番号で決まるので、会期一覧ページから提出番号とリンクを拾い、質問本文・答弁本文をそれぞれ取得します。

```powershell
# 小さく試す (第217回の衆議院だけ、20件で打ち切り)
make shuisho-fetch SHUISHO_HOUSE=shugiin SHUISHO_SESSION_FROM=217 SHUISHO_SESSION_TO=217 SHUISHO_ARGS="--limit-discovered 20"
make reindex-shuisho

# 直近数会期 (衆参両院)
make shuisho-fetch SHUISHO_SESSION_FROM=213 SHUISHO_SESSION_TO=221
make reindex-shuisho

# バックフィル (既定は第100回から第221回まで)
make shuisho-fetch-backfill SHUISHO_SESSION_TO=221
make reindex-shuisho
```

会期は機械的に走査し、一覧ページが存在しない会期 (404) は `_fetch_errors.jsonl` に記録してスキップします。HTML が公開されているのは概ね衆議院が第150回以降、参議院が第100回以降です。取得済みの件は既存 JSON と `_fetch_state.json` を見て skip するので、途中停止しても再開できます。答弁が未受理の件は質問本文だけを保存し、答弁受理後に `SHUISHO_ARGS="--overwrite"` で取り直せます。HTML 本文が一切取れない件 (PDF のみ等) は `_fetch_errors.jsonl` に記録して次へ進みます — PDF からのテキスト抽出は行いません。両院サイトへの負荷を避けるため、既定でリクエスト間隔は 3 秒です (`SHUISHO_DELAY_SECONDS=...` で調整)。

検索レコードは段落単位です。`content_long` の 8KB 上限による部分文字列検索の取りこぼしを避けるためで、質問本文・答弁本文の各段落が 1 ヒットになります。件名は法令名と同じ field に載るので、`質問主意書` タブでも件名の前方一致が効きます。

> `indexer/shuisho_data` はローカル専用です。`.gitkeep` 以外は Git 管理から除外しています。

## frontend と backend の接続

frontend は `/api/search` への相対パスで検索 API を呼び、backend への到達は Vite の proxy が担います。

- 開発 (`npm run dev`, port 5173): `vite.config.ts` の `server.proxy` が `/api` を `VITE_BACKEND_URL` (既定 `http://backend:8000`) に転送します。Docker を使わずローカルで backend を起動している場合は `VITE_BACKEND_URL=http://localhost:8000` を指定してください。
- Docker / preview (`vite preview`, container 4173 → host 5173): `vite.config.ts` の `preview.proxy` が同じく `/api` を backend に転送します。`vite preview` は `server.proxy` を参照しないため `preview.proxy` が必須です。

docker-compose では frontend コンテナに `VITE_BACKEND_URL=http://backend:8000` を渡し `5173:4173` を公開しているため、ブラウザは <http://localhost:5173> を開けば proxy 経由で backend に届きます。

## reindex の仕組み (versioned index + alias 切替)

`make reindex` は常に `<alias>-vYYYYMMDDHHMMSS` のような versioned index を新規作成し、次を順に検証してから alias を atomically 切り替える**標準導線**です。mapping や analyzer を変えた場合もこの導線で安全に入れ替えられます。

1. 投入件数 == manifest 件数
2. OpenSearch 件数 == manifest 件数
3. 新 index の mapping schema version 一致
4. golden query (新 index に対して実行。`GOLDEN_FILE=` で無効化可能)

いずれかが失敗すると alias は切り替わらず、作りかけの index は削除され、既存 index が生かされます (安全なロールバック)。`switch_alias()` 自体も切替直前に target index の存在と schema を再確認します。manifest や reindex レポート (manifest / golden report / index stats) は `tmp/reindex-reports/<timestamp>/` に保存します。

alias は既定で `.env` の `OPENSEARCH_INDEX` (既定 `jlaw-current`) を使い、`INDEX_ALIAS=...` で一時的に上書きできます。`reindex-versioned` は後方互換のための別名です。

- **サンプルコーパス**は Docker 内 backend から投入します: `make reindex` (既定 `INDEX_INPUT=indexer/sample_corpus`、golden は `sample.json`)。
- **フルコーパス**はホスト側 Python から `http://127.0.0.1:9200` に投入します。環境により `localhost` が遅いことがあるため indexer / validator 用の `HOST_OPENSEARCH` 既定を `127.0.0.1` にしています (backend 系 smoke は `localhost:8000` 固定で影響を受けません)。
- フルコーパスに sample 用 golden を指定するとエラーになります。`GOLDEN_FILE=` で外すか、コーパスに合わせた golden file を指定してください。

> 上書き型 (非 versioned) の高速 reindex は開発専用として `make reindex-dev` に残しています。alias 切替も世代管理も行わず削除済み文書が残り得るため本番運用には使いません。

### bulk / heap チューニング

bulk 投入の既定は Windows ローカル開発での安定性を優先し `BULK_CHUNK=200` / `BULK_MAX_MB=2` です (request size は `BULK_MAX_MB` で自動分割)。フルコーパスを高速に投入する場合は上のクイックセットアップのように `BULK_CHUNK=20000 BULK_MAX_MB=40` 程度まで引き上げます。

OpenSearch の shards は既定 4、heap は `.env` の `OPENSEARCH_JAVA_OPTS` で決まります (`.env.example` は `-Xms2g -Xmx2g`、compose は `.env` が無い場合 1GB にフォールバック)。heap を変えた場合は OpenSearch コンテナを再作成して反映してください。

#### 用途別の `.env` 推奨値

`.env.example` は dev 既定値です。用途に応じて `.env` で次を変更します (`.env.example` のコメントにも記載)。変更後は OpenSearch コンテナを再作成して反映してください。

| キー | dev (既定) | full-corpus | prod-like |
| --- | --- | --- | --- |
| `DJANGO_DEBUG` | `1` | `0` | `0` |
| `OPENSEARCH_NUMBER_OF_SHARDS` | `1`〜`4` | `4` | `4` |
| `OPENSEARCH_TIMEOUT_SECONDS` | `30` | `60` | `30` |
| `OPENSEARCH_REQUEST_TIMEOUT_SECONDS` | `10` | `30` | `10` |
| `OPENSEARCH_BULK_TIMEOUT_SECONDS` | `60` | `180` | `120` |
| `OPENSEARCH_BULK_MAX_BYTES` | `41943040` | `41943040` | `41943040` |
| `OPENSEARCH_JAVA_OPTS` | `-Xms1g -Xmx1g`〜`-Xms2g -Xmx2g` | `-Xms2g -Xmx2g` | `-Xms2g -Xmx2g` |
| `REINDEX_TOKEN` | (空) | 要設定 | 要設定 |

### schema version

`OPENSEARCH_SCHEMA_VERSION=8` では質問主意書用の `shuisho_kind` / `shuisho_number` field を追加しています (version 7 で国会会議録用の `source_type` / `speaker` / `meeting_name` などを追加済み)。古い schema version の index は `/readyz` と `ensure_index` で不一致として扱われるため、`make reindex` / `make reindex-diet` / `make reindex-shuisho` をそれぞれ回して alias を切り替えてください。

## e-Gov XML からの取り込み

`python -m indexer.egov_importer --xml-dir data/egov-xml --output indexer/data` は XML を `indexer/data/*.json` に変換し、`manifest.json` と `import_warnings.jsonl` を生成します。

- 条番号は `Article` の `Num` 属性から取得します。枝番条文 (`Num="2_2"` = 第2条の2) は `2の2` に正規化します。
- 変換後の各法令は `indexer/schema.py` の `validate_law_document` で構造検証し、問題を warning として JSONL 1 行ずつ出力します (変換は中断しません)。warning コード: `empty_law_id` / `empty_law_name` / `empty_law` / `missing_article_no` / `short_content` / `unsupported_item_no` / `appendix_skipped`。
- 条ではなく項だけで構成された附則 (`SupplProvision`) は `附則1-1` のような pseudo article として変換します (複数ある場合は `附則2-1` のように区別)。別表 (`AppdxTable` 等) も `別表1` のように本文を flatten して検索対象に入れます。様式・図など未変換領域は `appendix_skipped` として記録します。
- 変換後はコード別の集計が標準エラーに出ます。フルコーパス投入前に `make warning-summary` でコード別件数と影響法令を確認できます。

### 法令名と別名 (alias)

`law` フィルタと citation の法令名は `law_name` だけでなく `law_aliases` にも一致します。例えば民法に別名 `民法典` を登録しておくと `民法典709条` や `law=民法典` が `民法` にヒットします (`law_aliases` はコーパス JSON の各法令に配列で持たせます)。

## 検索モード（検索仕様の契約）

各モードの意味は `tests/golden_queries/sample.json` の golden query で契約として固定しています。analyzer / mapping / クエリ組み立てを変えるときは、この golden を必ず通します (標準導線の `make reindex` が alias 切替前に新 index へ golden を実行)。

- `auto`: 引用だけ (`民法709条`) なら citation、引用 + 残余語 (`民法709条 損害`) なら citation filter 付き全文検索、引用がなければ通常の全文フレーズ検索。
- `literal`: 入力文字列を 1 つのフレーズとして検索。引用だけの入力 (`民法90条`) は citation として解決します。
- `keyword`: 入力語を AND 条件として広めに検索。`content` / `content.keywordish` / `caption` / `heading` を対象にします。
- `boolean`: `A B` (AND)、`A | B` / `A OR B` (OR グループ)、`-C` (除外)、`"..."` (フレーズ) を解釈。
- `citation`: `民法709条` のような条文位置検索。漢数字 (`第七百九条`) と全角数字 (`７０９`) を正規化します。枝番条文 (`第2条の2` / `2の2条` / `2_2条`) も `2の2` として解決します。
- `regex`: 制限付き正規表現検索。自動検索では実行しません。OpenSearch の term-level regexp を使うため、grep の行単位 regex と完全に同じ挙動ではありません。

### literal フレーズ長の制限

content の ngram analyzer は `max_gram=15` ですが、schema version 5 以降は長文 literal 用の `content_long` keyword field も併用します。空白を含まない 15 文字超の検索語は `content` の phrase query と `content_long` の wildcard query のどちらかに一致すれば候補になり、`content_long` 一致は ranking でも boost します。`content_long` は ngram を作らず、indexer が先頭 8KB に切り詰めるため、フルコーパス reindex 時の index 負荷と OpenSearch の keyword term サイズ制限を避けます。非常に長い項の後半にだけ現れる長文完全一致は、通常の `content` phrase 側に依存します。

`content_long` の `*...*` は keyword field に対する substring scan のため通常検索より重くなります。フルコーパスで tail latency を抑えるため、検索語長が `MAX_LONG_LITERAL_WILDCARD_LENGTH` (既定 200 文字) を超える場合は wildcard を組み立てず `content` phrase 側のみで検索します (この長さ帯では後半のみの完全一致は取りこぼし得ます)。

## Golden query

検索品質の回帰確認として golden query を使います。各ケースは `query` / `mode` / `filters` と、`expected_top` (先頭ヒット一致)・`expected_contains` (いずれかのヒットが一致)・`not_expected_contains` (どのヒットも一致しない) で記述します。期待値は文字列 (ヒット JSON に部分一致) か `{"law_name": "民法", "article_no": "709"}` のようなフィールド一致を取れます。

```json
{
  "query": "民法709条 損害",
  "mode": "auto",
  "expected_contains": [{ "article_no": "709" }, "損害"]
}
```

- `tests/golden_queries/sample.json`: サンプルコーパス (民法 1/2/90/709/710/711条) に対する citation・literal・boolean・law alias・除外条件など約 30 ケース。
- `tests/golden_queries/full_corpus.json`: 枝番条文 (`民事訴訟法3条の2`)、長文 literal、代表法令の citation、boolean 除外条件を含むフルコーパス向け。

```powershell
make golden                                                  # live alias に対して実行
make bench-search GOLDEN_FILE=tests/golden_queries/full_corpus.json   # latency / hit count を記録
```

`make golden` は live alias に対して実行します。標準導線の `make reindex` は alias 切替前に新 index へ同じ golden を流すため、analyzer や mapping を壊す変更は alias が切り替わる前に検出できます。ローカルの投入対象がフルコーパスでない場合は、その corpus に対応する別ファイルを `GOLDEN_FILE=...` で指定してください。`make bench-search` の結果は `tmp/search_bench.jsonl` と `tmp/search_bench.md` に出力されます。

## API の制限とエラー

`POST /api/search` には以下の防御を入れています。

- `size`: 1〜100 (既定 20)。
- `page`: 1〜10000。さらに `(page-1)*size + size`（深さ）が `10000`（OpenSearch の `index.max_result_window`）を超える場合は `400` で拒否します。深いページングは将来 `search_after` / cursor に置き換える前提です。
- `q`: 最大 500 文字 (regex モードは 120 文字)。
- OpenSearch への接続不能・タイムアウト (`opensearchpy.ConnectionError`) は `500` ではなく `503` を返し、body に `detail` と `request_id` を含めます。
- バリデーションエラーは DRF 形式の JSON (`{"<field>": ["..."]}` または `{"detail": "..."}`) を返します。frontend はこの detail を解析して表示します。
- すべての response に `X-Request-ID` ヘッダが付きます。frontend は検索設定パネルと Debug パネルに `request_id` を表示するので、エラー報告時に紐付けられます。

`GET /api/laws/{law_id}` は法令全体、`GET /api/laws/{law_id}?article=709` は該当条だけを返します。`context` を指定する場合は `0〜50` に制限しています。

## 運用 (smoke / health / index 管理)

### smoke テスト

```powershell
make smoke   # health-smoke -> api-smoke -> frontend-smoke
```

- `make api-smoke`: backend の `/api/search` に全文キーワード "損害" を投げ、最初のヒットと総件数を表示します。リクエスト本文は `scripts/smoke_search.py` 内で組み立てるため、Windows コンソール codepage (cp932) による日本語クエリの文字化けを受けません。
- `make frontend-smoke`: frontend の `http://localhost:5173/api/search` 経由で同じ検索を行い、proxy → backend の到達を確認します。
- `make smoke`: 上記に `health-smoke` を加え、`make up` 後にブラウザ検索が確実に動く構成かを一発で確認します。

### health / metrics

```powershell
make health-smoke
```

- `/healthz`: Django process の生存確認
- `/readyz`: OpenSearch、concrete index の存在、mapping schema version、count API の疎通確認
- `/metrics`: HTTP request count / 5xx count / latency sum (値は process-local。multi worker 構成では worker ごとの値)

各 response には `X-Request-ID` が付与され、リクエストログは JSON 1 行で標準出力に出ます。

### index validation / 世代管理

```powershell
make validate-index INDEX_ALIAS=jlaw-current MANIFEST=indexer/data/manifest.json
make index-report
make cleanup-indices
make rollback-index TO_INDEX=jlaw-current-v20260605000000
```

`validate-index` は alias が指す index の件数が manifest と一致するかを確認します。`cleanup-indices` は既定で dry-run です。実削除する場合は `make cleanup-indices INDEX_ALIAS=jdiet-current KEEP=1 FORCE=1` のように `FORCE=1` を付けてください (alias が指している index は削除対象外で、`KEEP` は alias 以外の残す世代数です)。

> Docker Desktop (WSL2) では index を削除してもホストの空き容量はすぐに増えません。`docker_data.vhdx` は自動拡張されるが自動縮小しないためです。ホストに返すには Docker を止めて仮想ディスクを compact する必要があります (`wsl --shutdown` 後に管理者権限の diskpart で `select vdisk file="...\docker_data.vhdx"` → `attach vdisk readonly` → `compact vdisk` → `detach vdisk`)。compact しなくても空いた領域は Docker 内で再利用されるため、次回の reindex で vhdx がさらに膨らむことはありません。

## 開発

品質ゲート用に backend は Ruff / mypy / pytest-cov / pre-commit、frontend は ESLint / Prettier / TypeScript / Vitest を使います。

**フル品質ゲートは `make check` (手動) と CI で担保します。** pre-commit はコミット時間を短く保つため Ruff (lint/format) と frontend-check のみの軽量構成で、mypy / pytest は含みません。提出前や大きな変更後は必ず `make check` を実行してください。CI (`.github/workflows/ci.yml`) では backend (ruff / mypy / pytest)、OpenSearch integration、frontend (lint / typecheck / test / build) をすべて実行します。

```powershell
make setup-dev        # pip install -r requirements-dev.txt + frontend npm ci
make setup-dev-uv     # uv を使う場合
```

手動で入れる場合:

```powershell
uv pip install -r requirements-dev.txt
cd frontend; npm install; cd ..
.\.venv\Scripts\python.exe -m pre_commit install
```

確認はまとめて `make check` (フルゲート)、個別には次を使います。

```powershell
make check            # フルゲート: lint + typecheck + test + frontend-check
make lint
make typecheck
make test
make coverage
make frontend-check
```

pre-commit は軽量 hook (Ruff + frontend-check) のみです。`make check` の代わりにはならないので注意してください。

```powershell
.\.venv\Scripts\python.exe -m pre_commit run --all-files   # 軽量 hook のみ (mypy / pytest は含まない)
```

### frontend test on Windows sandbox

Windows の制限付き sandbox では Vite/Vitest の config load 時に `spawn EPERM` が出る場合があります。その場合は権限付きの PowerShell で `Set-Location frontend; npm run test` または `npm run check` を実行してください。

## 将来拡張メモ

- OpenSearch のアナライザ設定を `search/open_search_client.py` で一元管理しているため、`analysis-kuromoji` プラグインへの切替が容易です。compose は現時点では 2.9.0 を維持しています。3.x 系へ上げる場合は analyzer / highlight / alias switch の integration test を先に通してください。
- コーパスは `manifest.json` の digest と件数で追跡し、法令本文は必要に応じて外部ディレクトリへ切り離します。
- analyzer や mapping を変える場合は標準導線の `make reindex` (versioned + golden ゲート + alias 切替) を使います。
