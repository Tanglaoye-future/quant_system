"""
恒生指数公司（Hang Seng Indexes Company）官方数据源接入。

说明（合规与边界）：
- **成份股**：优先读取本地 CSV（来自恒生《指数数据产品文件》订阅，见 config `data.hang_seng_indexes`）；
  若未配置，则从恒生官网 **官方指数概览 PDF**（HSCHK100 英文 factsheet）解析「CONSTITUENTS (TOP 50)」表格行（仅 50 只）。
  若需 **完整 100 只** HSCHK100 成份，须向恒生订阅数据产品并将全量成份表路径写入 `full_constituents_csv`，或联系 info@hsi.com.hk。
- **个股 / 指数日线**：恒生指数公司不向本仓库提供免费的公共 REST 行情接口；若已订阅含 **成份股/指数点位** 的日频文件，
  请放入 `hk_constituent_daily_dir`（每只股票一个 CSV）及可选 `hschk100_index_daily_csv`。未配置时 `get_daily(hk_share)` 会显式报错，
  避免静默回退到非恒生数据源。

官方资料：
- HSCHK100（恒生中国内地企业（香港上市）100，Bloomberg: HSML100）概览 PDF（英文）:
  https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hschk100e.pdf
- 数据产品 / 订阅: https://www.hsi.com.hk/en-hk/solutions/data-analytics/our-data-analytics-offerings/
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# 恒生官网公开的 HSCHK100 英文概览（含 TOP 50 成份表）
DEFAULT_HSCHK100_FACTSHEET_PDF_EN = (
    "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hschk100e.pdf"
)

_STOCK_LINE_RE = re.compile(
    r"^(\d{4,5})\s+([A-Z0-9]{12})\s+(.+)$",
)


class HangSengDataError(RuntimeError):
    """恒生数据源未就绪或数据不完整。"""


def _normalize_hk_stock_code_5(raw: str) -> str:
    s = re.sub(r"\D", "", str(raw).strip())
    if not s:
        raise ValueError(f"无效港股代码: {raw!r}")
    n = int(s)
    return f"{n % 100000:05d}"


def parse_constituent_lines_from_factsheet_text(text: str) -> pd.DataFrame:
    """从 factsheet 抽取文本中解析「Stock Code + ISIN + Name」行（与官方 PDF 表格一致）。"""
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        m = _STOCK_LINE_RE.match(line)
        if not m:
            continue
        code_raw, _isin, rest = m.group(1), m.group(2), m.group(3)
        rest = rest.strip()
        parts = rest.rsplit(" ", 1)
        if len(parts) == 2:
            try:
                float(parts[1])
                name = parts[0].strip()
            except ValueError:
                name = rest
        else:
            name = rest
        if len(name) > 200:
            name = name[:200]
        rows.append((_normalize_hk_stock_code_5(code_raw), name))
    if not rows:
        raise HangSengDataError("未能从恒生 factsheet 文本中解析出任何成份行")
    # 按代码去重，保持顺序
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for c, n in rows:
        if c in seen:
            continue
        seen.add(c)
        out.append((c, n))
    return pd.DataFrame(out, columns=["code", "name"])


def fetch_hschk100_factsheet_pdf_bytes(url: str = DEFAULT_HSCHK100_FACTSHEET_PDF_EN) -> bytes:
    r = requests.get(
        url,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (compatible; quant_system/1.0; +https://www.hsi.com.hk)"},
    )
    r.raise_for_status()
    return r.content


def constituents_from_official_factsheet_pdf(
    url: str = DEFAULT_HSCHK100_FACTSHEET_PDF_EN,
) -> pd.DataFrame:
    """下载并解析恒生官方 HSCHK100 英文 factsheet PDF（当前公开版仅含 TOP 50 成份）。"""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise HangSengDataError(
            "解析恒生 PDF 需要安装 pypdf：pip install pypdf",
        ) from e
    pdf = fetch_hschk100_factsheet_pdf_bytes(url)
    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_constituent_lines_from_factsheet_text(text)


def _read_full_constituents_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    cols = {c.lower().strip(): c for c in df.columns}
    code_key = None
    name_key = None
    for k in ("stock code", "code", "股票代码", "证券代码", "成份券代码"):
        if k in cols:
            code_key = cols[k]
            break
    for k in ("company name", "name", "证券简称", "成份券名称", "股票名称"):
        if k in cols:
            name_key = cols[k]
            break
    if code_key is None or name_key is None:
        raise HangSengDataError(
            f"成份 CSV 须包含股票代码列与名称列（如 Stock Code, Company Name），当前列: {list(df.columns)}",
        )
    out = pd.DataFrame({
        "code": df[code_key].map(_normalize_hk_stock_code_5),
        "name": df[name_key].astype(str),
    })
    return out.drop_duplicates(subset=["code"]).reset_index(drop=True)


def load_hschk100_constituents(hsi_cfg: dict[str, Any] | None) -> pd.DataFrame:
    """
    HSCHK100（config 中 hk universe `hs100`）成份股，全部来自恒生公开/订阅数据。
    """
    hsi_cfg = hsi_cfg or {}
    full_csv = hsi_cfg.get("full_constituents_csv") or ""
    if full_csv:
        p = Path(full_csv)
        if not p.is_absolute():
            from quant_system.config import PROJECT_ROOT

            p = PROJECT_ROOT / p
        if p.is_file():
            return _read_full_constituents_csv(p)

    pdf_url = hsi_cfg.get("official_factsheet_pdf_en") or DEFAULT_HSCHK100_FACTSHEET_PDF_EN
    df_pdf = constituents_from_official_factsheet_pdf(url=pdf_url)
    allow_partial = bool(hsi_cfg.get("allow_factsheet_top50_only", False))
    if len(df_pdf) < 90 and not allow_partial:
        raise HangSengDataError(
            f"恒生官方 factsheet 当前仅解析到 {len(df_pdf)} 只成份（公开版为 TOP 50）。"
            f"请在 config.yaml 设置 data.hang_seng_indexes.full_constituents_csv 指向恒生指数公司"
            f"《指数数据产品文件》中的完整 HSCHK100 成份表，或设置 allow_factsheet_top50_only: true 以仅使用官方 TOP50（研究用）。",
        )
    return df_pdf


def read_hk_constituent_daily_csv(daily_dir: Path, code: str) -> pd.DataFrame:
    """读取单只港股日线：目录下 {code}.csv，列须含 date, open, high, low, close, volume（全历史，供缓存切片）。"""
    path = daily_dir / f"{code}.csv"
    if not path.is_file():
        raise HangSengDataError(
            f"未找到恒生提供的个股日线文件: {path}（请将订阅数据导出为该路径）",
        )
    df = pd.read_csv(path, encoding="utf-8-sig")
    colmap = {c.lower().strip(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close", "volume")
    missing = [k for k in need if k not in colmap]
    if missing:
        raise HangSengDataError(f"{path} 缺少列 {missing}，当前: {list(df.columns)}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df[colmap["date"]]).dt.strftime("%Y-%m-%d"),
        "open": df[colmap["open"]].astype(float),
        "high": df[colmap["high"]].astype(float),
        "low": df[colmap["low"]].astype(float),
        "close": df[colmap["close"]].astype(float),
        "volume": df[colmap["volume"]].astype(float),
    })
    return out.sort_values("date").reset_index(drop=True)


def read_hschk100_index_daily_csv(path: Path) -> pd.DataFrame:
    """恒生 HSCHK100 指数日线 CSV：列 date, open, high, low, close, volume（与 A 股 index 接口对齐）。"""
    if not path.is_file():
        raise HangSengDataError(f"未找到恒生 HSCHK100 指数日线文件: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    colmap = {c.lower().strip(): c for c in df.columns}
    need = ("date", "open", "high", "low", "close", "volume")
    missing = [k for k in need if k not in colmap]
    if missing:
        raise HangSengDataError(f"{path} 缺少列 {missing}，当前: {list(df.columns)}")
    out = pd.DataFrame({
        "date": pd.to_datetime(df[colmap["date"]]).dt.strftime("%Y-%m-%d"),
        "open": df[colmap["open"]].astype(float),
        "high": df[colmap["high"]].astype(float),
        "low": df[colmap["low"]].astype(float),
        "close": df[colmap["close"]].astype(float),
        "volume": df[colmap["volume"]].astype(float),
    })
    return out.sort_values("date").reset_index(drop=True)
