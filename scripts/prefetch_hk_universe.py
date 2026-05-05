"""
港股 HSCHK100 数据预取脚本。

功能：
1. 从恒生官网 factsheet PDF 解析 HSCHK100 TOP 50 成份股
2. 通过 akshare 下载每只股票日线数据（格式：date,open,high,low,close,volume）
3. 下载 HSML100（恒生中国香港上市100）指数日线，补全 volume=0
4. 保存至 data/hk_prices/

运行：
    python scripts/prefetch_hk_universe.py

完成后在 config.yaml 中配置：
    data:
      hang_seng_indexes:
        hk_constituent_daily_dir: "./data/hk_prices"
        hschk100_index_daily_csv: "./data/hk_prices/HSCHK100_index.csv"
        allow_factsheet_top50_only: true
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import akshare as ak
import pandas as pd

from quant_system.config import load_config
from quant_system.data.hang_seng_indexes import load_hschk100_constituents

FLOOR_DATE = "2018-01-01"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "hk_prices"


def fetch_stock(code: str) -> pd.DataFrame:
    """下载单只港股日线，返回标准列：date,open,high,low,close,volume。"""
    df = ak.stock_hk_daily(symbol=code, adjust="")
    df = df.rename(columns={"日期": "date", "开盘": "open", "最高": "high",
                             "最低": "low", "收盘": "close", "成交量": "volume"})
    # akshare stock_hk_daily 已经返回英文列名
    need = ["date", "open", "high", "low", "close", "volume"]
    df = df[need].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= FLOOR_DATE].reset_index(drop=True)
    return df


def fetch_index() -> pd.DataFrame:
    """下载 HSML100 指数日线，补 volume=0，返回标准列。"""
    df = ak.stock_hk_index_daily_em(symbol="HSML100")
    df = df.rename(columns={"latest": "close"})
    df["volume"] = 0.0
    need = ["date", "open", "high", "low", "close", "volume"]
    df = df[need].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= FLOOR_DATE].reset_index(drop=True)
    return df


def main() -> None:
    cfg = load_config()
    hsi_cfg = cfg.get("data", "hang_seng_indexes", default={}) or {}

    print("=== 获取 HSCHK100 成份股列表 ===")
    constituents = load_hschk100_constituents(hsi_cfg)
    codes = constituents["code"].tolist()
    print(f"成份股数量: {len(codes)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 下载个股 ---
    print(f"\n=== 下载个股日线至 {OUT_DIR} ===")
    ok, fail = 0, []
    for i, code in enumerate(codes, 1):
        out_path = OUT_DIR / f"{code}.csv"
        if out_path.exists():
            print(f"[{i:3d}/{len(codes)}] {code} 已存在，跳过")
            ok += 1
            continue
        try:
            df = fetch_stock(code)
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            print(f"[{i:3d}/{len(codes)}] {code}  {len(df)} 行  {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
            ok += 1
        except Exception as e:
            print(f"[{i:3d}/{len(codes)}] {code}  FAIL: {e}")
            fail.append(code)
        time.sleep(0.3)  # 避免频控

    # --- 下载指数 ---
    print("\n=== 下载 HSML100 指数日线 ===")
    idx_path = OUT_DIR / "HSCHK100_index.csv"
    try:
        df_idx = fetch_index()
        df_idx.to_csv(idx_path, index=False, encoding="utf-8-sig")
        print(f"HSML100 指数  {len(df_idx)} 行  {df_idx['date'].iloc[0]} ~ {df_idx['date'].iloc[-1]}")
    except Exception as e:
        print(f"HSML100 指数 FAIL: {e}")

    # --- 汇总 ---
    print(f"\n=== 完成 ===")
    print(f"成功: {ok}/{len(codes)}")
    if fail:
        print(f"失败: {fail}")
    print(f"\n完成后请在 config.yaml 中添加：")
    print(f"  data:")
    print(f"    hang_seng_indexes:")
    print(f"      hk_constituent_daily_dir: \"./data/hk_prices\"")
    print(f"      hschk100_index_daily_csv: \"./data/hk_prices/HSCHK100_index.csv\"")
    print(f"      allow_factsheet_top50_only: true")


if __name__ == "__main__":
    main()
