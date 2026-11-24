"""
公司解散登記清冊（2021–2025）資料體檢與驗算腳本

用途：
    在 Power BI 建模之前，先用 Python 對 60 個月的原始 CSV 做資料品質檢查，
    並算出儀表板 KPI 的「驗算基準值」。Power BI 做出來的數字若和這裡不同，
    代表清理或 DAX 步驟有錯。

執行方式（在 repo 根目錄）：
    pip install pandas
    python analysis/profile_data.py

輸出：
    analysis/summary_stats.md
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUTPUT = ROOT / "analysis" / "summary_stats.md"

KEYWORDS = ["生技", "科技", "資訊", "餐飲", "營造", "工程", "建設",
            "投資", "顧問", "行銷", "設計", "貿易", "國際"]
CAP_BINS = [-1, 0, 1e5, 5e5, 1e6, 5e6, 1e7, 1e8, 1e13]
CAP_LABELS = ["0或缺漏", "10萬以下", "10-50萬", "50-100萬", "100-500萬",
              "500-1000萬", "1000萬-1億", "1億以上"]


def roc_to_date(value):
    """民國年 7 碼（如 0651208、1100104）轉西元日期；空值或格式錯誤回傳 NaT。"""
    if not isinstance(value, str) or not value.strip():
        return pd.NaT
    s = value.strip().zfill(7)
    try:
        return pd.Timestamp(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return pd.NaT


def load() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("*.csv"))
    frames = [
        pd.read_csv(f, dtype=str, encoding="utf-8-sig").assign(資料月份=f.stem)
        for f in files
    ]
    df = pd.concat(frames, ignore_index=True)
    df["資料年度"] = df["資料月份"].str[:4]
    df["設立日期"] = df["核准設立日期"].map(roc_to_date)
    df["解散日期"] = df["核准解散日期"].map(roc_to_date)
    df["資本額"] = pd.to_numeric(df["資本額"], errors="coerce")
    df["存活年數"] = ((df["解散日期"] - df["設立日期"]).dt.days / 365.25).round(2)
    df["短命公司"] = df["存活年數"] < 1

    addr = df["公司所在地"].fillna("").str.strip()
    df["地址"] = addr.where(addr != "")
    df["縣市"] = df["地址"].str[:3].str.replace("^台", "臺", regex=True).fillna("地址缺漏")
    same_addr = df["地址"].map(df["地址"].value_counts())
    df["地址群聚"] = (same_addr >= 3) & df["地址"].notna()

    name = df["公司名稱"]
    df["公司型態"] = name.map(
        lambda n: "股份有限公司" if "股份有限公司" in n
        else ("有限公司" if "有限公司" in n else "其他"))
    df["產業關鍵字"] = name.map(lambda n: next((k for k in KEYWORDS if k in n), "其他"))
    df["資本額級距"] = pd.cut(df["資本額"].fillna(0), CAP_BINS, labels=CAP_LABELS)
    return df, len(files)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def build_report(df: pd.DataFrame, n_files: int) -> str:
    cap = df["資本額"]
    small = (cap > 0) & (cap <= 1e5)
    quality = (cap.fillna(0) == 0) | df["地址"].isna() | df["設立日期"].isna()
    lines = ["# 資料體檢與驗算基準", "",
             "由 `analysis/profile_data.py` 自動產生，請勿手動編輯。", "",
             "## 總覽", "",
             "| 項目 | 數值 |", "| --- | --- |",
             f"| 檔案數 | {n_files} 個月 |",
             f"| 總解散家數 | {len(df):,} |",
             f"| 平均資本額（排除 0） | {cap[cap > 0].mean():,.0f} 元 |",
             f"| 中位數資本額（排除 0） | {cap[cap > 0].median():,.0f} 元 |",
             f"| 平均存活年數 | {df['存活年數'].mean():.2f} 年 |",
             f"| 中位數存活年數 | {df['存活年數'].median():.2f} 年 |",
             f"| 短命公司（存活未滿 1 年） | {df['短命公司'].sum():,}（{pct(df['短命公司'].mean())}） |",
             f"| 資本額為 0 | {(cap == 0).sum():,} |",
             f"| 地址缺漏 | {df['地址'].isna().sum():,} |",
             f"| 設立日期缺漏 | {df['設立日期'].isna().sum():,} |",
             f"| 資料品質異常合計 | {quality.sum():,} |",
             f"| 重複統一編號 | {df['統一編號'].duplicated().sum():,} |",
             f"| 地址群聚（同址 ≥3 家）家數 | {df['地址群聚'].sum():,}（{df.loc[df['地址群聚'], '地址'].nunique():,} 個地址） |",
             ""]

    lines += ["## 逐年趨勢", "",
              "| 年度 | 解散家數 | 短命率 | 中位存活年數 | 群聚地址占比 | 資本 10 萬以下占比 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for year, g in df.groupby("資料年度"):
        g_small = ((g["資本額"] > 0) & (g["資本額"] <= 1e5)).mean()
        lines.append(f"| {year} | {len(g):,} | {pct(g['短命公司'].mean())} | "
                     f"{g['存活年數'].median():.1f} | {pct(g['地址群聚'].mean())} | {pct(g_small)} |")
    lines.append("")

    lines += ["## 資本額級距 × 短命率", "", "| 級距 | 家數 | 短命率 |", "| --- | --- | --- |"]
    for label, g in df.groupby("資本額級距", observed=True):
        lines.append(f"| {label} | {len(g):,} | {pct(g['短命公司'].mean())} |")
    lines.append("")

    lines += ["## 地址群聚 × 小資本（分解樹路徑）", "",
              "| 組別 | 家數 | 短命率 |", "| --- | --- | --- |",
              f"| 全部 | {len(df):,} | {pct(df['短命公司'].mean())} |",
              f"| 群聚地址 | {df['地址群聚'].sum():,} | {pct(df.loc[df['地址群聚'], '短命公司'].mean())} |",
              f"| 一般地址 | {(~df['地址群聚']).sum():,} | {pct(df.loc[~df['地址群聚'], '短命公司'].mean())} |",
              f"| 資本 10 萬以下 × 群聚地址 | {(small & df['地址群聚']).sum():,} | {pct(df.loc[small & df['地址群聚'], '短命公司'].mean())} |",
              f"| 資本 10 萬以下 × 一般地址 | {(small & ~df['地址群聚']).sum():,} | {pct(df.loc[small & ~df['地址群聚'], '短命公司'].mean())} |",
              ""]

    lines += ["## 產業關鍵字（依公司名稱）", "",
              "| 關鍵字 | 家數 | 短命率 | 中位存活年數 |", "| --- | --- | --- | --- |"]
    kw = df.groupby("產業關鍵字").agg(n=("短命公司", "size"), s=("短命公司", "mean"),
                                    m=("存活年數", "median")).sort_values("n", ascending=False)
    for k, r in kw.iterrows():
        lines.append(f"| {k} | {int(r.n):,} | {pct(r.s)} | {r.m:.1f} |")
    lines.append("")

    lines += ["## 縣市", "", "| 縣市 | 家數 | 短命率 |", "| --- | --- | --- |"]
    ct = df.groupby("縣市").agg(n=("短命公司", "size"), s=("短命公司", "mean")).sort_values("n", ascending=False)
    for c, r in ct.iterrows():
        lines.append(f"| {c} | {int(r.n):,} | {pct(r.s)} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    data, n = load()
    OUTPUT.write_text(build_report(data, n), encoding="utf-8")
    print(f"已輸出 {OUTPUT.relative_to(ROOT)}（{len(data):,} 筆）")
