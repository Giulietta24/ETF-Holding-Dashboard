import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

st.set_page_config(page_title="ETF Holdings Breakdown", layout="wide")

st.title("🔍 ETF Holdings Breakdown Dashboard")
st.caption("Holdings from stockanalysis.com · Prices & 52W via Yahoo Finance · Options Sentiment")

# ── Popular ETF quick-select ──────────────────────────────────────────────────
POPULAR = ["QQQ","SPY","VOO","XLK","SMH","XLE","XLF","XLV","ARKG","ICLN","ITA","PAVE","BOTZ","IBB","VNQ"]

with st.sidebar:
    st.header("⚙️ Settings")
    st.markdown("**Quick-pick a popular ETF:**")
    quick = st.selectbox("", ["(type your own below)"] + POPULAR)
    load_options = st.checkbox(
        "Load Options Sentiment",
        value=False,
        help="Fetches options chain for every holding — can take 1–3 minutes for large ETFs.",
    )
    st.divider()
    st.markdown("**Colour Guide — 52W Range %**")
    st.markdown("🟢 ≥ 60% Strong")
    st.markdown("🟡 35–60% Mid")
    st.markdown("🔴 < 35% Weak")
    if load_options:
        st.divider()
        st.markdown("**Colour Guide — P/C Ratio**")
        st.markdown("🟢 < 0.70 Bullish")
        st.markdown("🟡 0.70–0.85 Neutral")
        st.markdown("🔴 > 0.85 Bearish")

# ── Ticker input ──────────────────────────────────────────────────────────────
col_in, col_btn = st.columns([3, 1])
with col_in:
    default_val = quick if quick != "(type your own below)" else "QQQ"
    ticker_input = st.text_input("Enter ETF Ticker", value=default_val, placeholder="e.g. QQQ, SPY, XLK…").upper().strip()
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("🔎 Analyse ETF", use_container_width=True)

st.divider()

# ── Data fetchers ─────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

@st.cache_data(ttl=3600)
def get_holdings_stockanalysis(ticker: str) -> pd.DataFrame:
    """Scrape ETF holdings from stockanalysis.com — covers 3,000+ ETFs."""
    url = f"https://stockanalysis.com/etf/{ticker.lower()}/holdings/"
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(resp.text)
        if not tables:
            return pd.DataFrame()
        df = tables[0].copy()
        # Normalise column names
        df.columns = [str(c).strip() for c in df.columns]
        rename_map = {}
        for c in df.columns:
            cl = c.lower()
            if "symbol" in cl:                rename_map[c] = "Symbol"
            elif "company" in cl or "name" in cl: rename_map[c] = "Name"
            elif "weight" in cl or "%" in cl:  rename_map[c] = "Weight %"
            elif "share" in cl:               rename_map[c] = "Shares"
        df = df.rename(columns=rename_map)
        keep = [c for c in ["Symbol","Name","Weight %","Shares"] if c in df.columns]
        df = df[keep].dropna(subset=["Symbol"])
        df = df[df["Symbol"].str.match(r"^[A-Z]{1,5}$", na=False)]
        if "Weight %" in df.columns:
            df["Weight %"] = (
                pd.to_numeric(
                    df["Weight %"].astype(str).str.replace("%","", regex=False).str.strip(),
                    errors="coerce"
                )
            )
        df = df.reset_index(drop=True)
        return df
    except Exception as e:
        return pd.DataFrame(columns=["Symbol","Name","Weight %"])

@st.cache_data(ttl=1800)
def get_etf_meta(ticker: str):
    try:
        info = yf.Ticker(ticker).info
        return (
            info.get("longName", ticker),
            info.get("regularMarketPrice") or info.get("navPrice"),
            info.get("totalAssets"),
            info.get("annualReportExpenseRatio"),
            info.get("category","–"),
        )
    except Exception:
        return ticker, None, None, None, "–"

@st.cache_data(ttl=900)
def get_price_52w(symbols: list) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            price = round(fi.last_price, 2) if fi.last_price else None
            hi52  = round(fi.year_high,  2) if fi.year_high  else None
            lo52  = round(fi.year_low,   2) if fi.year_low   else None
            rng   = round((price - lo52) / (hi52 - lo52) * 100, 1) if (price and hi52 and lo52 and (hi52-lo52)>0) else None
            frhi  = round((price - hi52) / hi52 * 100, 2) if (price and hi52) else None
            rows.append({"Symbol": sym, "Price ($)": price, "52W Low": lo52,
                         "52W High": hi52, "52W Range %": rng, "% from 52W High": frhi})
        except Exception:
            rows.append({"Symbol": sym, "Price ($)": None, "52W Low": None,
                         "52W High": None, "52W Range %": None, "% from 52W High": None})
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600)
def get_put_call(symbols: list) -> dict:
    result = {}
    for sym in symbols:
        try:
            t     = yf.Ticker(sym)
            dates = t.options
            if not dates:
                result[sym] = None
                continue
            tp, tc = 0, 0
            for d in dates:
                chain  = t.option_chain(d)
                tp    += chain.puts["volume"].sum()
                tc    += chain.calls["volume"].sum()
            result[sym] = round(tp / tc, 3) if tc else None
        except Exception:
            result[sym] = None
    return result

# ── Styling helpers ───────────────────────────────────────────────────────────

def sentiment_label(r):
    if r is None or pd.isna(r): return "–"
    if r < 0.70:  return "🟢 Bullish"
    if r <= 0.85: return "🟡 Neutral"
    return "🔴 Bearish"

def apply_styles(row):
    styles = [""] * len(row)
    idx = list(row.index)

    if "52W Range %" in idx:
        v = row["52W Range %"]
        if pd.notna(v):
            c = "#d4f0d4" if v>=60 else "#fff9cc" if v>=35 else "#fde0e0"
            styles[idx.index("52W Range %")] = f"background-color:{c}"

    if "% from 52W High" in idx:
        v = row["% from 52W High"]
        if pd.notna(v):
            if v >= -5:    styles[idx.index("% from 52W High")] = "color:#1a6e1a;font-weight:600"
            elif v >= -15: styles[idx.index("% from 52W High")] = "color:#7a5500"
            else:          styles[idx.index("% from 52W High")] = "color:#8b1a1a"

    if "Sentiment" in idx:
        s = str(row["Sentiment"])
        if "Bullish" in s:  styles[idx.index("Sentiment")] = "color:#1a6e1a;font-weight:600"
        elif "Neutral" in s:styles[idx.index("Sentiment")] = "color:#7a5500;font-weight:600"
        elif "Bearish" in s:styles[idx.index("Sentiment")] = "color:#8b1a1a;font-weight:600"

    if "Weight %" in idx:
        v = row["Weight %"]
        if pd.notna(v) and v > 0:
            pct = min(v / row.get("_max_w", 1) * 100, 100)
            styles[idx.index("Weight %")] = (
                f"background:linear-gradient(90deg,#4a90d933 {pct:.0f}%,"
                f"transparent {pct:.0f}%)"
            )
    return styles

# ── Main render ───────────────────────────────────────────────────────────────

if run or ticker_input:
    # ETF meta
    with st.spinner(f"Loading {ticker_input} metadata…"):
        etf_name, etf_price, etf_aum, etf_expense, etf_cat = get_etf_meta(ticker_input)

    st.subheader(f"{ticker_input} — {etf_name}")
    if etf_cat and etf_cat != "–":
        st.caption(f"Category: {etf_cat}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Price",         f"${etf_price:,.2f}"        if etf_price   else "N/A")
    m2.metric("AUM",           f"${etf_aum/1e9:,.2f}B"     if etf_aum     else "N/A")
    m3.metric("Expense Ratio", f"{etf_expense*100:.2f}%"   if etf_expense else "N/A")
    m4.metric("Holdings Source","stockanalysis.com")

    st.divider()

    # Holdings
    with st.spinner(f"Fetching {ticker_input} holdings from stockanalysis.com…"):
        holdings_df = get_holdings_stockanalysis(ticker_input)

    if holdings_df.empty:
        st.error(
            f"❌ Could not retrieve holdings for **{ticker_input}**.\n\n"
            "Possible reasons:\n"
            "- Ticker not found on stockanalysis.com\n"
            "- ETF is very small or newly listed\n"
            "- Temporary network issue — try refreshing\n\n"
            f"Check manually: https://stockanalysis.com/etf/{ticker_input.lower()}/holdings/"
        )
        st.stop()

    symbols = holdings_df["Symbol"].tolist()
    st.success(f"✅ Found **{len(symbols)} holdings** for {ticker_input}")

    # Prices + 52W
    with st.spinner("Fetching prices and 52-week data…"):
        price_df = get_price_52w(symbols)

    # Options
    if load_options:
        with st.spinner(f"Fetching options data for {len(symbols)} stocks… (~1–3 min)"):
            pc_data = get_put_call(symbols)
        price_df["P/C Ratio"] = price_df["Symbol"].map(pc_data)
        price_df["Sentiment"] = price_df["P/C Ratio"].apply(sentiment_label)
    else:
        price_df["P/C Ratio"] = None
        price_df["Sentiment"] = "–"

    # Merge all
    df = holdings_df.merge(price_df, on="Symbol", how="left")
    df = df.sort_values("Weight %", ascending=False, na_position="last").reset_index(drop=True)

    # ── Summary metrics ───────────────────────────────────────────────────────
    near_hi  = (df["% from 52W High"] >= -5).sum()
    near_lo  = (df["52W Range %"] <= 10).sum()
    avg_rng  = df["52W Range %"].mean()
    top5_wt  = df["Weight %"].head(5).sum()

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Holdings Shown",         len(df))
    s2.metric("Top 5 Weight",           f"{top5_wt:.1f}%"           if pd.notna(top5_wt) else "N/A")
    s3.metric("Near 52W High (≤5%)",    int(near_hi))
    s4.metric("Avg 52W Range Position", f"{avg_rng:.1f}%"            if pd.notna(avg_rng) else "N/A")

    if load_options:
        bull_n = (df["P/C Ratio"] < 0.70).sum()
        neu_n  = ((df["P/C Ratio"] >= 0.70) & (df["P/C Ratio"] <= 0.85)).sum()
        bear_n = (df["P/C Ratio"] > 0.85).sum()
        o1, o2, o3, _ = st.columns(4)
        o1.metric("🟢 Bullish Holdings", int(bull_n))
        o2.metric("🟡 Neutral Holdings", int(neu_n))
        o3.metric("🔴 Bearish Holdings", int(bear_n))

    st.divider()

    # ── Charts row ────────────────────────────────────────────────────────────
    col_pie, col_bar = st.columns([1, 2])

    with col_pie:
        st.subheader("Top Holdings Weight")
        top10 = df.dropna(subset=["Weight %"]).head(10)
        labels = top10["Symbol"].tolist()
        sizes  = top10["Weight %"].tolist()
        rest   = 100 - sum(sizes)
        if rest > 0.5:
            labels.append("Others")
            sizes.append(round(rest, 2))
        cmap   = plt.get_cmap("tab20")
        colors = [cmap(i / len(labels)) for i in range(len(labels))]
        fig_p, ax_p = plt.subplots(figsize=(5, 5))
        wedges, texts, autos = ax_p.pie(
            sizes, labels=labels, autopct="%1.1f%%",
            startangle=140, pctdistance=0.80,
            colors=colors, textprops={"fontsize": 8},
        )
        ax_p.set_title(f"{ticker_input} — Top 10 Holdings", fontsize=11)
        fig_p.tight_layout()
        st.pyplot(fig_p)

    with col_bar:
        st.subheader("52-Week Range Position")
        bar_df = df.dropna(subset=["52W Range %"]).sort_values("52W Range %", ascending=True)
        if not bar_df.empty:
            bc = ["green" if v>=60 else "gold" if v>=35 else "tomato" for v in bar_df["52W Range %"]]
            fig_b, ax_b = plt.subplots(figsize=(7, max(4, len(bar_df)*0.28)))
            bars_b = ax_b.barh(bar_df["Symbol"], bar_df["52W Range %"], color=bc, edgecolor="none", height=0.65)
            ax_b.axvline(x=50, color="black", linestyle="--", linewidth=0.8, label="Midpoint")
            ax_b.set_xlabel("Position in 52-Week Range (%)", fontsize=9)
            ax_b.set_xlim(0, 120)
            ax_b.tick_params(axis="y", labelsize=8)
            for bar, val in zip(bars_b, bar_df["52W Range %"]):
                ax_b.text(bar.get_width()+1, bar.get_y()+bar.get_height()/2,
                          f"{val:.0f}%", va="center", fontsize=7.5)
            gp = mpatches.Patch(color="green",  label="Strong (≥60%)")
            yp = mpatches.Patch(color="gold",   label="Mid (35–60%)")
            rp = mpatches.Patch(color="tomato", label="Weak (<35%)")
            ax_b.legend(handles=[gp,yp,rp], fontsize=8, loc="lower right")
            fig_b.tight_layout()
            st.pyplot(fig_b)

    st.divider()

    # ── Full table ────────────────────────────────────────────────────────────
    st.subheader("📋 Full Holdings Table")

    COLS = ["Symbol","Name","Weight %","Price ($)","52W Low","52W High","% from 52W High","52W Range %"]
    if load_options:
        COLS += ["P/C Ratio","Sentiment"]

    disp = df[[c for c in COLS if c in df.columns]].copy()
    max_w = disp["Weight %"].max() if "Weight %" in disp.columns and disp["Weight %"].notna().any() else 1
    disp["_max_w"] = max_w

    styled = disp.drop(columns=["_max_w"]).style.apply(
        lambda row: apply_styles(pd.concat([row, pd.Series({"_max_w": max_w})])),
        axis=1
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Options chart ─────────────────────────────────────────────────────────
    if load_options:
        st.divider()
        st.subheader("📊 Options Sentiment per Holding")
        pc_df = df.dropna(subset=["P/C Ratio"]).sort_values("P/C Ratio")
        if not pc_df.empty:
            pc_c = ["green" if r<0.70 else "gold" if r<=0.85 else "tomato" for r in pc_df["P/C Ratio"]]
            fig_o, ax_o = plt.subplots(figsize=(12, max(4, len(pc_df)*0.28)))
            bars_o = ax_o.barh(pc_df["Symbol"], pc_df["P/C Ratio"], color=pc_c, edgecolor="none", height=0.65)
            ax_o.axvline(x=0.70, color="green",  linestyle=":", linewidth=1)
            ax_o.axvline(x=0.85, color="orange", linestyle=":", linewidth=1)
            ax_o.axvline(x=1.00, color="black",  linestyle="--", linewidth=0.8)
            ax_o.set_xlabel("Put/Call Ratio", fontsize=9)
            ax_o.set_title(f"{ticker_input} Holdings — Put/Call Ratios (Bullish → Bearish)", fontsize=11)
            ax_o.tick_params(axis="y", labelsize=8)
            for bar, val in zip(bars_o, pc_df["P/C Ratio"]):
                ax_o.text(bar.get_width()+0.01, bar.get_y()+bar.get_height()/2,
                          f"{val:.3f}", va="center", fontsize=7.5)
            gp = mpatches.Patch(color="green",  label="Bullish (<0.70)")
            yp = mpatches.Patch(color="gold",   label="Neutral (0.70–0.85)")
            rp = mpatches.Patch(color="tomato", label="Bearish (>0.85)")
            ax_o.legend(handles=[gp,yp,rp], fontsize=8, loc="lower right")
            fig_o.tight_layout()
            st.pyplot(fig_o)

    st.divider()
    st.caption(
        f"Holdings: stockanalysis.com · Prices & 52W: Yahoo Finance (cached 15 min) · "
        f"Options: Yahoo Finance (cached 1 hr) · Built with Streamlit"
    )
