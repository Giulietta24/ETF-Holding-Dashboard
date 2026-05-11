import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

st.set_page_config(page_title="ETF Holdings Breakdown", layout="wide")

st.title("🔍 ETF Holdings Breakdown Dashboard")
st.caption("Enter any ETF to see its holdings · 52-Week Range · Options Sentiment")

# ── Input ─────────────────────────────────────────────────────────────────────
col_input, col_btn, col_opt = st.columns([2, 1, 2])
with col_input:
    ticker_input = st.text_input("Enter ETF Ticker", value="QQQ", placeholder="e.g. QQQ, SPY, XLK…").upper().strip()
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("🔎 Analyse", use_container_width=True)
with col_opt:
    st.markdown("<br>", unsafe_allow_html=True)
    load_options = st.checkbox("Load Options Sentiment (slower)", value=False)

st.divider()

# ── Helper functions ──────────────────────────────────────────────────────────

@st.cache_data(ttl=1800)
def get_etf_info(ticker):
    etf = yf.Ticker(ticker)
    try:
        info = etf.info
        name  = info.get("longName", ticker)
        price = info.get("regularMarketPrice") or info.get("navPrice")
        aum   = info.get("totalAssets")
        expense = info.get("annualReportExpenseRatio")
        return name, price, aum, expense
    except Exception:
        return ticker, None, None, None

@st.cache_data(ttl=1800)
def get_holdings(ticker):
    """Fetch top holdings via yfinance funds_data."""
    etf = yf.Ticker(ticker)
    rows = []
    try:
        fd = etf.funds_data
        holdings = fd.top_holdings          # DataFrame: symbol, holdingName, holdingPercent
        if holdings is not None and not holdings.empty:
            for _, row in holdings.iterrows():
                sym = str(row.get("symbol", "")).strip()
                name = str(row.get("holdingName", sym)).strip()
                pct  = row.get("holdingPercent", None)
                if sym:
                    rows.append({"Symbol": sym, "Name": name, "Weight %": round(float(pct)*100, 2) if pct else None})
    except Exception:
        pass

    # fallback: try .info top10
    if not rows:
        try:
            info = etf.info
            for i in range(1, 11):
                sym  = info.get(f"holdings{i}Symbol")
                name = info.get(f"holdings{i}Description", sym)
                pct  = info.get(f"holdings{i}Percent")
                if sym:
                    rows.append({"Symbol": sym, "Name": name, "Weight %": round(float(pct)*100, 2) if pct else None})
        except Exception:
            pass

    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Symbol","Name","Weight %"])

@st.cache_data(ttl=900)
def get_price_52w(symbols):
    rows = []
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            price   = round(fi.last_price, 2) if fi.last_price else None
            hi52    = round(fi.year_high,  2) if fi.year_high  else None
            lo52    = round(fi.year_low,   2) if fi.year_low   else None
            rng_pct = None
            if price and hi52 and lo52 and (hi52 - lo52) > 0:
                rng_pct = round((price - lo52) / (hi52 - lo52) * 100, 1)
            from_hi = round((price - hi52) / hi52 * 100, 2) if price and hi52 else None
            rows.append({"Symbol": sym, "Price": price, "52W Low": lo52, "52W High": hi52,
                         "52W Range %": rng_pct, "% from 52W High": from_hi})
        except Exception:
            rows.append({"Symbol": sym, "Price": None, "52W Low": None, "52W High": None,
                         "52W Range %": None, "% from 52W High": None})
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600)
def get_put_call(symbols):
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

def sentiment_label(r):
    if r is None or (isinstance(r, float) and pd.isna(r)): return "–"
    if r < 0.70:  return "🟢 Bullish"
    if r <= 0.85: return "🟡 Neutral"
    return "🔴 Bearish"

def range_color(v):
    if pd.isna(v): return ""
    if v >= 60:  return "background-color:#d4f0d4"
    if v >= 35:  return "background-color:#fff9cc"
    return "background-color:#fde0e0"

def high_color(v):
    if pd.isna(v): return ""
    if v >= -5:   return "color:#1a6e1a;font-weight:600"
    if v >= -15:  return "color:#7a5500"
    return "color:#8b1a1a"

def sent_color(v):
    if "Bullish" in str(v): return "color:#1a6e1a;font-weight:600"
    if "Neutral" in str(v): return "color:#7a5500;font-weight:600"
    if "Bearish" in str(v): return "color:#8b1a1a;font-weight:600"
    return ""

def style_table(row):
    styles = [""] * len(row)
    idx = list(row.index)
    for col, fn in [("52W Range %", range_color), ("% from 52W High", high_color), ("Sentiment", sent_color)]:
        if col in idx:
            styles[idx.index(col)] = fn(row[col])
    return styles

# ── Main logic ─────────────────────────────────────────────────────────────────
if run or ticker_input:

    # ETF top-level info
    with st.spinner(f"Loading {ticker_input} info…"):
        etf_name, etf_price, etf_aum, etf_expense = get_etf_info(ticker_input)

    # Header
    st.subheader(f"{ticker_input} — {etf_name}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("ETF Price", f"${etf_price:,.2f}" if etf_price else "N/A")
    m2.metric("AUM", f"${etf_aum/1e9:,.1f}B" if etf_aum else "N/A")
    m3.metric("Expense Ratio", f"{etf_expense*100:.2f}%" if etf_expense else "N/A")
    m4.metric("Data Source", "Yahoo Finance")

    st.divider()

    # Holdings
    with st.spinner("Fetching holdings…"):
        holdings_df = get_holdings(ticker_input)

    if holdings_df.empty:
        st.warning(f"⚠️ No holdings data found for **{ticker_input}**. "
                   "Some ETFs (inverse, leveraged, or smaller funds) may not expose holdings via Yahoo Finance.")
        st.stop()

    symbols = holdings_df["Symbol"].tolist()
    st.info(f"Found **{len(symbols)} holdings**. Fetching prices and 52-week data…")

    # Price / 52w data
    with st.spinner("Fetching price & 52-week data for each holding…"):
        price_df = get_price_52w(symbols)

    # Options sentiment
    if load_options:
        with st.spinner("Fetching options data for each holding… (may take a minute)"):
            pc_data = get_put_call(symbols)
        price_df["P/C Ratio"] = price_df["Symbol"].map(pc_data)
        price_df["Sentiment"] = price_df["P/C Ratio"].apply(sentiment_label)
    else:
        price_df["P/C Ratio"] = None
        price_df["Sentiment"] = "–"

    # Merge
    df = holdings_df.merge(price_df, on="Symbol", how="left")
    df = df.sort_values("Weight %", ascending=False).reset_index(drop=True)

    # ── Summary metrics ───────────────────────────────────────────────────────
    valid_range = df.dropna(subset=["52W Range %"])
    near_hi   = (df["% from 52W High"] >= -5).sum()
    near_lo   = (df["52W Range %"] <= 10).sum()
    avg_range = valid_range["52W Range %"].mean()

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Holdings Shown", len(df))
    s2.metric("Near 52W High (≤5%)", int(near_hi))
    s3.metric("Near 52W Low (≤10%)", int(near_lo))
    s4.metric("Avg 52W Range Position", f"{avg_range:.1f}%" if not pd.isna(avg_range) else "N/A")

    if load_options:
        s5, s6, s7, _ = st.columns(4)
        bull_n = (df["P/C Ratio"] < 0.70).sum()
        neu_n  = ((df["P/C Ratio"] >= 0.70) & (df["P/C Ratio"] <= 0.85)).sum()
        bear_n = (df["P/C Ratio"] > 0.85).sum()
        s5.metric("🟢 Bullish Holdings", int(bull_n))
        s6.metric("🟡 Neutral Holdings", int(neu_n))
        s7.metric("🔴 Bearish Holdings", int(bear_n))

    st.divider()

    # ── Weight pie chart + 52W bar chart ──────────────────────────────────────
    col_pie, col_bar = st.columns([1, 2])

    with col_pie:
        st.subheader("Portfolio Weight")
        top_n  = df.dropna(subset=["Weight %"]).head(10)
        labels = top_n["Symbol"].tolist()
        sizes  = top_n["Weight %"].tolist()
        others = 100 - sum(sizes)
        if others > 0:
            labels.append("Others")
            sizes.append(round(others, 2))
        fig_pie, ax_pie = plt.subplots(figsize=(5, 5))
        wedges, texts, autotexts = ax_pie.pie(
            sizes, labels=labels, autopct="%1.1f%%",
            startangle=140, pctdistance=0.82,
            textprops={"fontsize": 8},
        )
        ax_pie.set_title(f"{ticker_input} Top Holdings", fontsize=11)
        fig_pie.tight_layout()
        st.pyplot(fig_pie)

    with col_bar:
        st.subheader("52-Week Range Position per Holding")
        bar_df = df.dropna(subset=["52W Range %"]).sort_values("52W Range %", ascending=True)
        if not bar_df.empty:
            bar_colors = ["green" if v >= 60 else "gold" if v >= 35 else "tomato"
                          for v in bar_df["52W Range %"]]
            fig_bar, ax_bar = plt.subplots(figsize=(7, max(3.5, len(bar_df) * 0.3)))
            bars = ax_bar.barh(bar_df["Symbol"], bar_df["52W Range %"],
                               color=bar_colors, edgecolor="none", height=0.65)
            ax_bar.axvline(x=50, color="black", linestyle="--", linewidth=0.8)
            ax_bar.set_xlabel("Position in 52-Week Range (%)", fontsize=9)
            ax_bar.set_xlim(0, 120)
            ax_bar.tick_params(axis="y", labelsize=8)
            for bar, val in zip(bars, bar_df["52W Range %"]):
                ax_bar.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                            f"{val:.0f}%", va="center", fontsize=7.5)
            gp = mpatches.Patch(color="green",  label="Strong (≥60%)")
            yp = mpatches.Patch(color="gold",   label="Mid (35–60%)")
            rp = mpatches.Patch(color="tomato", label="Weak (<35%)")
            ax_bar.legend(handles=[gp, yp, rp], fontsize=8, loc="lower right")
            fig_bar.tight_layout()
            st.pyplot(fig_bar)
        else:
            st.info("No 52-week range data available.")

    st.divider()

    # ── Full holdings table ───────────────────────────────────────────────────
    st.subheader("📋 Full Holdings Table")

    COLS = ["Symbol", "Name", "Weight %", "Price", "52W Low", "52W High",
            "% from 52W High", "52W Range %"]
    if load_options:
        COLS += ["P/C Ratio", "Sentiment"]

    display_df = df[[c for c in COLS if c in df.columns]].copy()

    # Weight % bar column (visual progress bar via background)
    max_w = display_df["Weight %"].max() if "Weight %" in display_df else 1

    def weight_bar(val):
        if pd.isna(val): return ""
        pct = val / max_w * 100
        return f"background: linear-gradient(90deg, #4a90d9 {pct:.0f}%, transparent {pct:.0f}%); color: #000"

    styled = display_df.style \
        .apply(style_table, axis=1) \
        .applymap(weight_bar, subset=["Weight %"])

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Options sentiment breakdown chart (if loaded) ─────────────────────────
    if load_options:
        st.divider()
        st.subheader("📊 Options Sentiment by Holding")
        pc_valid = df.dropna(subset=["P/C Ratio"]).sort_values("P/C Ratio")
        if not pc_valid.empty:
            pc_colors = ["green" if r < 0.70 else "gold" if r <= 0.85 else "tomato"
                         for r in pc_valid["P/C Ratio"]]
            fig_pc, ax_pc = plt.subplots(figsize=(12, max(4, len(pc_valid) * 0.3)))
            bars_pc = ax_pc.barh(pc_valid["Symbol"], pc_valid["P/C Ratio"],
                                 color=pc_colors, edgecolor="none", height=0.65)
            ax_pc.axvline(x=1.0, color="black", linestyle="--", linewidth=0.8, label="Neutral = 1.0")
            ax_pc.axvline(x=0.70, color="green", linestyle=":", linewidth=0.8, label="Bullish threshold 0.70")
            ax_pc.axvline(x=0.85, color="orange", linestyle=":", linewidth=0.8, label="Bearish threshold 0.85")
            ax_pc.set_xlabel("Put/Call Ratio", fontsize=9)
            ax_pc.set_title(f"{ticker_input} Holdings — Put/Call Ratios (Bullish → Bearish)", fontsize=11)
            ax_pc.tick_params(axis="y", labelsize=8)
            for bar, val in zip(bars_pc, pc_valid["P/C Ratio"]):
                ax_pc.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                           f"{val:.3f}", va="center", fontsize=7.5)
            gp = mpatches.Patch(color="green",  label="Bullish (<0.70)")
            yp = mpatches.Patch(color="gold",   label="Neutral (0.70–0.85)")
            rp = mpatches.Patch(color="tomato", label="Bearish (>0.85)")
            ax_pc.legend(handles=[gp, yp, rp], fontsize=8, loc="lower right")
            fig_pc.tight_layout()
            st.pyplot(fig_pc)
        else:
            st.info("No options data returned for these holdings.")

    st.divider()
    st.caption("Holdings via Yahoo Finance funds_data · Prices cached 15 min · Options cached 1 hr · Built with Streamlit")
