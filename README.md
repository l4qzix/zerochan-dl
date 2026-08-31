```markdown
# zerochan-dl

[Zerochan](https://www.zerochan.net) 用の**非公式** Python クライアントライブラリです。
検索・ブラウズ・画像ダウンロードができます。Anthropic や Zerochan 運営とは無関係の、
サードパーティ製ツールです。

## 特徴

- 公式の read-only JSON API (`https://www.zerochan.net/api`) を使ったタグ検索・ブラウズ・複数タグ検索
- エントリ詳細ページを解析してフル解像度画像URL・タグ一覧・投稿者・サイズなどを取得
- 画像のストリーミングダウンロード（進捗コールバック、上書き制御つき）
- タグ検索結果の一括ダウンロード
- ページを跨いだ検索結果の自動イテレート
- 60 req/min のレート制限に配慮した自主スロットリング
- 簡易 CLI (`python -m zerochan_dl`)
- **Cloudflare 対策回避**：`curl_cffi` によるブラウザ TLS フィンガープリントの模倣（`impersonate` オプション）

## インストール

```bash
pip install -e .
# もしくは
pip install -r requirements.txt
```

**必須依存関係**: `requests`, `beautifulsoup4`

**任意（Cloudflare 回避に推奨）**:
```bash
pip install curl_cffi
```

`curl_cffi` がインストールされていれば、`impersonate` オプションで Chrome/Firefox などになりすませます。

## クイックスタート

```python
from zerochan_dl import ZerochanClient

# 通常の requests セッションを使う場合
client = ZerochanClient(username="your_zerochan_username")  # username は任意

# Cloudflare 対策を回避したい場合（curl_cffi が必要）
client = ZerochanClient(impersonate="chrome")  # Chrome になりすます

# タグ検索（生のJSON APIレスポンスをそのまま返す）
raw = client.search("Hatsune Miku", page=1, limit=10)

# IDから詳細情報を取得（フル画像URL・タグなどが確実に取れる）
entry = client.get_entry(3793685)
print(entry.full_image_url, entry.tags)

# 1件ダウンロード
client.download(entry, dest_dir="./downloads")

# タグ検索結果をまとめてダウンロード
client.download_search_results("Genshin Impact", dest_dir="./downloads/genshin", max_images=20)

# 複数タグのAND検索（両方のタグを含むエントリのみ）もOK
client.download_search_results(
    ["Genshin Impact", "Klee"], dest_dir="./downloads/genshin_klee", max_images=20
)

# ブラウズ/検索ページのサムネイル一覧を直接パースしたい場合（軽量・タグ一覧なし）
result = client.list_page("Genshin Impact", page=1)
print(f"{result.page}/{result.max_page} ページ, {len(result.items)} 件")
for item in result.items:
    print(item.id, item.full_image_url)

# タグ/カテゴリページの概要情報（名前・サムネ画像・種別など）を取得
category = client.get_category("Furina de Fontaine")
print(category.name, category.type)  # 例: "Furina de Fontaine" "character"

# サイズ/ソートは文字列でも、分かりやすいエイリアス (SizeFilter/SortBy) でも指定可能
from zerochan_dl import SizeFilter, SortBy

result = client.list_page(
    "Genshin Impact", dimension=SizeFilter.BIGGER_AND_BETTER, sort=SortBy.POPULAR
)
```

## CLI

```bash
python -m zerochan_dl search "Genshin Impact" --limit 10 --out ./downloads
python -m zerochan_dl search "Genshin Impact,Klee" --limit 10 --out ./downloads  # AND検索
python -m zerochan_dl get 3793685 --out ./downloads
```

## API 概要

| メソッド | 説明 |
|---|---|
| `browse(page, limit, sort, time_range, dimension, color)` | タグなしで全体をブラウズ（生JSON） |
| `search(tag, page, limit, strict, dimension, color)` | 単一タグ検索（生JSON） |
| `search_multi(tags, page, limit)` | 複数タグのAND検索（生JSON） |
| `get_entry_raw(entry_id)` | エントリの生JSONを取得 |
| `get_entry(entry_id)` | エントリ詳細をHTMLから解析し `ZerochanEntry` を返す（画像直リンクが確実） |
| `iter_search(tag, max_pages, limit, **kwargs)` | 検索結果を複数ページ自動で辿るジェネレータ（`tag`は文字列 or リストでAND検索） |
| `list_page(tag, page, limit, sort, dimension, color, strict)` | ブラウズ/検索ページ(HTML)のサムネイル一覧を解析し `ZerochanSearchResult` を返す |
| `iter_list(tag, max_pages, **kwargs)` | `list_page()` の結果を複数ページ自動で辿るジェネレータ（`ZerochanListItem` を yield） |
| `get_category(tag)` | タグ/カテゴリページの概要（名前・画像・種別など）を `ZerochanCategoryInfo` として取得 |
| `set_cookie(cookie_header)` | ブラウザから取得したCookieヘッダー全体を設定し、会員限定コンテンツにアクセス |
| `authorize(z_hash, z_id)` | `z_hash` / `z_id` の2つの値だけで手軽にログイン状態にする |
| `is_authenticated()` | 現在のCookie/セッションが実際にログイン状態か **サーバーに確認しに行く**（`True`/`False`/`None`） |
| `login(username, password)` | ログインフォームを実行時に解析してログインを試行（実験的） |
| `download(entry, dest_dir, filename, overwrite, progress_callback)` | 画像をダウンロード |
| `download_search_results(tag, dest_dir, max_images, strict)` | 検索結果を一括ダウンロード（`tag`は文字列 or リストでAND検索） |

## ZerochanClient コンストラクタパラメータ

| 引数 | 型 | 説明 |
|---|---|---|
| `username` | `Optional[str]` | Zerochan ユーザー名（User-Agent に使用、推奨） |
| `project_name` | `str` | プロジェクト名（User-Agent に含める） |
| `requests_per_minute` | `int` | 自主レート制限（デフォルト: 50） |
| `session` | `Optional[requests.Session]` | 既存のセッションを渡す（上級者向け） |
| `timeout` | `float` | HTTP リクエストのタイムアウト（秒） |
| `cookie` | `Optional[str]` | ブラウザからコピーした Cookie ヘッダー全体 |
| `z_hash` | `Optional[str]` | ログイン状態を保持する `z_hash` Cookie 値 |
| `z_id` | `Optional[str]` | ログイン状態を保持する `z_id` Cookie 値 |
| **`impersonate`** | `Optional[str]` | **curl_cffi で模倣するブラウザ（例: "chrome", "firefox"）。指定すると Cloudflare 対策を回避できる** |

## ボット対策（Cloudflare）の回避

Zerochan は Cloudflare などのボット対策を導入しており、通常の `requests` ライブラリでは TLS フィンガープリントがブラウザと異なるため、503 エラーでブロックされることがあります。

このライブラリは **`curl_cffi`** をサポートしており、ブラウザと同じ TLS スタックを模倣することで回避が可能です。

### 使い方

```python
from zerochan_dl import ZerochanClient

# Chrome になりすます（推奨）
client = ZerochanClient(impersonate="chrome")

# Firefox になりすます
client = ZerochanClient(impersonate="firefox")

# Safari になりすます
client = ZerochanClient(impersonate="safari")
```

**指定可能な impersonate 値**（一部）:
- `"chrome"` / `"chrome110"` / `"chrome124"` など
- `"firefox"` / `"firefox120"` など
- `"safari"` / `"safari15_5"` など

詳しくは [curl_cffi のドキュメント](https://github.com/yifeikong/curl_cffi) を参照してください。

### 注意

- `impersonate` を使うには `pip install curl_cffi` が必要です。
- 指定しなければ従来通り `requests` が使われるため、後方互換性は保たれています。
- もし 503 が依然として出る場合は、`impersonate` のバージョンを変えてみるか、ブラウザからコピーした Cookie を `set_cookie()` で設定することも有効です。

## ログインが必要な（会員限定）コンテンツへのアクセス

Zerochan には、ログインしないと閲覧できない「会員限定」のエントリがあります。
3通りの認証方法を用意しています。

### 方法1: `z_hash` / `z_id` だけを指定する（お手軽）

```python
from zerochan_dl import ZerochanClient

# 普段使っているブラウザで zerochan.net にログイン → 開発者ツール(F12) →
# Network タブ → 何かリクエストを選択 → リクエストヘッダーの "Cookie: ..." の
# 値の中から z_id と z_hash の2つだけを抜き出す（ログイン状態を保持しているのは
# 主にこの2つの Cookie）。非公式クライアント kiriharu/zerochan の
# authorize(z_hash, z_id) を参考にした簡易メソッド。
client = ZerochanClient(z_hash="xxxx", z_id="yyyy")

# もしくは後から設定
client = ZerochanClient()
client.authorize(z_hash="xxxx", z_id="yyyy")
```

### 方法2: Cookie ヘッダー全体を指定する（最も確実）

```python
from zerochan_dl import ZerochanClient

# 上と同じ手順で、今度は "Cookie: ..." の値をまるごとコピーして貼り付ける。
# z_id / z_hash 以外の Cookie も含めて送信したい場合や、方法1でうまく
# いかない場合はこちらを使う。
client = ZerochanClient(cookie="z_id=xxxx; z_hash=yyyy")

# もしくは後から設定
client = ZerochanClient()
client.set_cookie("z_id=xxxx; z_hash=yyyy")

# Cookieが実際に有効かどうかをサーバーに確認する
if client.is_authenticated():
    print("ログインできています")
else:
    print("ログインできていません（Cookieの期限切れ・コピーミスなどの可能性）")

entry = client.get_entry(1234567)  # 会員限定エントリも取得できる場合がある
```

### 方法3: ユーザー名・パスワードでログインする（実験的）

```python
client = ZerochanClient()
ok = client.login("myusername", "mypassword")
print("ログイン成功:", ok)
```

`login()` はログインページの `<form>` をその場で解析し、ユーザー名欄・パスワード欄
・隠しフィールド（CSRFトークンなど）を特定して送信します。フィールド名を
ハードコードしていないため Zerochan 側の細かな仕様変更には強い一方、フォーム構造
が大きく変わった場合や、CAPTCHA・2段階認証が有効な場合は失敗することがあります。
確実性を重視する場合は方法1（Cookie 指定）を使ってください。

ログイン状態になると、以降の `get_entry()` や `download()` などすべてのリクエストが
そのセッションで送信されます。ただし、会員限定コンテンツの公開範囲や年齢制限
コンテンツの表示設定（セーフモードなど）は Zerochan 側のアカウント設定に依存する
ため、ログインしても一部の画像が見られない場合があります。

`logged_in`（プロパティ）は「`set_cookie()`/`login()`を呼んだかどうか」を示す
ローカルなフラグに過ぎません。Cookie自体が期限切れ・無効な場合でも`True`のまま
になり得るため、実際にサーバー側で認証されているかを確認したい場合は必ず
`is_authenticated()` を呼んでください（実際にリクエストを送って判定します）。

## 重要な注意点

- **JSON API のフィールド名は未確定**です。`browse()` / `search()` / `search_multi()` /
  `get_entry_raw()` は Zerochan が返す生の JSON をそのまま返します。Zerochan 側の
  API 仕様変更に対応できるよう、まずは `print()` してレスポンス構造を確認してから
  使うことをおすすめします。
- 一方で `get_entry()` はエントリ詳細ページの `og:image` メタタグなど、実際に確認済みの
  安定した箇所から情報を取得するため、画像直リンクの取得は信頼性が高い設計です。
- `list_page()` / `iter_list()` は `<ul id="thumbs2">` 内のサムネイル一覧を直接パースします。
  `get_entry()` より高速（エントリごとの追加リクエストが不要）ですが、タグ一覧や投稿者などは
  含まれず、Zerochan 側のページデザイン変更の影響も受けやすい点に注意してください。
  `l`（1ページあたりの件数）パラメータが通常のブラウズ/検索ページでも実際に効くかは未確認です。
- `get_category()` はページ内に `<script type="application/ld+json">` の構造化データが
  存在する場合、そちらの `name` / `image` / `@type` を優先的に使います（非公式ライブラリ
  [kiriharu/zerochan](https://github.com/kiriharu/zerochan) の手法を参考にした改良）。
  構造化データが無い、または対象フィールドが欠けている場合のみ、従来どおり
  `og:description` の文面（例: "X is a character from Y."）から `type` を推測する
  フォールバックに切り替わります。フォールバック時は説明文の形式が異なるカテゴリで
  `type` が `None` になることがあります。`description` は常に `og:description` から
  取得されます。
- サイズ/次元フィルタ (`dimension`) は JSON API・通常ページの両方で共通の文字列値
  (`large` / `huge` / `landscape` / `portrait` / `square`) を使うことを実際のサイトで確認済みです。
  `SizeFilter` / `SortBy` はこれらの分かりやすい別名で、非公式ライブラリ
  [kiriharu/zerochan](https://github.com/kiriharu/zerochan)（Python, `PictureSize`/`SortBy` Enum）を
  参考にしています。
- Zerochan の API ドキュメントでは、匿名アクセスは Ban 対象になり得ると明記されています。
  `ZerochanClient(username=...)` で自分のユーザー名を指定することを推奨します。
- レート制限は 60 req/min です。本ライブラリはデフォルトで 50 req/min に自主制限して
  いますが、大量ダウンロード時は特に注意してください。
- **Cloudflare 対策について**：`impersonate` オプションを使えば多くのケースで回避可能ですが、Zerochan 側の対策が強化された場合は、`impersonate` のバージョンを変えたり、Cookie を併用するなどして対応してください。
- 画像の著作権は各投稿者・原作者に帰属します。ダウンロードした画像の利用は自己責任で、
  各画像のライセンスや Zerochan の利用規約に従ってください。
- 会員限定コンテンツなど、一部エントリは取得できない場合があります。

## ライセンス

MIT
```