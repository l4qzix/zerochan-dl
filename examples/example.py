"""zerochan_dl の使用例。

実行前に依存関係をインストールしてください:
    pip install -r requirements.txt
    または
    pip install -e .
"""

from zerochan_dl import ZerochanClient

# username は任意ですが、Zerochan の API ドキュメントで推奨されています。

client = ZerochanClient(username="your_zerochan_username",impersonate="chrome")

# --- 0. （任意）ログインして会員限定コンテンツにアクセス --------------------
# 方法A: z_hash / z_id の2値だけで手軽に認証する（お手軽）
# client.authorize(z_hash="xxxx", z_id="yyyy")
# if client.is_authenticated():
#     print("ログイン成功を確認しました")
# else:
#     print("ログインできていません（Cookie切れ等の可能性）")
#
# 方法B: ブラウザからコピーしたCookieヘッダー全体を使う（最も確実）
# client.set_cookie("z_id=xxxx; z_hash=yyyy; other=zzzz")
#
# 方法C: ユーザー名/パスワードでログインを試みる（実験的）
# client.login("myusername", "mypassword")

# --- 1. 単一タグで検索 (生のJSON APIレスポンス) -----------------------------
raw = client.search("Hatsune Miku", page=1, limit=5)
print("生のJSONレスポンス（構造は要確認）:")
print(raw)

# --- 2. IDを指定して詳細情報を取得（画像直リンク・タグ一覧などが確実に取れる）---
entry = client.get_entry(3793685)
print(entry)
print("フル画像URL:", entry.full_image_url)
print("タグ:", entry.tags)

# --- 3. 1枚だけダウンロード -------------------------------------------------
path = client.download(entry, dest_dir="./downloads")
print("保存先:", path)

# --- 4. タグ検索結果をまとめてダウンロード ----------------------------------
saved = client.download_search_results(
    "Genshin Impact", dest_dir="./downloads/genshin", max_images=5
)
print(f"{len(saved)} 件保存しました")
for p in saved:
    print(" -", p)

# --- 4b. 複数タグのAND検索でまとめてダウンロード ----------------------------
saved_multi = client.download_search_results(
    ["Genshin Impact", "Klee"], dest_dir="./downloads/genshin_klee", max_images=5
)
print(f"複数タグ検索で {len(saved_multi)} 件保存しました")

# --- 5. ページを跨いだ検索結果をイテレートする ------------------------------
count = 0
for item in client.iter_search("Zerochan", max_pages=2, limit=20):
    count += 1
print(f"2ページ分で {count} 件のアイテムを取得しました")

# --- 6. タグ/カテゴリページの概要情報を取得 ----------------------------------
# JSON-LD構造化データがあればそちらを優先し、無ければ og:description から
# type を推測するフォールバックになる。
category = client.get_category("Furina de Fontaine")
print("カテゴリ名:", category.name)
print("種別:", category.type)

