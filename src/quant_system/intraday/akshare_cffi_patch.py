"""akshare curl_cffi monkeypatch — 绕过 Clash/系统代理 TLS 指纹拦阻.

问题: macOS 系统代理 (127.0.0.1:7897) 开启时 Python `requests` 库的 TLS
指纹被 eastmoney 服务器 reject (RemoteDisconnected / ProxyError).
akshare 内部硬绑 `requests.get()` 和 `request_with_retry()`, 无法从外部注入.

方案: 本模块在 import 时自动全局替换 `requests.get` 和 akshare 内部所有
`request_with_retry` 引用为 `curl_cffi` 版本 (Chrome124 TLS impersonation +
explicit empty proxy bypass).

用法: 在 **任何 akshare import 之前** import 本模块:
    import quant_system.intraday.akshare_cffi_patch  # noqa — side-effect import
    import akshare as ak  # 之后所有调用自动走 curl_cffi

已知限制: 82.push2.eastmoney.com (stock_zh_a_spot_em) 在本机网络层被拦
(系统 curl --noproxy '*' 也失败), 不归本模块修. push2his.eastmoney.com
(stock_zh_a_hist 等 daily 主力函数) 正常.
"""
from __future__ import annotations

import time as _time
import random as _random

from curl_cffi import requests as _cffi


def _cffi_get(url: str, params=None, **kwargs):
    """requests.get 的 curl_cffi 替代 (Chrome124 impersonate, 空代理)."""
    timeout = kwargs.pop("timeout", 30)
    # Keep only kwargs that requests.get supports but cffi doesn't need
    kwargs.pop("proxies", None)
    kwargs.pop("verify", None)
    kwargs.pop("cert", None)
    return _cffi.get(
        url, params=params, timeout=timeout,
        impersonate="chrome124",
        proxies={"http": "", "https": ""},
    )


def _cffi_request_with_retry(
    url: str,
    params=None,
    timeout: int = 15,
    max_retries: int = 3,
    base_delay: float = 1.0,
    random_delay_range: tuple = (0.5, 1.5),
):
    """akshare request_with_retry 的 curl_cffi 替代."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = _cffi.get(
                url, params=params or {}, timeout=timeout,
                impersonate="chrome124",
                proxies={"http": "", "https": ""},
            )
            r.raise_for_status()
            return r
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + _random.uniform(
                    *random_delay_range
                )
                _time.sleep(delay)
    raise last_exc


def _apply() -> None:
    """应用全局 monkeypatch (import 时自动调用)."""
    import requests as _orig_requests

    # 1. 全局替换 requests.get (akshare 函数直接调 requests.get(url, ...) 的路径)
    _orig_requests.get = _cffi_get  # type: ignore[assignment]

    # 2. 替换 akshare 内部的 request_with_retry 引用 (fetch_paginated_data 等路径)
    _patch_akshare_module("akshare.utils.request", "request_with_retry")
    _patch_akshare_module("akshare.utils.func", "request_with_retry")

    # 3. 其他少数直接 import request_with_retry 的模块
    for mod_name in (
        "akshare.stock_feature.stock_value_em",
        "akshare.stock_feature.stock_info",
        "akshare.qdii.qdii_jsl",
    ):
        _patch_akshare_module(mod_name, "request_with_retry")


def _patch_akshare_module(mod_name: str, attr: str) -> None:
    """给已 import 的 akshare 模块替换 attr; 若未 import 则 hook import."""
    import sys
    if mod_name in sys.modules:
        setattr(sys.modules[mod_name], attr, _cffi_request_with_retry)


_apply()
