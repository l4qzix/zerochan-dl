"""Zerochan のエントリ（1枚の画像投稿）を表すモデル。"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ZerochanListItem:
    """検索/ブラウズ結果一覧の1件を表す軽量モデル。

    ``ZerochanClient.list_page()`` / ``iter_list()`` が返す。一覧ページ
    (``<ul id="thumbs2">``) から直接取れる情報のみを持つため、
    :class:`ZerochanEntry` と異なりタグ一覧や投稿者などは含まないが、
    その分エントリごとの追加リクエストが不要で高速。
    """

    id: Optional[int]
    title: Optional[str]
    full_image_url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    kb_size: Optional[int] = None

    @property
    def filename(self) -> str:
        return self.full_image_url.rsplit("/", 1)[-1]

    def __repr__(self) -> str:  # pragma: no cover - 表示用
        dims = f"{self.width}x{self.height}" if self.width and self.height else "?"
        return f"<ZerochanListItem id={self.id} dims={dims} url={self.full_image_url!r}>"


@dataclass
class ZerochanSearchResult:
    """``list_page()`` の戻り値。1ページ分の一覧結果とページ情報をまとめたもの。"""

    items: List[ZerochanListItem]
    page: int
    max_page: int
    members_only_skipped: int = 0
    """このページ内で、会員限定のため取得・解析できずスキップした件数。
    0より大きい場合、ログインすればより多くの画像が見える可能性がある。"""


@dataclass
class ZerochanCategoryInfo:
    """タグ/カテゴリページの概要情報 (``ZerochanClient.get_category()`` の戻り値)。"""

    name: Optional[str] = None
    image: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ZerochanEntry:
    """1件の画像投稿を表す。

    エントリ詳細ページ (``https://www.zerochan.net/<id>``) を解析して生成される。
    フィールドはページに実際に存在する情報のみを保持し、取得できなかった値は
    ``None`` または空リストになる。
    """

    id: int
    title: Optional[str] = None
    full_image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size_kb: Optional[int] = None
    file_format: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    primary_tag: Optional[str] = None
    mangaka: Optional[str] = None
    uploader: Optional[str] = None
    source_url: Optional[str] = None
    favorites: Optional[int] = None
    page_url: str = ""

    @property
    def filename(self) -> str:
        """ダウンロード時に使うおすすめのファイル名を返す。"""
        if self.full_image_url:
            return self.full_image_url.rsplit("/", 1)[-1]
        ext = (self.file_format or "jpg").lower()
        return f"zerochan_{self.id}.{ext}"

    def __repr__(self) -> str:  # pragma: no cover - 表示用
        dims = f"{self.width}x{self.height}" if self.width and self.height else "?"
        return f"<ZerochanEntry id={self.id} title={self.title!r} dims={dims}>"