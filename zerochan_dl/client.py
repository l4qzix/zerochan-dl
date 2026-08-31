"""zerochan_dl のメインクライアント実装。"""

from __future__ import annotations

import os
import re
import time
import json as _json
from collections import deque
from typing import Iterator, List, Optional, Sequence, Union
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .exceptions import RateLimitExceeded, ZerochanError, ZerochanHTTPError, ZerochanParseError
from .models import ZerochanCategoryInfo, ZerochanEntry, ZerochanListItem, ZerochanSearchResult
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
BASE_URL = "https://www.zerochan.net"

# Zerochan のドキュメント (https://www.zerochan.net/api) に記載されている
# 有効な次元・色フィルタ値。実際のサイト (https://www.zerochan.net/<tag>?d=large など) を
# 確認したところ、通常の HTML ページ (list_page()) も JSON API (?json) と同じ文字列値
# ("large" / "huge" / "landscape" / "portrait" / "square") を ``d`` パラメータに使っており、
# 別体系の整数コードは存在しなかった。そのため両方でこの1つの定数セットを共有する。
VALID_DIMENSIONS = {"large", "huge", "landscape", "portrait", "square"}
VALID_SORTS = {"id", "fav", "random"}


class SizeFilter:
    """``dimension`` パラメータ (``VALID_DIMENSIONS``) の分かりやすい別名。

    非公式ライブラリ kiriharu/zerochan (https://github.com/kiriharu/zerochan) の
    ``PictureSize`` Enum を参考にした、意味の分かりやすいエイリアス。値そのものは
    実サイトで確認済みの文字列 (``VALID_DIMENSIONS``) と同じもの。
    """

    ALL = None
    BIGGER_AND_BETTER = "large"
    BIG_AND_HUGE = "huge"
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class SortBy:
    """``sort`` パラメータ (``VALID_SORTS``) の分かりやすい別名（kiriharu/zerochan の

    ``SortBy`` Enum を参考）。
    """

    RECENT = "id"
    POPULAR = "fav"
    RANDOM = "random"


class ZerochanClient:
    """Zerochan.net の非公式クライアント。

    公式の read-only API (``?json`` を付与するエンドポイント) を優先的に使い、
    画像の直リンクやタグ一覧などページ側にしか無い情報は個別エントリページを
    軽量にパースして補完する。

    Parameters
    ----------
    username:
        Zerochan のユーザー名（あれば）。API のドキュメントで推奨されている
        User-Agent ("プロジェクト名 - ユーザー名") の組み立てに使う。
    project_name:
        あなたのプロジェクト/アプリ名。匿名だと Ban されやすいとドキュメントに
        明記されているため、できれば分かりやすい名前を設定すること。
    requests_per_minute:
        自主的なレート制限のしきい値。公式ドキュメントでは 60 req/min が上限と
        されている。デフォルトは安全側に倒して 50。
    session:
        既存の ``requests.Session`` を渡したい場合に使用。
    timeout:
        HTTP リクエストのタイムアウト秒数。
    cookie:
        ログイン済みブラウザから取得した Cookie ヘッダーの文字列（任意）。
        指定すると、会員限定（ログインしないと見られない）コンテンツにも
        アクセスできる場合がある。詳しくは :meth:`set_cookie` を参照。
    z_hash, z_id:
        ``cookie`` の代わりに、``z_hash`` / ``z_id`` の2つの値だけを個別に
        指定したい場合に使う（両方セットで指定する必要がある）。詳しくは
        :meth:`authorize` を参照。``cookie`` と同時に指定した場合は ``cookie``
        が優先される。
    """

    def __init__(
        self,
        username: Optional[str] = None,
        project_name: str = "zerochan-dl (unofficial python client)",
        requests_per_minute: int = 50,
        session: Optional[requests.Session] = None,
        timeout: float = 15.0,
        cookie: Optional[str] = None,
        z_hash: Optional[str] = None,
        z_id: Optional[str] = None,
        impersonate: Optional[str] = None,
    ) -> None:
        if session is not None:
            self.session = session
        elif impersonate is not None:
            if not HAS_CURL_CFFI:
                raise ImportError(
                    "curl_cffi がインストールされていません。"
                    "pip install curl_cffi を実行してください。"
                )
            self.session = cffi_requests.Session(impersonate=impersonate)
        else:
            self.session = requests.Session()
        ua = project_name if not username else f"{project_name} - {username}"
        self.session.headers.setdefault("User-Agent", ua)
        self.timeout = timeout
        self._rpm = max(1, requests_per_minute)
        self._request_times: deque = deque()
        self._logged_in = False
        # z_lang は Zerochan が言語設定に使う Cookie。未設定でも動作するが、
        # 明示しておくことでレスポンスが一貫しやすくなる。
        self.session.cookies.setdefault("z_lang", "en")
        if cookie:
            self.set_cookie(cookie)
        elif z_hash and z_id:
            self.authorize(z_hash=z_hash, z_id=z_id)

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        """直近 60 秒間のリクエスト数が上限を超えないよう、必要なら待機する。"""
        now = time.monotonic()
        window = 60.0
        while self._request_times and now - self._request_times[0] > window:
            self._request_times.popleft()
        if len(self._request_times) >= self._rpm:
            sleep_for = window - (now - self._request_times[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._request_times.append(time.monotonic())

    def _request(
        self, path: str, params: Optional[dict] = None, _retried: bool = False
    ) -> requests.Response:
        self._throttle()
        url = f"{BASE_URL}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ZerochanHTTPError(f"リクエストに失敗しました: {exc}", url=url) from exc

        if resp.status_code == 429:
            raise RateLimitExceeded(
                "Zerochan からレート制限 (429) を受け取りました。しばらく待ってから再試行してください。"
            )
        if not resp.ok:
            body_lower = resp.text.lower()
            # Zerochan 独自の簡易ボット対策ページ（"Crawlers are not permitted on
            # this site... Try enabling cookies."）。このページは検証用 Cookie を
            # Set-Cookie ヘッダーで返し、次のリクエストでそれを送り返せているかを
            # 見ているだけのことがある。requests.Session は Set-Cookie を自動で
            # cookie jar に保存するため、同じセッションでもう一度リクエストし
            # 直すだけで通ることがある（JS 実行を要求する本格的な Cloudflare
            # チャレンジとは別物で、こちらは1回のリトライで突破できる場合がある）。
            is_cookie_challenge = (
                "enabling cookies" in body_lower or "crawlers are not permitted" in body_lower
            )
            if is_cookie_challenge and not _retried:
                return self._request(path, params, _retried=True)

            hint = ""
            if resp.status_code in (503, 403, 429) or "cloudflare" in body_lower or is_cookie_challenge:
                snippet = resp.text.strip().replace("\n", " ")[:200]
                extra = ""
                if is_cookie_challenge:
                    extra = (
                        "\n  Zerochan 独自のボット対策メッセージです。同一セッションでの"
                        "自動リトライでも解消しませんでした。ZerochanClient(username=...)"
                        " でユーザー名を指定してカスタム User-Agent を設定することも"
                        "試してください（匿名リクエストは弾かれやすいと Zerochan API"
                        " ドキュメント https://www.zerochan.net/api に明記されています）。"
                    )
                hint = (
                    f"\n  Cloudflare 等のボット対策や一時的な障害の可能性があります"
                    f"（ブラウザで {url} に直接アクセスして確認してください）。"
                    f"\n  レスポンス本文の先頭: {snippet!r}{extra}"
                )
            raise ZerochanHTTPError(
                f"HTTP {resp.status_code} : {url}{hint}", status_code=resp.status_code, url=url
            )
        return resp

    def _get_json(self, path: str, params: Optional[dict] = None) -> Union[dict, list]:
        params = dict(params or {})
        params["json"] = ""
        resp = self._request(path, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise ZerochanParseError(
                "JSON としてパースできませんでした。Zerochan が API 仕様を変更したか、"
                "一時的に HTML ページ（ログイン要求など）を返している可能性があります。"
            ) from exc

    def _get_html(self, path: str, params: Optional[dict] = None) -> str:
        resp = self._request(path, params)
        return resp.text

    # ------------------------------------------------------------------
    # 認証（会員限定コンテンツへのアクセス）
    # ------------------------------------------------------------------
    def set_cookie(self, cookie_header: str) -> None:
        """ログイン済みブラウザから取得した Cookie ヘッダーをそのまま設定する。

        最も確実な認証方法。手順の例:

        1. 普段使っているブラウザで https://www.zerochan.net にログインする。
        2. 開発者ツールを開き（F12 など）、Network タブでページをリロードする。
        3. zerochan.net への何らかのリクエストを選び、リクエストヘッダーの
           ``Cookie: xxxxx=yyyy; zzzz=wwww`` の値（``Cookie:`` の後ろの部分）を
           まるごとコピーする。
        4. ``client.set_cookie("xxxxx=yyyy; zzzz=wwww")`` のように渡す。

        以降のすべてのリクエスト（``search`` / ``get_entry`` / ``download`` など）
        がこのセッションとして送信されるため、会員限定コンテンツにもアクセス
        できるようになる場合がある（対象コンテンツの公開範囲は Zerochan 側の
        設定に依存する）。
        """
        self.session.headers["Cookie"] = cookie_header
        self._logged_in = True

    def authorize(self, z_hash: str, z_id: str) -> None:
        """``z_hash`` と ``z_id`` の2つの Cookie 値だけでログイン状態にする簡易メソッド。

        Zerochan のログイン状態は主に ``z_id`` と ``z_hash`` という2つの Cookie で
        保持されている（上記 :meth:`set_cookie` の説明も参照）。毎回ブラウザの
        開発者ツールから ``Cookie: ...`` ヘッダー全体をまるごとコピーしなくても、
        この2つの値さえ分かれば十分なことが多い。非公式ライブラリ
        `kiriharu/zerochan <https://github.com/kiriharu/zerochan>`_ の
        ``authorize(z_hash, z_id)`` を参考にした簡易メソッド。

        ``set_cookie()`` が Cookie ヘッダー全体を1つの文字列として上書きするのに
        対し、こちらは ``z_hash`` / ``z_id`` の2つだけをセッションの Cookie jar に
        個別に設定する。以前に :meth:`set_cookie` で Cookie ヘッダーを設定していた
        場合、それを優先させてしまい ``z_hash`` / ``z_id`` の変更が無視されて
        しまわないよう、既存の ``Cookie`` ヘッダーがあれば取り除いてから設定する。

        Parameters
        ----------
        z_hash:
            ブラウザの開発者ツールで確認できる ``z_hash`` Cookie の値。
        z_id:
            同じく ``z_id`` Cookie の値。

        Examples
        --------
        >>> client = ZerochanClient()
        >>> client.authorize(z_hash="xxxx", z_id="yyyy")
        >>> client.is_authenticated()
        True
        """
        self.session.headers.pop("Cookie", None)
        self.session.cookies.set("z_hash", z_hash)
        self.session.cookies.set("z_id", z_id)
        self._logged_in = True

    @property
    def logged_in(self) -> bool:
        """:meth:`login` / :meth:`set_cookie` / :meth:`authorize` によって
        認証情報が設定されているか。

        注意: これはあくまでローカルのフラグであり、実際にサーバー側で有効な
        セッションかどうかを保証するものではない（Cookie の期限切れなど）。
        """
        return self._logged_in

    def login(self, username: str, password: str) -> bool:
        """ユーザー名とパスワードでログインを試みる（実験的機能）。

        Zerochan のログインフォームのフィールド名をハードコードする代わりに、
        ``https://www.zerochan.net/login`` の HTML を実行時に取得して
        ``<form>`` の中身（input の name/value）を解析し、パスワード欄と
        ユーザー名らしき欄を特定してそのまま POST 送信する。これにより
        Zerochan 側でフィールド名が変わっても追従しやすくなっているが、
        フォーム構造が大きく変わった場合は失敗する可能性がある。

        ログインに成功したかどうかは HTTP レスポンスからのヒューリスティックな
        判定であり、100% の精度は保証できない。確実性を重視する場合は
        :meth:`set_cookie` の利用を推奨する。

        Returns
        -------
        bool
            ログインに成功したと判断できた場合 True。
        """
        login_path = "/login"
        html = self._get_html(login_path)
        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form")
        if form is None:
            raise ZerochanParseError(
                "ログインフォームが見つかりませんでした。ページ構造が変更された"
                "可能性があります。set_cookie() での認証をご検討ください。"
            )

        action = form.get("action") or login_path
        action_url = urljoin(f"{BASE_URL}{login_path}", action)

        fields = {}
        username_field = None
        password_field = None
        for inp in form.find_all(["input", "button"]):
            name = inp.get("name")
            if not name:
                continue
            itype = (inp.get("type") or "text").lower()
            value = inp.get("value", "")
            if itype == "password":
                password_field = name
                fields[name] = password
            elif itype == "checkbox":
                if inp.has_attr("checked"):
                    fields[name] = value or "on"
            elif itype == "radio":
                if inp.has_attr("checked"):
                    fields[name] = value
            elif itype in ("submit", "hidden", "text", "email"):
                fields[name] = value
                if (
                    itype in ("text", "email")
                    and username_field is None
                    and "pass" not in name.lower()
                ):
                    username_field = name

        if username_field is None or password_field is None:
            raise ZerochanParseError(
                "ユーザー名またはパスワードの入力欄を特定できませんでした。"
                "フォーム構造が想定と異なる可能性があります。"
                " set_cookie() での認証をご検討ください。"
            )
        fields[username_field] = username

        self._throttle()
        try:
            resp = self.session.post(
                action_url, data=fields, timeout=self.timeout, allow_redirects=True
            )
        except requests.RequestException as exc:
            raise ZerochanHTTPError(f"ログインリクエストに失敗しました: {exc}", url=action_url) from exc

        if resp.status_code == 429:
            raise RateLimitExceeded(
                "Zerochan からレート制限 (429) を受け取りました。しばらく待ってから再試行してください。"
            )

        success = ("/login" not in resp.url) or bool(
            re.search(r"log\s*out", resp.text, re.IGNORECASE)
        )
        self._logged_in = success
        return success

    def is_authenticated(self) -> Optional[bool]:
        """現在のセッション（Cookie）が実際にログイン状態かどうかをサーバーに確認する。

        ``set_cookie()`` / ``authorize()`` でCookieを設定した直後などに、それが
        本当に有効なログインセッションかどうかを確かめたい場合に使う。
        ``logged_in`` プロパティが「設定したかどうか」のローカルなフラグに
        過ぎないのに対し、こちらは実際に Zerochan へリクエストを送って判定する
        ため、Cookie の期限切れなども検出できる。

        判定方法: ``https://www.zerochan.net/`` （トップページ）にアクセスし、

        - ログイン済みの場合、通常はヘッダー等に "Logout" リンクが表示される。
        - 未ログインの場合、ログインフォーム、または ``/login`` へのリンクが
          表示される。

        以前は ``/login`` ページに直接アクセスして判定していましたが、ログイン
        関連のエンドポイントはクレデンシャルスタッフィング対策などで他のページ
        より厳しいボット対策（Cloudflare の JS チャレンジなど）が掛かっており、
        ``requests`` だけでは常に ``503``/``403`` 等で失敗し続けるケースが
        確認されています。通常のブラウズと同じ扱いを受けやすいトップページの方が
        遥かに通りやすいため、こちらに変更しています。

        なお、それでも失敗する場合は Zerochan 側のボット対策自体に阻まれている
        可能性が高く、このライブラリ（``requests`` ベース）では技術的に回避
        できません。その場合は ``is_authenticated()`` をスキップし、既知の
        エントリ ID で直接 :meth:`get_entry` を試すなど、実際に必要な操作で
        認証状態を確認することを検討してください。

        Returns
        -------
        Optional[bool]
            ``True``  : ログイン済みと判断できた
            ``False`` : 未ログイン（フォームまたは ``/login`` へのリンクが見つかった）と判断できた
            ``None``  : ページ構造から判定できなかった（要目視確認）
        """
        html = self._get_html("/")
        soup = BeautifulSoup(html, "html.parser")

        has_login_form = soup.find("input", attrs={"type": "password"}) is not None
        has_login_link = soup.find("a", href=re.compile(r"^/login/?(?:\?.*)?$")) is not None
        has_logout_link = bool(re.search(r"log\s*out", html, re.IGNORECASE))

        if has_logout_link and not (has_login_form or has_login_link):
            result = True
        elif has_login_form or has_login_link:
            result = False
        else:
            # どちらとも判定できない。ページ構造が変わっている可能性がある。
            result = None

        if result is not None:
            self._logged_in = result
        return result

    # ------------------------------------------------------------------
    # 公式 JSON API ラッパー (https://www.zerochan.net/api)
    # ------------------------------------------------------------------
    def browse(
        self,
        page: int = 1,
        limit: int = 24,
        sort: str = "id",
        time_range: int = 0,
        dimension: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Union[dict, list]:
        """タグ指定なしで全エントリをブラウズする (``/?p=..&json``)。

        戻り値は Zerochan API が返す生の JSON 構造（dict または list）をそのまま返す。
        フィールド名は Zerochan 側の仕様に依存するため、内容は ``print()`` などで
        一度確認してから使うことを推奨する。
        """
        if sort not in VALID_SORTS:
            raise ValueError(f"sort は {VALID_SORTS} のいずれかである必要があります")
        if dimension is not None and dimension not in VALID_DIMENSIONS:
            raise ValueError(f"dimension は {VALID_DIMENSIONS} のいずれかである必要があります")

        params = {"p": page, "l": limit, "s": sort, "t": time_range}
        if dimension:
            params["d"] = dimension
        if color:
            params["c"] = color
        return self._get_json("/", params)

    def search(
        self,
        tag: str,
        page: int = 1,
        limit: int = 24,
        strict: bool = False,
        dimension: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Union[dict, list]:
        """単一タグでエントリを検索する (``/<tag>?json``)。

        Parameters
        ----------
        tag:
            検索したいタグ名（例: ``"Genshin Impact"``, ``"Hatsune Miku"``）。
            スペースはそのまま渡してよい（内部で URL エンコードされる）。
        strict:
            True の場合、そのタグが「主タグ」であるエントリのみを対象にする
            (Strict Mode)。メタタグには使用できない（Zerochan 側の制限）。
        """
        if dimension is not None and dimension not in VALID_DIMENSIONS:
            raise ValueError(f"dimension は {VALID_DIMENSIONS} のいずれかである必要があります")

        params = {"p": page, "l": limit}
        if strict:
            params["strict"] = ""
        if dimension:
            params["d"] = dimension
        if color:
            params["c"] = color
        path = f"/{quote(tag)}"
        return self._get_json(path, params)

    def search_multi(
        self, tags: Sequence[str], page: int = 1, limit: int = 24
    ) -> Union[dict, list]:
        """複数タグの AND 検索を行う (``/tag1,tag2?json``)。"""
        if not tags:
            raise ValueError("tags は 1 件以上指定してください")
        joined = ",".join(quote(t) for t in tags)
        return self._get_json(f"/{joined}", {"p": page, "l": limit})

    def get_entry_raw(self, entry_id: Union[int, str]) -> Union[dict, list]:
        """1件のエントリについて、生の JSON データを取得する (``/<id>?json``)。"""
        return self._get_json(f"/{entry_id}", {})

    def iter_search(
        self,
        tag: Union[str, Sequence[str]],
        max_pages: Optional[int] = None,
        limit: int = 100,
        **kwargs,
    ) -> Iterator[dict]:
        """タグ検索の結果を複数ページにわたって自動で辿るジェネレータ。

        ``tag`` は単一タグの文字列でも、複数タグのリスト/タプルでもよい。
        リストを渡した場合は :meth:`search_multi` による AND 検索（複数タグを
        すべて含むエントリのみ）になる。複数タグ検索では ``strict`` や
        ``dimension`` などの追加パラメータは使えないため、``kwargs`` は無視される。

        各ページの生 JSON レスポンスに含まれるエントリのリストを1件ずつ yield する。
        レスポンス構造の違いに対応するため、dict の場合は代表的なキー
        (``items``, ``entries``, ``results``, ``data``) を順に探し、それでも
        見つからなければレスポンス全体を1件として扱う。
        """
        is_multi = not isinstance(tag, str)
        page = 1
        while max_pages is None or page <= max_pages:
            if is_multi:
                data = self.search_multi(tag, page=page, limit=limit)
            else:
                data = self.search(tag, page=page, limit=limit, **kwargs)
            items = self._extract_items(data)
            if not items:
                break
            for item in items:
                yield item
            page += 1

    @staticmethod
    def _extract_items(data: Union[dict, list]) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "entries", "results", "data", "posts"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    # ------------------------------------------------------------------
    # HTML ベースの詳細取得（画像直リンク・タグ一覧などの確実な取得用）
    # ------------------------------------------------------------------
    def get_entry(self, entry_id: Union[int, str]) -> ZerochanEntry:
        """エントリ詳細ページを解析し、扱いやすい :class:`ZerochanEntry` を返す。

        Zerochan の公開 JSON API はレスポンス形式が変化する可能性があるため、
        フル解像度画像の URL のように確実性が求められる情報は、実際の HTML
        ページ (``og:image`` メタタグやタグ一覧のリンクなど) から取得する。
        """
        entry_id = str(entry_id)
        page_url = f"{BASE_URL}/{entry_id}"
        html = self._get_html(f"/{entry_id}")
        soup = BeautifulSoup(html, "html.parser")

        full_image_url = self._meta_content(soup, "og:image")
        if not full_image_url:
            if re.search(r"member|sign\s*up|log\s*in|register", html, re.IGNORECASE):
                raise ZerochanParseError(
                    f"エントリ #{entry_id} の画像を取得できませんでした。会員限定"
                    "（ログインが必要な）コンテンツの可能性があります。"
                    " ZerochanClient(cookie=...) や client.set_cookie(...) /"
                    " client.login(...) でログイン状態にしてから再試行してください。"
                )
            raise ZerochanParseError(
                f"エントリ #{entry_id} の画像 URL を取得できませんでした。"
                " ID が存在しないか、削除されている可能性があります。"
            )

        title = self._meta_content(soup, "og:title") or (soup.title.string if soup.title else None)
        if title:
            title = re.sub(r"\s*-\s*Zerochan Anime Image Board\s*$", "", title).strip()

        width = height = None
        file_size_kb = None
        file_format = None
        description = self._meta_content(soup, "og:description") or ""
        dim_match = re.search(r"(\d+)\s*[×x]\s*(\d+)", description)
        if dim_match:
            width, height = int(dim_match.group(1)), int(dim_match.group(2))

        size_match = re.search(r"(\d[\d,]*)\s*kB\s*(jpg|png|gif|webp)", html, re.IGNORECASE)
        if size_match:
            file_size_kb = int(size_match.group(1).replace(",", ""))
            file_format = size_match.group(2).lower()
        elif full_image_url:
            ext_match = re.search(r"\.(jpg|jpeg|png|gif|webp)(?:\?|$)", full_image_url, re.IGNORECASE)
            if ext_match:
                file_format = ext_match.group(1).lower()

        tags: List[str] = []
        tags_heading = soup.find(lambda t: t.name in ("h2", "h3") and t.get_text(strip=True) == "Tags")
        if tags_heading:
            tag_list = tags_heading.find_next("ul") or tags_heading.find_parent().find_next("ul")
            if tag_list:
                for a in tag_list.find_all("a"):
                    text = a.get_text(strip=True)
                    if text:
                        tags.append(text)
        if not tags:
            # フォールバック: "Tags" 見出し配下の <ul> が見つからない場合、
            # ページ内の "Added by ..." 属性（category ページの兄弟パターン）を
            # 持つタグリンクを拾う。それも無ければタグ一覧は空のままとなる。
            for a in soup.find_all("a", href=True, title=re.compile(r"Added by", re.IGNORECASE)):
                text = a.get_text(strip=True)
                if text:
                    tags.append(text)

        uploader = None
        uploaded_by = soup.find(string=re.compile(r"Uploaded by", re.IGNORECASE))
        if uploaded_by:
            # 通常は "Uploaded by <a href="/user/Name">Name</a>" の形。
            # まず同じテキスト内に名前があるケース、次に直後の <a> タグを探す。
            m = re.search(r"Uploaded by\s+([^\n,<]+)", uploaded_by)
            if m and m.group(1).strip():
                uploader = m.group(1).strip()
            else:
                next_link = uploaded_by.find_next("a", href=re.compile(r"^/user/"))
                if next_link:
                    uploader = next_link.get_text(strip=True)

        mangaka = None
        mangaka_label = soup.find(string=re.compile(r"^\s*Mangaka:\s*$"))
        if mangaka_label:
            sib = mangaka_label.find_next("a")
            if sib:
                mangaka = sib.get_text(strip=True)

        source_url = None
        source_heading = soup.find(lambda t: t.name in ("h2", "h3") and "Source" in t.get_text())
        if source_heading:
            nxt = source_heading.find_next(["a", "p"])
            if nxt:
                text = nxt.get_text(strip=True)
                if text.startswith("http"):
                    source_url = text

        favorites = None
        fav_match = re.search(r"([\d,]+)\s*favorites?", html)
        if fav_match:
            favorites = int(fav_match.group(1).replace(",", ""))

        primary_tag = tags[0] if tags else None
        thumbnail_url = (
            full_image_url.replace(".full.", ".1024.") if ".full." in full_image_url else None
        )

        try:
            numeric_id = int(entry_id)
        except ValueError:
            numeric_id = -1

        return ZerochanEntry(
            id=numeric_id,
            title=title,
            full_image_url=full_image_url,
            thumbnail_url=thumbnail_url,
            width=width,
            height=height,
            file_size_kb=file_size_kb,
            file_format=file_format,
            tags=tags,
            primary_tag=primary_tag,
            mangaka=mangaka,
            uploader=uploader,
            source_url=source_url,
            favorites=favorites,
            page_url=page_url,
        )

    @staticmethod
    def _meta_content(soup: BeautifulSoup, property_name: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"property": property_name}) or soup.find(
            "meta", attrs={"name": property_name}
        )
        return tag.get("content") if tag else None

    # ------------------------------------------------------------------
    # HTML ベースの一覧取得（サムネイル一覧・カテゴリ概要）
    # ------------------------------------------------------------------
    def list_page(
        self,
        tag: Optional[Union[str, Sequence[str]]] = None,
        page: int = 1,
        limit: Optional[int] = None,
        sort: str = "id",
        time_range: int = 0,
        dimension: Optional[str] = None,
        color: Optional[str] = None,
        strict: bool = False,
    ) -> ZerochanSearchResult:
        """通常のブラウズ/検索ページ（HTML）を取得し、サムネイル一覧を軽量パースする。

        :meth:`browse` / :meth:`search` は Zerochan の JSON API をそのまま返すが、
        こちらは実際に表示されている ``<ul id="thumbs2">`` のサムネイル一覧を解析して
        :class:`~zerochan_dl.models.ZerochanListItem` のリストにする。タグ一覧や
        投稿者などエントリ詳細が必要な場合は代わりに :meth:`get_entry` を使うこと。

        Parameters
        ----------
        tag:
            タグ名（文字列）。複数タグを AND 検索したい場合はリスト/タプルで渡す
            （:meth:`search_multi` と同様にカンマ区切りで結合される）。``None`` の
            場合はタグ指定なしの全体ブラウズになる。
        limit:
            1ページあたりの件数。JSON API とは異なり、通常のブラウズ/検索ページが
            この値を実際に尊重するかは未確認のため、指定しても無視される場合がある。
        strict:
            単一タグ検索時のみ有効（Strict Mode）。複数タグ検索では無視される。

        Notes
        -----
        HTML のページ構造に依存するため、Zerochan 側のデザイン変更に弱い。
        ``members_only_skipped`` は、サムネイルへのリンクは存在するが画像直リンクが
        取得できなかった（＝会員限定と思われる）件数のヒューリスティックな推定値。
        """
        if sort not in VALID_SORTS:
            raise ValueError(f"sort は {VALID_SORTS} のいずれかである必要があります")
        if dimension is not None and dimension not in VALID_DIMENSIONS:
            raise ValueError(f"dimension は {VALID_DIMENSIONS} のいずれかである必要があります")

        params = {"p": page, "s": sort, "t": time_range}
        if limit is not None:
            params["l"] = limit
        if dimension:
            params["d"] = dimension
        if color:
            params["c"] = color

        if tag is None:
            path = "/"
        elif isinstance(tag, str):
            if strict:
                params["strict"] = ""
            path = f"/{quote(tag)}"
        else:
            path = f"/{','.join(quote(t) for t in tag)}"

        html = self._get_html(path, params)
        soup = BeautifulSoup(html, "html.parser")

        items: List[ZerochanListItem] = []
        members_only_skipped = 0
        thumbs = soup.find("ul", id="thumbs2")
        for li in thumbs.find_all("li", recursive=False) if thumbs else []:
            entry_link = li.find("a", href=re.compile(r"^/\d+$"))
            if entry_link is None:
                continue
            entry_id = int(entry_link["href"].lstrip("/"))

            img = entry_link.find("img")
            img_title = (img.get("title") or "") if img else ""
            item_title = (img.get("alt") or None) if img else None

            width = height = kb_size = None
            dim_match = re.search(r"(\d+)\s*[×x✕]\s*(\d+)", img_title)
            if dim_match:
                width, height = int(dim_match.group(1)), int(dim_match.group(2))
            size_match = re.search(r"([\d,]+)\s*kb", img_title, re.IGNORECASE)
            if size_match:
                kb_size = int(size_match.group(1).replace(",", ""))

            full_image_url = None
            for a in li.find_all("a", href=True):
                href = a["href"]
                if href == entry_link["href"]:
                    continue
                if re.search(r"\.zerochan\.net/.*\.(jpg|jpeg|png|gif|webp)$", href, re.IGNORECASE):
                    full_image_url = href
                    break

            if full_image_url is None:
                # 直リンクが見つからない＝会員限定などで隠されている可能性が高い。
                members_only_skipped += 1
                continue

            thumbnail_url = (
                full_image_url.replace(".full.", ".1024.") if ".full." in full_image_url else None
            )

            items.append(
                ZerochanListItem(
                    id=entry_id,
                    title=item_title,
                    full_image_url=full_image_url,
                    thumbnail_url=thumbnail_url,
                    width=width,
                    height=height,
                    kb_size=kb_size,
                )
            )

        max_page = page
        page_match = re.search(r"page\s+(\d+)\s+of\s+(\d+)", html, re.IGNORECASE)
        if page_match:
            max_page = int(page_match.group(2))

        return ZerochanSearchResult(
            items=items,
            page=page,
            max_page=max_page,
            members_only_skipped=members_only_skipped,
        )

    def iter_list(
        self,
        tag: Optional[Union[str, Sequence[str]]] = None,
        max_pages: Optional[int] = None,
        **kwargs,
    ) -> Iterator[ZerochanListItem]:
        """:meth:`list_page` の結果を複数ページにわたって自動で辿るジェネレータ。

        ``kwargs`` は :meth:`list_page` にそのまま渡される（``limit`` / ``sort`` /
        ``dimension`` / ``color`` / ``strict`` など）。
        """
        page = 1
        while max_pages is None or page <= max_pages:
            result = self.list_page(tag, page=page, **kwargs)
            if not result.items:
                break
            for item in result.items:
                yield item
            if page >= result.max_page:
                break
            page += 1

    def get_category(self, tag: str) -> ZerochanCategoryInfo:
        """タグ/カテゴリページの概要情報を取得する。

        まずページ内の ``<script type="application/ld+json">``（構造化データ）を
        優先的に使う。これが存在する場合、``name`` / ``image`` / ``@type`` の各
        フィールドが Zerochan 側から明示的に提供されるため、``og:description`` の
        文面をヒューリスティックに正規表現で推測するよりも信頼性が高い
        （非公式ライブラリ kiriharu/zerochan がこの手法を採っていたのを参考にした）。

        構造化データが存在しない、または一部フィールドが欠けている場合は、
        従来どおり ``og:title`` / ``og:image`` / ``og:description`` メタタグに
        フォールバックする。``description`` は常に ``og:description`` から取得する
        （構造化データ側には通常含まれないため）。
        """
        path = f"/{quote(tag)}"
        html = self._get_html(path)
        soup = BeautifulSoup(html, "html.parser")

        ld_name = ld_image = ld_type = None
        ld_script = soup.find("script", attrs={"type": "application/ld+json"})
        if ld_script and ld_script.string:
            try:
                ld_data = _json.loads(ld_script.string)
            except ValueError:
                ld_data = None
            if isinstance(ld_data, list):
                # 稀に配列で複数の構造化データブロックが並ぶことがあるため、
                # "name" を持つ最初の要素を使う。
                ld_data = next((d for d in ld_data if isinstance(d, dict) and d.get("name")), None)
            if isinstance(ld_data, dict):
                ld_name = ld_data.get("name")
                ld_image = ld_data.get("image")
                ld_type = ld_data.get("@type")

        name = ld_name
        if not name:
            name = self._meta_content(soup, "og:title")
            if name:
                name = re.sub(r"\s*-\s*Zerochan Anime Image Board\s*$", "", name).strip()
                # og:title は "Furina de Fontaine - Genshin Impact" のように
                # "<名前> - <親カテゴリ>" 形式になることがあるため、先頭部分のみを使う。
                name = name.split(" - ", 1)[0].strip()

        image = ld_image or self._meta_content(soup, "og:image")
        description = self._meta_content(soup, "og:description")

        category_type = ld_type
        if not category_type and description:
            type_match = re.search(r"is an? ([A-Za-z][A-Za-z /]*?) from ", description)
            if type_match:
                category_type = type_match.group(1).strip()

        return ZerochanCategoryInfo(
            name=name, image=image, type=category_type, description=description
        )

    # ------------------------------------------------------------------
    # ダウンロード
    # ------------------------------------------------------------------
    def download(
        self,
        entry: Union[int, str, "ZerochanEntry"],
        dest_dir: str = ".",
        filename: Optional[str] = None,
        overwrite: bool = False,
        chunk_size: int = 1 << 16,
        progress_callback=None,
    ) -> str:
        """画像をダウンロードしてローカルに保存する。

        Parameters
        ----------
        entry:
            エントリ ID (int/str) または :meth:`get_entry` が返す
            :class:`ZerochanEntry`、あるいは直接の画像 URL(``http`` で始まる文字列)。
        dest_dir:
            保存先ディレクトリ。存在しない場合は作成する。
        filename:
            保存ファイル名を指定したい場合。省略時は URL から自動決定。
        overwrite:
            既に同名ファイルが存在する場合に上書きするかどうか。
        progress_callback:
            ``callback(downloaded_bytes, total_bytes_or_None)`` の形式で呼ばれる
            任意のコールバック。

        Returns
        -------
        str
            保存したファイルの絶対パス。
        """
        if isinstance(entry, ZerochanEntry):
            url = entry.full_image_url
            default_name = entry.filename
        elif isinstance(entry, str) and entry.startswith("http"):
            url = entry
            default_name = url.rsplit("/", 1)[-1]
        else:
            fetched = self.get_entry(entry)
            url = fetched.full_image_url
            default_name = fetched.filename

        if not url:
            raise ZerochanError("ダウンロード対象の画像 URL を特定できませんでした。")

        os.makedirs(dest_dir, exist_ok=True)
        out_name = filename or default_name
        out_path = os.path.abspath(os.path.join(dest_dir, out_name))

        if os.path.exists(out_path) and not overwrite:
            return out_path

        self._throttle()
        try:
            resp = self.session.get(url, stream=True, timeout=self.timeout)
            try:
                if not resp.ok:
                    raise ZerochanHTTPError(...)
                total = resp.headers.get("Content-Length")
                total = int(total) if total is not None else None
                downloaded = 0
                tmp_path = out_path + ".part"
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
                os.replace(tmp_path, out_path)
            except requests.RequestException as exc:
                raise ZerochanHTTPError(f"画像のダウンロード中にエラーが発生しました: {exc}", url=url) from exc
            finally:
                resp.close()
        except requests.RequestException as exc:
            raise ZerochanHTTPError(f"画像のダウンロード中にエラーが発生しました: {exc}", url=url) from exc

        return out_path

    def download_search_results(
        self,
        tag: Union[str, Sequence[str]],
        dest_dir: str = ".",
        max_images: int = 20,
        strict: bool = False,
        overwrite: bool = False,
        progress_callback=None,
    ) -> List[str]:
        """タグ検索を行い、上位 N 件を一括ダウンロードする便利メソッド。

        ``tag`` には単一タグ (``"Genshin Impact"``) だけでなく、複数タグの
        リスト/タプル (``["Genshin Impact", "Klee"]``) も渡せる。複数タグを渡した
        場合は :meth:`search_multi` による AND 検索（すべてのタグを含むエントリの
        み）が行われる。この場合 ``strict`` オプションは無視される（Zerochan の
        複数タグ検索エンドポイントが strict モードに対応していないため）。

        内部で :meth:`iter_search` を使ってエントリ ID を集め、それぞれ
        :meth:`get_entry` → :meth:`download` する。JSON API のレスポンス構造に
        依存する部分があるため、IDが取れない場合は ``ZerochanParseError`` を送出する
        代わりにスキップし、最終的にダウンロードできたパスのみを返す。
        """
        is_multi = not isinstance(tag, str)
        search_kwargs = {} if is_multi else {"strict": strict}

        saved_paths: List[str] = []
        count = 0
        for item in self.iter_search(tag, **search_kwargs):
            if count >= max_images:
                break
            entry_id = self._extract_id(item)
            if entry_id is None:
                continue
            try:
                entry = self.get_entry(entry_id)
                path = self.download(
                    entry, dest_dir=dest_dir, overwrite=overwrite, progress_callback=progress_callback
                )
                saved_paths.append(path)
                count += 1
            except ZerochanError:
                # 1件の失敗で全体を止めない。会員限定・削除済みなどをスキップ。
                continue
        return saved_paths

    @staticmethod
    def _extract_id(item: Union[dict, int, str]) -> Optional[Union[int, str]]:
        if isinstance(item, (int, str)):
            return item
        if isinstance(item, dict):
            for key in ("id", "post_id", "entry_id"):
                if key in item:
                    return item[key]
        return None