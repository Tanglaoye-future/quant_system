"""quant_system package."""
import os
import socket

# A 股数据源都是国内域名, 不应走代理.
# 加入 NO_PROXY, requests/urllib3 就绕过 HTTP_PROXY/HTTPS_PROXY 直连.
_DOMESTIC_HOSTS = [
    "eastmoney.com", "push2his.eastmoney.com", "datacenter-web.eastmoney.com",
    "sina.com.cn", "finance.sina.com.cn",
    "sse.com.cn", "szse.cn", "cninfo.com.cn",
    "10jqka.com.cn", "iwencai.com",
    "akshare.akfamily.xyz",
]
_existing = os.environ.get("NO_PROXY", "")
_merged = ",".join(filter(None, [_existing] + _DOMESTIC_HOSTS))
os.environ["NO_PROXY"] = _merged
os.environ["no_proxy"] = _merged

# akshare 内部用 requests 但不暴露 timeout 参数, 默认无超时.
# 设全局 socket 超时, 避免单只股票拉数据卡死整个脚本.
socket.setdefaulttimeout(15)

# PR3.5 — curl_cffi TLS 绕过 (Clash/系统代理兼容).
# requests 库的 TLS 指纹被 eastmoney reject; curl_cffi impersonate Chrome.
# try/except 安全: curl_cffi 未安装时静默回退 (不影响 package import).
try:
    from quant_system.intraday import akshare_cffi_patch as _ak_cffi  # noqa: F401
except ImportError:
    pass

__version__ = "0.1.2"
