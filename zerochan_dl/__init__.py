"""
zerochan-dl
===========

Zerochan (https://www.zerochan.net) 用の非公式 Python クライアントライブラリ。

- 公式の read-only JSON/XML API (https://www.zerochan.net/api) を利用したタグ検索・
  ブラウズ・複数タグ検索。
- 個別エントリページの解析（フル解像度画像URL・タグ一覧・投稿者・サイズ等の取得）。
- 画像のダウンロード（ストリーミング、レジューム風の上書き回避、リトライ対応）。
- API のレート制限 (60 req/min) に配慮した簡易スロットリング。

これは Zerochan 非公式のサードパーティ製ライブラリです。Anthropic/Claude や
Zerochan 運営とは無関係です。利用の際は https://www.zerochan.net/api の利用規約・
レート制限を守り、自己責任でお使いください。
"""

from .client import ZerochanClient, SizeFilter, SortBy
from .models import (
    ZerochanCategoryInfo,
    ZerochanEntry,
    ZerochanListItem,
    ZerochanSearchResult,
)
from .exceptions import ZerochanError, ZerochanHTTPError, ZerochanParseError, RateLimitExceeded

__all__ = [
    "ZerochanClient",
    "SizeFilter",
    "SortBy",
    "ZerochanEntry",
    "ZerochanListItem",
    "ZerochanSearchResult",
    "ZerochanCategoryInfo",
    "ZerochanError",
    "ZerochanHTTPError",
    "ZerochanParseError",
    "RateLimitExceeded",
]

__version__ = "0.2.0"
