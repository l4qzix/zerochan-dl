"""コマンドラインから使う簡易インターフェース。

使い方:
    python -m zerochan_dl search "Genshin Impact" --limit 10 --out ./downloads
    python -m zerochan_dl get 3793685 --out ./downloads
"""

from __future__ import annotations

import argparse
import sys

from .client import ZerochanClient
from .exceptions import ZerochanError


def _progress(downloaded: int, total):
    if total:
        pct = downloaded * 100 // total
        print(f"\r  ダウンロード中... {pct:3d}% ({downloaded}/{total} bytes)", end="", flush=True)
    else:
        print(f"\r  ダウンロード中... {downloaded} bytes", end="", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="zerochan_dl", description="Zerochan 非公式 CLI")
    parser.add_argument("--username", default=None, help="Zerochan ユーザー名 (User-Agent に使用)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="タグ検索して画像を一括ダウンロード")
    p_search.add_argument(
        "tags",
        help="検索タグ。複数指定する場合はカンマ区切り (例: 'Genshin Impact,Klee' は"
        " AND 検索)",
    )
    p_search.add_argument("--limit", type=int, default=10, help="ダウンロードする最大件数")
    p_search.add_argument("--out", default="./zerochan_downloads", help="保存先ディレクトリ")
    p_search.add_argument(
        "--strict", action="store_true", help="Strict Mode で検索する（単一タグのみ有効）"
    )

    p_get = sub.add_parser("get", help="ID を指定して1件ダウンロード")
    p_get.add_argument("entry_id", help="エントリ ID (例: 3793685)")
    p_get.add_argument("--out", default="./zerochan_downloads", help="保存先ディレクトリ")

    args = parser.parse_args(argv)
    client = ZerochanClient(username=args.username)

    try:
        if args.command == "search":
            tag_list = [t.strip() for t in args.tags.split(",") if t.strip()]
            tag_arg = tag_list[0] if len(tag_list) == 1 else tag_list
            label = " + ".join(tag_list)
            print(f"'{label}' を検索してダウンロードします（最大 {args.limit} 件）...")
            paths = client.download_search_results(
                tag_arg,
                dest_dir=args.out,
                max_images=args.limit,
                strict=args.strict,
                progress_callback=_progress,
            )
            print()
            print(f"{len(paths)} 件を保存しました:")
            for p in paths:
                print(f"  {p}")
        elif args.command == "get":
            entry = client.get_entry(args.entry_id)
            print(f"取得: {entry}")
            path = client.download(entry, dest_dir=args.out, progress_callback=_progress)
            print()
            print(f"保存しました: {path}")
    except ZerochanError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
