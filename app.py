import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

st.set_page_config(page_title="ETF Holdings Breakdown", layout="wide")

st.title("🔍 ETF Holdings Breakdown Dashboard")
st.caption("Holdings pulled directly from ETF providers (SPDR · Vanguard · Invesco · iShares · ARK · VanEck) — No API key needed")

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER ROUTING MAP
# Covers every ETF from the user's original list + common extras
# ─────────────────────────────────────────────────────────────────────────────

# SPDR / State Street: Excel file per ticker
SSGA_TICKERS = {
    "SPY","XLK","XLE","XLF","XLV","XLY","XLP","XLU","XLC","XLI","XLB","XLRE",
    "KBE","KRE","KIE","XRT","GLD","SLV","DIA","MDY","IJR",
}

# Vanguard: JSON API
VANGUARD_TICKERS = {
    "VOO","VTI","VNQ","VPU","VGT","VFH","VDE","VHT","VCR","VDC","VIS","VAW",
    "VOX","VIG","VYM","VXUS","VEA","VWO","VTV","VUG","VB","VO","VBR","VBK",
    "VTIP","BND","BSV","BLV","BNDX","VMBS",
}

# Invesco: CSV download
INVESCO_TICKERS = {
    "QQQ","QQQM","RSP","IVZ","PGX","BKLN","PFF","SPHQ","SPHD","SPLV","CIBR",
    "SKYY","PBJ","DBA","PHO","PEJ","PBS","IGV",
}

# iShares (BlackRock): CSV with fund ID mapping
ISHARES_MAP = {
    "IVV":  "239726","IWM":"239710","EFA":"239623","EEM":"239637",
    "AGG":  "239458","LQD":"239566","HYG":"239565","TLT":"239454",
    "SOXX": "239705","IHI":"239516","ITA":"239512","IYT":"239501",
    "IBB":  "239699","ICLN":"239550","ITB":"239515","IGV":"239502",
    "SRVR": "1621964","SMH":"239705",
}

# ARK Invest: public CSV
ARK_MAP = {
    "ARKK": "ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKG": "ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKW": "ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKF": "ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
    "ARKQ": "ARK_AUTONOMOUS_TECH._&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    "ARKVX":"ARK_VENTURE_FUND_ARKVX_HOLDINGS.csv",
}

# VanEck: CSV download (slug mapping)
VANECK_MAP = {
    "GDX":  "gold-miners-etf-gdx",
    "GDXJ": "junior-gold-miners-etf-gdxj",
    "SMH":  "semiconductor-etf-smh",
    "OIH":  "oil-services-etf-oih",
    "REMX": "rare-earth-strategic-metals-etf-remx",
    "MSOS": "msci-usa-broad-esg-etf-esgu",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_ssga(ticker: str) -> pd.DataFrame:
    """State Street / SPDR direct Excel download."""
    url = (
        f"https://www.ssga.com/us/en/individual/etfs/library-content/products/"
        f"fund-data/etfs/us/holdings-daily-us-en-{ticker.lower()}.xlsx"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    # SPDR Excel: header row is at index 3 (4th row)
    df = pd.read_excel(io.BytesIO(r.content), header=3, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    # Drop footer rows (no ticker)
    df = df.dropna(subset=["Ticker"])
    df = df[df["Ticker"].astype(str).str.match(r"^[A-Z]{1,5}$")]
    rename = {"Ticker": "Symbol", "Name": "Name", "Weight": "Weight %"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "Weight %" in df.columns:
        df["Weight %"] = pd.to_numeric(df["Weight %"], errors="coerce").round(2)
    return df[["Symbol","Name","Weight %"]].dropna(subset=["Symbol"]).reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_vanguard(ticker: str) -> pd.DataFrame:
    """Vanguard JSON portfolio holdings API."""
    url = (
        f"https://investor.vanguard.com/investment-products/etfs/profile/api/"
        f"{ticker}/portfolio-holding/stock"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Navigate to holding list — structure varies slightly
    holdings = (
        data.get("fund", {}).get("entity", [])
        or data.get("holdingDetails", {}).get("holding", [])
        or []
    )
    rows = []
    for h in holdings:
        sym  = h.get("ticker","").strip()
        name = h.get("shortLongName") or h.get("holdingName","")
        pct  = h.get("percentage") or h.get("percentWeight")
        if sym:
            rows.append({"Symbol": sym, "Name": name, "Weight %": round(float(pct), 2) if pct else None})
    df = pd.DataFrame(rows)
    return df.sort_values("Weight %", ascending=False, na_position="last").reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_invesco(ticker: str) -> pd.DataFrame:
    """Invesco direct CSV download."""
    url = (
        f"https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
        f"?audienceType=Investor&action=download&ticker={ticker}"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    # Find the data start row — Invesco CSVs have a few header lines
    lines = r.text.splitlines()
    header_row = 0
    for i, line in enumerate(lines):
        if "Fund Ticker" in line or "Holding Ticker" in line or "Security Identifier" in line:
            header_row = i
            break
    df = pd.read_csv(io.StringIO(r.text), skiprows=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if "ticker" in cl and "fund" not in cl: rename[c] = "Symbol"
        elif "name" in cl and "fund" not in cl: rename[c] = "Name"
        elif "weight" in cl:                    rename[c] = "Weight %"
    df = df.rename(columns=rename)
    if "Symbol" not in df.columns:
        # last-resort column guess
        df = df.rename(columns={df.columns[0]: "Symbol", df.columns[1]: "Name"})
    df = df[df["Symbol"].astype(str).str.match(r"^[A-Z]{1,5}$", na=False)]
    if "Weight %" in df.columns:
        df["Weight %"] = (
            pd.to_numeric(df["Weight %"].astype(str).str.replace("%",""), errors="coerce").round(2)
        )
    keep = [c for c in ["Symbol","Name","Weight %"] if c in df.columns]
    return df[keep].dropna(subset=["Symbol"]).reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_ishares(ticker: str, fund_id: str) -> pd.DataFrame:
    """iShares / BlackRock CSV download via AJAX endpoint."""
    url = (
        f"https://www.ishares.com/us/products/{fund_id}/{ticker.lower()}/"
        f"1467271812596.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    lines = r.text.splitlines()
    # iShares CSV has a few metadata rows before the actual header
    skip = 0
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or line.startswith("Name,"):
            skip = i
            break
    df = pd.read_csv(io.StringIO(r.text), skiprows=skip)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "ticker":                         rename[c] = "Symbol"
        elif cl == "name":                         rename[c] = "Name"
        elif "weight" in cl and "%" in cl:         rename[c] = "Weight %"
    df = df.rename(columns=rename)
    df = df[df.get("Symbol", pd.Series(dtype=str)).astype(str).str.match(r"^[A-Z]{1,5}$", na=False)]
    if "Weight %" in df.columns:
        df["Weight %"] = pd.to_numeric(df["Weight %"], errors="coerce").round(2)
    keep = [c for c in ["Symbol","Name","Weight %"] if c in df.columns]
    return df[keep].dropna(subset=["Symbol"]).reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_ark(csv_filename: str) -> pd.DataFrame:
    """ARK Invest public CSV holdings."""
    url = f"https://ark-funds.com/wp-content/uploads/funds-etf-csv/{csv_filename}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "ticker":                  rename[c] = "Symbol"
        elif "company" in cl or "name" in cl: rename[c] = "Name"
        elif "weight" in cl:                rename[c] = "Weight %"
    df = df.rename(columns=rename)
    df = df[df.get("Symbol", pd.Series(dtype=str)).astype(str).str.match(r"^[A-Z]{1,5}$", na=False)]
    if "Weight %" in df.columns:
        df["Weight %"] = (
            pd.to_numeric(df["Weight %"].astype(str).str.replace("%",""), errors="coerce").round(2)
        )
    keep = [c for c in ["Symbol","Name","Weight %"] if c in df.columns]
    return df[keep].dropna(subset=["Symbol"]).reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_vaneck(slug: str) -> pd.DataFrame:
    """VanEck CSV holdings download."""
    url = f"https://www.vaneck.com/us/en/investments/{slug}/holdings/download/?type=csv"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    lines = r.text.splitlines()
    skip = 0
    for i, line in enumerate(lines):
        if "Symbol" in line or "Ticker" in line or "Security" in line:
            skip = i
            break
    df = pd.read_csv(io.StringIO(r.text), skiprows=skip)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for c in df.columns:
        cl = c.lower()
        if "symbol" in cl or "ticker" in cl: rename[c] = "Symbol"
        elif "name" in cl or "desc" in cl:   rename[c] = "Name"
        elif "weight" in cl or "%" in cl:    rename[c] = "Weight %"
    df = df.rename(columns=rename)
    df = df[df.get("Symbol", pd.Series(dtype=str)).astype(str).str.match(r"^[A-Z]{1,5}$", na=False)]
    if "Weight %" in df.columns:
        df["Weight %"] = pd.to_numeric(
            df["Weight %"].astype(str).str.replace("%",""), errors="coerce"
        ).round(2)
    keep = [c for c in ["Symbol","Name","Weight %"] if c in df.columns]
    return df[keep].dropna(subset=["Symbol"]).reset_index(drop=True)


def get_holdings(ticker: str) -> tuple[pd.DataFrame, str]:
    """Route to correct provider and return (df, provider_name)."""
    t = ticker.upper()
    try:
        if t in SSGA_TICKERS:
            return fetch_ssga(t), "SPDR / State Street"
        if t in VANGUARD_TICKERS:
            return fetch_vanguard(t), "Vanguard"
        if t in INVESCO_TICKERS:
            return fetch_invesco(t), "Invesco"
        if t in ISHARES_MAP:
            return fetch_ishares(t, ISHARES_MAP[t]), "iShares / BlackRock"
        if t in ARK_MAP:
            return fetch_ark(ARK_MAP[t]), "ARK Invest"
        if t in VANECK_MAP:
            return fetch_vaneck(VANECK_MAP[t]), "VanEck"
    except Exception as e:
        st.warning(f"Primary source failed ({e}), trying fallback…")

    # yfinance fallback
    try:
        fd = yf.Ticker(t).funds_data
        h  = fd.top_holdings
        if h is not None and not h.empty:
            rows = []
            for _, row in h.iterrows():
                sym  = str(row.get("symbol","")).strip()
                name = str(row.get("holdingName", sym))
                pct  = row.get("holdingPercent")
                if sym:
                    rows.append({"Symbol": sym, "Name": name,
                                 "Weight %": round(float(pct)*100, 2) if pct else None})
            return pd.DataFrame(rows), "Yahoo Finance (top 25 only)"
    except Exception:
        pass

    return pd.DataFrame(), "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# PRICE / 52W / OPTIONS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=900)
def get_price_52w(symbols: list) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        try:
            fi    = yf.Ticker(sym).fast_info
            price = round(fi.last_price, 2) if fi.last_price else None
            hi52  = round(fi.year_high,  2) if fi.year_high  else None
            lo52  = round(fi.year_low,   2) if fi.year_low   else None
            rng   = (round((price-lo52)/(hi52-lo52)*100, 1)
                     if price and hi52 and lo52 and (hi52-lo52) > 0 else None)
            frhi  = round((price-hi52)/hi52*100, 2) if price and hi52 else None
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
            t = yf.Ticker(sym)
            dates = t.options
            if not dates:
                result[sym] = None
                continue
            tp, tc = 0, 0
            for d in dates:
                chain = t.option_chain(d)
                tp   += chain.puts["volume"].sum()
                tc   += chain.calls["volume"].sum()
            result[sym] = round(tp/tc, 3) if tc else None
        except Exception:
            result[sym] = None
    return result


@st.cache_data(ttl=1800)
def get_etf_meta(ticker: str):
    try:
        info = yf.Ticker(ticker).info
        return (info.get("longName", ticker),
                info.get("regularMarketPrice") or info.get("navPrice"),
                info.get("totalAssets"),
                info.get("annualReportExpenseRatio"),
                info.get("category","–"))
    except Exception:
        return ticker, None, None, None, "–"


# ─────────────────────────────────────────────────────────────────────────────
# STYLING
# ─────────────────────────────────────────────────────────────────────────────

def sentiment_label(r):
    if r is None or pd.isna(r): return "–"
    if r < 0.70:  return "🟢 Bullish"
    if r <= 0.85: return "🟡 Neutral"
    return "🔴 Bearish"

def apply_styles(row, max_w=1):
    styles = [""] * len(row)
    idx    = list(row.index)

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
        if "Bullish" in s:   styles[idx.index("Sentiment")] = "color:#1a6e1a;font-weight:600"
        elif "Neutral" in s: styles[idx.index("Sentiment")] = "color:#7a5500;font-weight:600"
        elif "Bearish" in s: styles[idx.index("Sentiment")] = "color:#8b1a1a;font-weight:600"

    if "Weight %" in idx:
        v = row["Weight %"]
        if pd.notna(v) and max_w > 0:
            pct = min(v/max_w*100, 100)
            styles[idx.index("Weight %")] = (
                f"background:linear-gradient(90deg,#4a90d940 {pct:.0f}%,transparent {pct:.0f}%)"
            )
    return styles


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

POPULAR = {
    "SPDR":    ["SPY","XLK","XLE","XLF","XLV","XLY","XLP","XLU","XLC","XLI","XLB","KBE","KRE"],
    "Vanguard":["VOO","VTI","VNQ","VGT","VHT","VFH","VDE","VCR","VDC","VIS","VAW","VOX"],
    "Invesco": ["QQQ","CIBR","SKYY","PHO","PBJ","DBA","PEJ","PBS","IGV"],
    "iShares": ["IVV","IBB","SOXX","ITA","IHI","IYT","ICLN","ITB"],
    "ARK":     ["ARKK","ARKG","ARKW","ARKF","ARKQ"],
    "VanEck":  ["SMH","GDX","GDXJ","OIH","REMX"],
}

with st.sidebar:
    st.header("⚙️  Settings")
    st.markdown("**Browse by provider:**")
    provider_sel = st.selectbox("Provider", list(POPULAR.keys()))
    ticker_sel   = st.selectbox("ETF", POPULAR[provider_sel])

    load_options = st.checkbox("Load Options Sentiment", value=False,
                               help="Fetches options chain per holding — takes 1–3 min.")
    st.divider()
    st.markdown("**52W Range colours**")
    st.markdown("🟢 ≥60%  Strong · 🟡 35–60%  Mid · 🔴 <35%  Weak")
    if load_options:
        st.divider()
        st.markdown("**P/C Ratio colours**")
        st.markdown("🟢 <0.70 Bullish · 🟡 0.70–0.85 Neutral · 🔴 >0.85 Bearish")

# ─────────────────────────────────────────────────────────────────────────────
# TICKER INPUT
# ─────────────────────────────────────────────────────────────────────────────

col_in, col_btn = st.columns([3,1])
with col_in:
    ticker_input = st.text_input(
        "Enter any ETF ticker (or pick from sidebar)",
        value=ticker_sel,
        placeholder="e.g. QQQ, SPY, XLK, ARKG…"
    ).upper().strip()
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("🔎 Analyse ETF", use_container_width=True)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if run or ticker_input:
    with st.spinner(f"Loading {ticker_input} info…"):
        etf_name, etf_price, etf_aum, etf_expense, etf_cat = get_etf_meta(ticker_input)

    st.subheader(f"{ticker_input}  —  {etf_name}")
    if etf_cat and etf_cat != "–":
        st.caption(f"Category: {etf_cat}")

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Price",         f"${float(etf_price):,.2f}"        if etf_price   else "N/A")
    m2.metric("AUM",           f"${float(etf_aum)/1e9:,.2f}B"     if etf_aum     else "N/A")
    m3.metric("Expense Ratio", f"{float(etf_expense)*100:.2f}%"   if etf_expense else "N/A")
    m4.metric("Category",      etf_cat or "–")

    st.divider()

    # Holdings
    with st.spinner(f"Fetching {ticker_input} holdings from provider…"):
        holdings_df, source = get_holdings(ticker_input)

    if holdings_df.empty:
        provider_list = (
            f"• SPDR: {', '.join(sorted(SSGA_TICKERS)[:8])}…\n"
            f"• Vanguard: {', '.join(sorted(VANGUARD_TICKERS)[:8])}…\n"
            f"• Invesco: {', '.join(sorted(INVESCO_TICKERS)[:8])}…\n"
            f"• iShares: {', '.join(sorted(ISHARES_MAP.keys()))}\n"
            f"• ARK: {', '.join(sorted(ARK_MAP.keys()))}\n"
            f"• VanEck: {', '.join(sorted(VANECK_MAP.keys()))}"
        )
        st.error(
            f"❌ Could not retrieve holdings for **{ticker_input}**.\n\n"
            "This ETF's provider may not be mapped yet. Currently supported tickers:\n\n"
            + provider_list
        )
        st.stop()

    symbols = holdings_df["Symbol"].tolist()
    st.success(f"✅  **{len(symbols)} holdings** loaded via **{source}**")

    # Prices + 52W
    with st.spinner("Fetching prices and 52-week data…"):
        price_df = get_price_52w(symbols)

    # Options
    if load_options:
        with st.spinner(f"Fetching options for {len(symbols)} stocks…"):
            pc_data = get_put_call(symbols)
        price_df["P/C Ratio"] = price_df["Symbol"].map(pc_data)
        price_df["Sentiment"] = price_df["P/C Ratio"].apply(sentiment_label)
    else:
        price_df["P/C Ratio"] = None
        price_df["Sentiment"] = "–"

    df = holdings_df.merge(price_df, on="Symbol", how="left")
    df = df.sort_values("Weight %", ascending=False, na_position="last").reset_index(drop=True)

    # Summary metrics
    near_hi = (df["% from 52W High"] >= -5).sum()
    near_lo = (df["52W Range %"] <= 10).sum()
    avg_rng = df["52W Range %"].mean()
    top5_wt = df["Weight %"].head(5).sum()

    s1,s2,s3,s4 = st.columns(4)
    s1.metric("Holdings",               len(df))
    s2.metric("Top 5 Concentration",    f"{top5_wt:.1f}%"  if pd.notna(top5_wt) else "N/A")
    s3.metric("Near 52W High (≤5%)",    int(near_hi))
    s4.metric("Avg 52W Range Position", f"{avg_rng:.1f}%"  if pd.notna(avg_rng) else "N/A")

    if load_options:
        bull_n = (df["P/C Ratio"] < 0.70).sum()
        neu_n  = ((df["P/C Ratio"] >= 0.70) & (df["P/C Ratio"] <= 0.85)).sum()
        bear_n = (df["P/C Ratio"] > 0.85).sum()
        o1,o2,o3,_ = st.columns(4)
        o1.metric("🟢 Bullish", int(bull_n))
        o2.metric("🟡 Neutral", int(neu_n))
        o3.metric("🔴 Bearish", int(bear_n))

    st.divider()

    # Charts
    col_pie, col_bar = st.columns([1,2])

    with col_pie:
        st.subheader("Top Holdings Weight")
        top10  = df.dropna(subset=["Weight %"]).head(10)
        labels = top10["Symbol"].tolist()
        sizes  = top10["Weight %"].tolist()
        rest   = 100 - sum(sizes)
        if rest > 0.5:
            labels.append("Others"); sizes.append(round(rest,2))
        cmap   = plt.get_cmap("tab20")
        colors = [cmap(i/len(labels)) for i in range(len(labels))]
        fig_p, ax_p = plt.subplots(figsize=(5,5))
        ax_p.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140,
                 pctdistance=0.80, colors=colors, textprops={"fontsize":8})
        ax_p.set_title(f"{ticker_input} — Top 10", fontsize=11)
        fig_p.tight_layout(); st.pyplot(fig_p)

    with col_bar:
        st.subheader("52-Week Range Position")
        bar_df = df.dropna(subset=["52W Range %"]).sort_values("52W Range %", ascending=True)
        if not bar_df.empty:
            bc = ["green" if v>=60 else "gold" if v>=35 else "tomato" for v in bar_df["52W Range %"]]
            fig_b, ax_b = plt.subplots(figsize=(7, max(4, len(bar_df)*0.27)))
            bars_b = ax_b.barh(bar_df["Symbol"], bar_df["52W Range %"], color=bc, edgecolor="none", height=0.65)
            ax_b.axvline(x=50, color="black", linestyle="--", linewidth=0.8)
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
            fig_b.tight_layout(); st.pyplot(fig_b)

    st.divider()

    # Full table
    st.subheader("📋 Full Holdings Table")
    COLS = ["Symbol","Name","Weight %","Price ($)","52W Low","52W High","% from 52W High","52W Range %"]
    if load_options:
        COLS += ["P/C Ratio","Sentiment"]

    disp  = df[[c for c in COLS if c in df.columns]].copy()
    max_w = disp["Weight %"].max() if disp["Weight %"].notna().any() else 1
    styled = disp.style.apply(lambda row: apply_styles(row, max_w), axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Options chart
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
            ax_o.set_title(f"{ticker_input} Holdings — Put/Call Ratios", fontsize=11)
            ax_o.tick_params(axis="y", labelsize=8)
            for bar, val in zip(bars_o, pc_df["P/C Ratio"]):
                ax_o.text(bar.get_width()+0.01, bar.get_y()+bar.get_height()/2,
                          f"{val:.3f}", va="center", fontsize=7.5)
            gp = mpatches.Patch(color="green",  label="Bullish (<0.70)")
            yp = mpatches.Patch(color="gold",   label="Neutral (0.70–0.85)")
            rp = mpatches.Patch(color="tomato", label="Bearish (>0.85)")
            ax_o.legend(handles=[gp,yp,rp], fontsize=8, loc="lower right")
            fig_o.tight_layout(); st.pyplot(fig_o)

    st.divider()
    st.caption(f"Holdings source: {source} · Prices/52W: Yahoo Finance (15 min cache) · Options: Yahoo Finance (1 hr cache)")
