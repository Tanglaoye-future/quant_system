"""
NASDAQ 100 数据预取脚本。

功能：
1. 使用内置 NASDAQ 100 成份股列表（静态；须定期更新）
2. 通过 akshare 下载每只股票日线数据（格式：date,open,high,low,close,volume）
3. 下载 QQQ ETF 日线作为 NDX 基准代理
4. 保存至 data/us_prices/

运行：
    python scripts/prefetch_us_universe.py

完成后在 config.yaml 中确认：
    data:
      us_market:
        daily_dir: "./data/us_prices"
        index_daily_csv: "./data/us_prices/NDX_index.csv"
        constituents_csv: "./data/us_prices/nasdaq100_constituents.csv"
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

FLOOR_DATE = "2018-01-01"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "us_prices"

# NASDAQ 100 成份股（2025 年版；每年调整一次，请参照 QQQ 官方持仓更新）
# 来源: Invesco QQQ ETF 持仓（https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=Investor&ticker=QQQ）
NASDAQ100_TICKERS: list[tuple[str, str]] = [
    ("AAPL",  "Apple Inc"),
    ("MSFT",  "Microsoft Corp"),
    ("NVDA",  "NVIDIA Corp"),
    ("AMZN",  "Amazon.com Inc"),
    ("META",  "Meta Platforms Inc"),
    ("GOOGL", "Alphabet Inc Class A"),
    ("GOOG",  "Alphabet Inc Class C"),
    ("TSLA",  "Tesla Inc"),
    ("AVGO",  "Broadcom Inc"),
    ("COST",  "Costco Wholesale Corp"),
    ("NFLX",  "Netflix Inc"),
    ("QCOM",  "QUALCOMM Inc"),
    ("AMD",   "Advanced Micro Devices"),
    ("TMUS",  "T-Mobile US Inc"),
    ("PEP",   "PepsiCo Inc"),
    ("INTU",  "Intuit Inc"),
    ("ADBE",  "Adobe Inc"),
    ("CSCO",  "Cisco Systems Inc"),
    ("AMGN",  "Amgen Inc"),
    ("TXN",   "Texas Instruments"),
    ("HON",   "Honeywell International"),
    ("ISRG",  "Intuitive Surgical Inc"),
    ("AMAT",  "Applied Materials Inc"),
    ("ADP",   "Automatic Data Processing"),
    ("BKNG",  "Booking Holdings Inc"),
    ("VRTX",  "Vertex Pharmaceuticals"),
    ("REGN",  "Regeneron Pharmaceuticals"),
    ("MU",    "Micron Technology Inc"),
    ("GILD",  "Gilead Sciences Inc"),
    ("LRCX",  "Lam Research Corp"),
    ("ADI",   "Analog Devices Inc"),
    ("MDLZ",  "Mondelez International"),
    ("PANW",  "Palo Alto Networks Inc"),
    ("KLAC",  "KLA Corp"),
    ("KDP",   "Keurig Dr Pepper Inc"),
    ("SNPS",  "Synopsys Inc"),
    ("CDNS",  "Cadence Design Systems"),
    ("MELI",  "MercadoLibre Inc"),
    ("ASML",  "ASML Holding NV"),
    ("MCHP",  "Microchip Technology"),
    ("PAYX",  "Paychex Inc"),
    ("FTNT",  "Fortinet Inc"),
    ("ROST",  "Ross Stores Inc"),
    ("ODFL",  "Old Dominion Freight Line"),
    ("CEG",   "Constellation Energy Corp"),
    ("FAST",  "Fastenal Co"),
    ("DXCM",  "DexCom Inc"),
    ("CRWD",  "CrowdStrike Holdings Inc"),
    ("CSGP",  "CoStar Group Inc"),
    ("MAR",   "Marriott International"),
    ("IDXX",  "IDEXX Laboratories Inc"),
    ("EXC",   "Exelon Corp"),
    ("WDAY",  "Workday Inc"),
    ("BIIB",  "Biogen Inc"),
    ("ROP",   "Roper Technologies Inc"),
    ("VRSK",  "Verisk Analytics Inc"),
    ("DLTR",  "Dollar Tree Inc"),
    ("FANG",  "Diamondback Energy Inc"),
    ("CTAS",  "Cintas Corp"),
    ("EA",    "Electronic Arts Inc"),
    ("TTD",   "The Trade Desk Inc"),
    ("NXPI",  "NXP Semiconductors NV"),
    ("PCAR",  "PACCAR Inc"),
    ("CTSH",  "Cognizant Technology Solutions"),
    ("ORLY",  "O'Reilly Automotive Inc"),
    ("ZS",    "Zscaler Inc"),
    ("SBUX",  "Starbucks Corp"),
    ("XEL",   "Xcel Energy Inc"),
    ("ANSS",  "ANSYS Inc"),
    ("BKR",   "Baker Hughes Co"),
    ("CSX",   "CSX Corp"),
    ("GEHC",  "GE HealthCare Technologies"),
    ("TEAM",  "Atlassian Corp"),
    ("DDOG",  "Datadog Inc"),
    ("EBAY",  "eBay Inc"),
    ("WBD",   "Warner Bros Discovery"),
    ("ILMN",  "Illumina Inc"),
    ("KHC",   "Kraft Heinz Co"),
    ("ALGN",  "Align Technology Inc"),
    ("CCEP",  "Coca-Cola Europacific Partners"),
    ("ZM",    "Zoom Video Communications"),
    ("MNST",  "Monster Beverage Corp"),
    ("TTWO",  "Take-Two Interactive Software"),
    ("LULU",  "Lululemon Athletica Inc"),
    ("ON",    "ON Semiconductor Corp"),
    ("GFS",   "GlobalFoundries Inc"),
    ("CHTR",  "Charter Communications Inc"),
    ("ABNB",  "Airbnb Inc"),
    ("PYPL",  "PayPal Holdings Inc"),
    ("MRNA",  "Moderna Inc"),
    ("PDD",   "PDD Holdings Inc"),
    ("PLTR",  "Palantir Technologies Inc"),
    ("ARM",   "ARM Holdings plc"),
    ("APP",   "AppLovin Corp"),
    ("AZN",   "AstraZeneca PLC"),
    ("DASH",  "DoorDash Inc"),
    ("EXPE",  "Expedia Group Inc"),
    ("CDW",   "CDW Corp"),
    ("CINF",  "Cincinnati Financial Corp"),
]


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
    """下载单只美股日线，返回标准列：date,open,high,low,close,volume。"""
    df = ak.stock_us_daily(symbol=ticker, adjust="")
    return _normalize_df(df)


def fetch_qqq_as_index() -> pd.DataFrame:
    """下载 QQQ ETF 日线作为 NDX 基准代理，返回标准列。"""
    df = ak.stock_us_daily(symbol="QQQ", adjust="")
    return _normalize_df(df)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 保存成份股列表 ---
    cons_df = pd.DataFrame(NASDAQ100_TICKERS, columns=["code", "name"])
    cons_path = OUT_DIR / "nasdaq100_constituents.csv"
    cons_df.to_csv(cons_path, index=False, encoding="utf-8-sig")
    print(f"成份股列表已保存: {cons_path}  ({len(cons_df)} 只)")

    tickers = [t for t, _ in NASDAQ100_TICKERS]

    # --- 下载个股 ---
    print(f"\n=== 下载个股日线至 {OUT_DIR} ===")
    ok, fail = 0, []
    for i, ticker in enumerate(tickers, 1):
        out_path = OUT_DIR / f"{ticker}.csv"
        if out_path.exists():
            print(f"[{i:3d}/{len(tickers)}] {ticker:<6s} 已存在，跳过")
            ok += 1
            continue
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
        time.sleep(0.5)

    # --- 下载 QQQ 指数代理 ---
    print("\n=== 下载 QQQ ETF 日线（NDX 基准代理） ===")
    idx_path = OUT_DIR / "NDX_index.csv"
    for attempt in range(3):
        try:
            df_idx = fetch_qqq_as_index()
            df_idx.to_csv(idx_path, index=False, encoding="utf-8-sig")
            print(f"QQQ  {len(df_idx)} 行  {df_idx['date'].iloc[0]} ~ {df_idx['date'].iloc[-1]}")
            break
        except Exception as e:
            if attempt < 2:
                print(f"QQQ 下载失败，重试 ({attempt+1}/3): {e}")
                time.sleep(5)
            else:
                print(f"QQQ 下载失败: {e}")

    # --- 汇总 ---
    print(f"\n=== 完成 ===")
    print(f"成功: {ok}/{len(tickers)}")
    if fail:
        print(f"失败: {fail}")
    print(f"\nconfig.yaml 中应已配置（prefetch 脚本已写入 data/us_prices/）：")
    print(f"  data:")
    print(f"    us_market:")
    print(f"      daily_dir: \"./data/us_prices\"")
    print(f"      index_daily_csv: \"./data/us_prices/NDX_index.csv\"")
    print(f"      constituents_csv: \"./data/us_prices/nasdaq100_constituents.csv\"")


if __name__ == "__main__":
    main()
