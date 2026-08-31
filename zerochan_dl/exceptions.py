"""zerochan_dl の例外クラス群。"""


class ZerochanError(Exception):
    """このライブラリが送出する例外の基底クラス。"""


class ZerochanHTTPError(ZerochanError):
    """HTTP リクエストが失敗した場合（4xx/5xx など）。"""

    def __init__(self, message, status_code=None, url=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class ZerochanParseError(ZerochanError):
    """レスポンス（JSON もしくは HTML）の解析に失敗した場合。

    Zerochan 側のページ構造や API のレスポンス形式が変わった可能性があります。
    """


class RateLimitExceeded(ZerochanError):
    """サーバー側のレート制限 (60 req/min) に達したと判断された場合。"""
