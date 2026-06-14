"""
美股全市场数据预取脚本。

功能：
1. 通过 akshare stock_us_spot_em() 获取全部美股列表
2. 逐只下载日线数据（使用 akshare stock_us_daily）
3. 保存至 data/us_prices_all/

运行：
    python scripts/prefetch/prefetch_us_all.py

注意：
- akshare stock_us_daily 对中国 IP 可能受限，失败会记录到 prefetch_us_failed.txt
- 备选：yfinance（需另行安装）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import quant_system  # noqa: F401 — 触发 curl_cffi TLS 补丁，绕过 Clash 拦阻
import akshare as ak
import pandas as pd

FLOOR_DATE = "2018-01-01"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "us_prices_all"


def fetch_stock(code: str) -> pd.DataFrame:
    """下载单只美股日线。"""
    df = ak.stock_us_daily(symbol=code, adjust="")
    # akshare 可能返回中/英文列名
    cn_map = {"日期": "date", "开盘": "open", "最高": "high",
              "最低": "low", "收盘": "close", "成交量": "volume"}
    df = df.rename(columns=cn_map)
    need = ["date", "open", "high", "low", "close", "volume"]
    df = df[need].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["date"] >= FLOOR_DATE].reset_index(drop=True)
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== 获取全美股列表 ===")
    # 用 sina 端点 (stock_us_spot)；em 变体走 push2 在本机 Clash 网络层被拦阻
    spot = ak.stock_us_spot()
    codes = spot["symbol"].tolist()
    names = dict(zip(spot["symbol"], spot["cname"]))
    print(f"全美股数量: {len(codes)}")

    # 过滤已有缓存
    existing = {c for c in codes if (OUT_DIR / f"{c}.csv").exists()}
    todo = [c for c in codes if c not in existing]
    print(f"已缓存: {len(existing)}, 待下载: {len(todo)}")

    failed = []
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        try:
            df = fetch_stock(code)
            if df.empty:
                failed.append((code, "empty"))
            else:
                df.to_csv(OUT_DIR / f"{code}.csv", index=False, encoding="utf-8-sig")
        except Exception as e:
            # 提取前面的错误信息避免超长文件名
            failed.append((code, str(e)[:80]))

        if i % 50 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            print(
                f"  [{i:>5}/{len(todo)}] {code} {names.get(code, '?')}  "
                f"elapsed {elapsed/60:.1f}m  rate {rate:.2f}/s  "
                f"ETA {eta/60:.0f}m  失败 {len(failed)}",
                flush=True,
            )
        time.sleep(0.2)  # akshare 频控

    elapsed = time.time() - t0
    print(f"\nDONE: {len(todo)} fetched, {len(failed)} failed, {elapsed/60:.1f}m")
    if failed:
        failed_path = OUT_DIR.parent / "prefetch_us_failed.txt"
        failed_path.write_text("\n".join(f"{c}\t{e}" for c, e in failed), encoding="utf-8")
        print(f"失败列表: {failed_path}")


if __name__ == "__main__":
    main()
