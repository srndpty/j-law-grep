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

## セットアップ

```powershell
cp .env.example .env
make up
make reindex
```

`make up` は OpenSearch / Redis / Backend / Frontend を起動します。`make reindex` はサンプルコーパス (民法709条/710条) を OpenSearch に投入します。

## API スモークテスト

```
make api-smoke
```

`/api/search` に対して "民法 709条" を検索し、最初のヒットを表示します。

## 将来拡張メモ

- OpenSearch のアナライザ設定を `search/open_search_client.py` で一元管理しているため、`analysis-kuromoji` プラグインへの切替が容易です。
- `indexer/` を拡張し e-Gov 法令 XML からの取り込みに対応する予定です。
- Redis は将来的な検索キャッシュやジョブキュー用にスタブとして構成しています。

## 動作確認

1. `make up` でコンテナを起動し、OpenSearch のヘルスチェックが通るまで待つ。
2. 別ターミナルで `make reindex` を実行し、"Indexed 2 records" のログを確認する。
3. `make api-smoke` を実行して `/api/search` から "民法 709条" にヒットすることを確認する。
4. ブラウザで `http://localhost:5173` を開き、検索 UI から "過失" や "不法行為" を検索してハイライト付きで結果が表示されることを確認する。
