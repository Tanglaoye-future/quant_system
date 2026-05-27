"""
S&P 500 数据预取脚本。

功能：
1. 从 GitHub 公开镜像拉取 S&P 500 成份股列表（datasets/s-and-p-500-companies）
2. 通过 akshare stock_us_daily 下载每只股票日线（complement: NASDAQ100 已有的复用）
3. 下载 SPY ETF 日线作为 SPX 基准代理
4. 保存至 data/sp500_prices/

运行：
    venv/bin/python scripts/prefetch/prefetch_sp500_universe.py

完成后 config/markets/us_share.yaml 应配 sp500_market 字典指向 data/sp500_prices/。

注意：
- 503 ticker × akshare 平均 2-3 秒/只 → 25-40 分钟
- 已存在 csv 跳过；中断重跑可断点续传
- US fundamentals 走 yfinance lazy fetch（首次回测时才拉）
"""
from __future__ import annotations

import io
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


import akshare as ak
import pandas as pd

FLOOR_DATE = "2018-01-01"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "sp500_prices"

CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


def fetch_constituents() -> pd.DataFrame:
    """从 GitHub 拉 SP500 成分股列表（503 ticker，含 GICS sector）。
    返回列：code, name, sector"""
    req = urllib.request.Request(CONSTITUENTS_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=20).read()
    df = pd.read_csv(io.BytesIO(raw))
    # 标准化字段名
    df = df.rename(columns={
        "Symbol": "code",
        "Security": "name",
        "GICS Sector": "sector",
    })[["code", "name", "sector"]].copy()
    # akshare stock_us_daily 不接受 BRK.B / BF.B 这种带 . 的代码，需要转换为 BRK-B
    df["code"] = df["code"].str.replace(".", "-", regex=False)
    return df.reset_index(drop=True)


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """统一 akshare US 日线列名（中/英文均兼容），返回标准列 date,open,high,low,close,volume。"""
    cn_map = {
        "日期": "date", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
    }
    df = df.rename(columns=cn_map)
    need = ["date", "open", "high", "low", "close", "volume"]
    df = df[need].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= FLOOR_DATE].reset_index(drop=True)
    return df


def fetch_stock(ticker: str) -> pd.DataFrame:
    df = ak.stock_us_daily(symbol=ticker, adjust="")
    return _normalize_df(df)


def fetch_spy_as_index() -> pd.DataFrame:
    df = ak.stock_us_daily(symbol="SPY", adjust="")
    return _normalize_df(df)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 拉成分股列表 ---
    print("拉取 SP500 成分股列表...")
    cons = fetch_constituents()
    cons_path = OUT_DIR / "sp500_constituents.csv"
    cons.to_csv(cons_path, index=False, encoding="utf-8-sig")
    print(f"成分股列表已保存: {cons_path}  ({len(cons)} 只)")

    tickers = cons["code"].tolist()

    # --- 下载个股日线 ---
    print(f"\n=== 下载个股日线至 {OUT_DIR} ===")
    ok, skip, fail = 0, 0, []
    for i, ticker in enumerate(tickers, 1):
        out_path = OUT_DIR / f"{ticker}.csv"
        if out_path.exists():
            skip += 1
            ok += 1
            continue
        attempt = 0
        for attempt in range(3):
            try:
                df = fetch_stock(ticker)
                df.to_csv(out_path, index=False, encoding="utf-8-sig")
                print(f"[{i:3d}/{len(tickers)}] {ticker:<6s}  {len(df)} 行  {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
                ok += 1
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(5)
                else:
                    print(f"[{i:3d}/{len(tickers)}] {ticker:<6s}  FAIL: {e}")
                    fail.append(ticker)
        time.sleep(0.3)

    # --- SPY 指数代理 ---
    print("\n=== 下载 SPY ETF 日线（SPX 基准代理） ===")
    idx_path = OUT_DIR / "SPX_index.csv"
    if idx_path.exists():
        print(f"  已存在，跳过: {idx_path}")
    else:
        for attempt in range(3):
            try:
                df_idx = fetch_spy_as_index()
                df_idx.to_csv(idx_path, index=False, encoding="utf-8-sig")
                print(f"SPY  {len(df_idx)} 行  {df_idx['date'].iloc[0]} ~ {df_idx['date'].iloc[-1]}")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"SPY 下载失败，重试 ({attempt+1}/3): {e}")
                    time.sleep(5)
                else:
                    print(f"SPY 下载失败: {e}")

    # --- 汇总 ---
    print(f"\n=== 完成 ===")
    print(f"成功: {ok}/{len(tickers)}  (跳过已存在: {skip})")
    if fail:
        print(f"失败 ({len(fail)}): {fail[:20]}{' ...' if len(fail) > 20 else ''}")


if __name__ == "__main__":
    main()
