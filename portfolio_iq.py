import streamlit as st
import anthropic
import json
import re
import html as html_lib
import urllib.request
import urllib.parse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as _dt, timedelta as _td

# ── XSS protection: escape ALL user-sourced strings before embedding in HTML ──
def esc(value):
    """Escape user-provided strings before embedding in HTML to prevent XSS."""
    if value is None: return ''
    return html_lib.escape(str(value))

# ── Input sanitisation ────────────────────────────────────────────────────────
def clean_ticker(raw):
    """Strip everything that isn't a valid ticker character."""
    if not raw: return ''
    return re.sub(r'[^A-Z0-9.-]', '', str(raw).upper().strip())[:10]

def clean_number(raw):
    """Strip everything that isn't a digit or decimal point."""
    if raw is None: return ''
    return re.sub(r'[^0-9.]', '', str(raw).strip())[:20]

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NGUYENILY X - Portfolio IQ",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Styles (same design system as Stock Analyzer) ────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@700;800&display=swap');

html, body, [class*="css"] { font-family: 'Space Mono', monospace; background: #060a0f; color: #e2e8f0; }
.main { background: #060a0f; }
.block-container { padding: 1.5rem 1.5rem 4rem; max-width: 960px; }

h1 { font-family: 'Syne', sans-serif !important; font-size: 22px !important; color: #f0f6ff !important; letter-spacing: -0.5px; }
h2 { font-family: 'Syne', sans-serif !important; font-size: 15px !important; color: #3b82f6 !important; letter-spacing: 3px; text-transform: uppercase; }
h3 { font-family: 'Syne', sans-serif !important; font-size: 15px !important; color: #93c5fd !important; letter-spacing: 2px; text-transform: uppercase; }

input[type="text"], input[type="number"] {
    background: #060c15 !important; border: 1px solid #1a2e48 !important;
    color: #ffffff !important; font-family: 'Space Mono', monospace !important;
    font-size: 15px !important; font-weight: 700 !important;
}
input::placeholder { color: rgba(255,255,255,0.4) !important; }

.stButton > button {
    background: #3b82f6 !important; color: #fff !important; border: none !important;
    font-family: 'Syne', sans-serif !important; font-size: 15px !important;
    font-weight: 700 !important; letter-spacing: 2px !important;
    text-transform: uppercase !important; width: 100% !important; padding: 0.75rem !important;
}
.stButton > button:hover { background: #2563eb !important; }
.stButton > button:disabled { background: #1e2d3d !important; color: #7a9ab8 !important; }

.card { background: #0d1825; border: 1px solid #1a2e48; padding: 14px; margin-bottom: 10px; }
.card-blue  { border-color: #3b82f655; background: #080f1f; }
.card-green { border-color: #16a34a55; background: #060f09; }
.card-gold  { border-color: #f59e0b;   background: #0d0b02; }
.card-red   { border-color: #dc262655; background: #150505; }
.card-purple{ border-color: #7c3aed55; background: #0c0818; }

.label   { font-size: 15px; letter-spacing: 2px; color: #94a3b8; text-transform: uppercase; margin-bottom: 4px; }
.big-val { font-family: 'Syne', sans-serif; font-size: 22px; font-weight: 800; color: #f0f6ff; }

.badge-up { display:inline-block;font-size:15px;padding:2px 7px;border:1px solid #16a34a44;background:#061508;color:#4ade80;text-transform:uppercase; }
.badge-dn { display:inline-block;font-size:15px;padding:2px 7px;border:1px solid #dc262644;background:#150505;color:#f87171;text-transform:uppercase; }
.badge-fl { display:inline-block;font-size:15px;padding:2px 7px;border:1px solid #ca8a0444;background:#0f1208;color:#fbbf24;text-transform:uppercase; }

.verdict-bull { background:#061508; border:1px solid #16a34a55; padding:12px; margin-bottom:8px; }
.verdict-bear { background:#150505; border:1px solid #dc262655; padding:12px; margin-bottom:8px; }
.verdict-neut { background:#0f1208; border:1px solid #ca8a0455; padding:12px; margin-bottom:8px; }
.verdict-label-bull { font-family:'Syne',sans-serif; font-size:15px; font-weight:800; color:#4ade80; }
.verdict-label-bear { font-family:'Syne',sans-serif; font-size:15px; font-weight:800; color:#f87171; }
.verdict-label-neut { font-family:'Syne',sans-serif; font-size:15px; font-weight:800; color:#fbbf24; }
.verdict-tag { font-size:15px; letter-spacing:1.5px; text-transform:uppercase; opacity:0.8; }
.verdict-tag-bull { color:#4ade80; } .verdict-tag-bear { color:#f87171; } .verdict-tag-neut { color:#fbbf24; }
.verdict-reason { font-size:15px; color:#e2e8f0; margin-top:3px; line-height:1.5; }

.sec-hdr { font-family:'Syne',sans-serif; font-size:15px; font-weight:700; letter-spacing:3px; text-transform:uppercase; color:#3b82f6; padding:8px 12px; background:#0d1825; border-bottom:1px solid #111c2a; margin-bottom:0; }
.sec-body { padding:12px; font-size:15px; line-height:1.85; color:#e2e8f0; background:#090f1a; border:1px solid #111c2a; margin-bottom:8px; }

.data-table { width:100%; border-collapse:collapse; font-size:15px; }
.data-table th { text-align:left; padding:8px 11px; font-size:15px; letter-spacing:2px; color:#94a3b8; text-transform:uppercase; border-bottom:1px solid #111c2a; background:#0d1825; font-family:'Syne',sans-serif; }
.data-table td { padding:10px 11px; border-bottom:1px solid #090f1a; vertical-align:top; color:#e2e8f0; font-size:15px; }
.data-table tr:last-child td { border-bottom:none; }

/* Mobile-responsive table wrapper */
.tbl-wrap { width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; }

/* Mobile card styles for stacked layouts */
.mob-card { background:#090f1a; border:1px solid #1a2e48; padding:12px; margin-bottom:8px; }
.mob-card-row { display:flex; justify-content:space-between; align-items:flex-start; gap:8px; margin-bottom:6px; flex-wrap:wrap; }
.mob-card-label { font-size:15px; color:#94a3b8; min-width:90px; flex-shrink:0; }
.mob-card-val { font-size:15px; color:#e2e8f0; font-weight:700; text-align:right; flex:1; }
.mob-card-ticker { font-family:'Syne',sans-serif; font-size:18px; font-weight:800; color:#f0f6ff; margin-bottom:8px; }
.mob-card-full { font-size:15px; color:#e2e8f0; line-height:1.6; margin-top:6px; padding-top:6px; border-top:1px solid #111c2a; word-break:break-word; }

/* Prevent news headlines and long text from overflowing on mobile */
.sec-body { word-break:break-word; }
.card { word-break:break-word; }
.sig-good { color:#4ade80; font-size:15px; } .sig-bad { color:#f87171; font-size:15px; } .sig-ok { color:#fbbf24; font-size:15px; }

.divider { height:1px; background:#111c2a; margin:16px 0; }
.disc    { font-size:15px; color:#4a6a88; text-align:center; letter-spacing:1.5px; padding:20px 0; }
.stExpander { border:1px solid #1a2e48 !important; background:#0a1420 !important; }
.stExpander > div > div { background:#0d1825 !important; }
hr { border-color: #111c2a !important; }
.stAlert { background:#150505 !important; border:1px solid #dc2626 !important; color:#f87171 !important; }
</style>
""", unsafe_allow_html=True)


# ── JSON parser (same robust parser as Stock Analyzer) ───────────────────────
def parse_json(txt):
    if not txt: return None
    txt = re.sub(r'```json\s*', '', txt, flags=re.I)
    txt = re.sub(r'```\s*', '', txt)
    txt = txt.strip()
    try: return json.loads(txt)
    except: pass
    a, b = txt.find('{'), txt.rfind('}')
    if a >= 0 and b > a:
        try: return json.loads(txt[a:b+1])
        except: pass
    start = txt.find('{') if txt.find('{') >= 0 else 0
    fragment = txt[start:]
    fragment = re.sub(r',\s*"[^"]*"?\s*:\s*[^,}\]]*$', '', fragment)
    fragment = re.sub(r',\s*"[^"]*"?\s*$', '', fragment)
    fragment = re.sub(r',\s*$', '', fragment)
    depth_brace = depth_bracket = 0
    in_str = escaped = False
    for ch in fragment:
        if escaped: escaped = False; continue
        if ch == '\\': escaped = True; continue
        if ch == '"' and not escaped: in_str = not in_str; continue
        if in_str: continue
        if ch == '{': depth_brace += 1
        elif ch == '}': depth_brace -= 1
        elif ch == '[': depth_bracket += 1
        elif ch == ']': depth_bracket -= 1
    fragment += ']' * max(0, depth_bracket)
    fragment += '}' * max(0, depth_brace)
    try: return json.loads(fragment)
    except: pass
    return None


# ── Verdict helpers ───────────────────────────────────────────────────────────
def verdict_cls(v):
    v = (v or '').upper()
    if 'BULL' in v: return 'bull'
    if 'BEAR' in v: return 'bear'
    return 'neut'

def verdict_icon(v):
    v = (v or '').upper()
    if 'BULL' in v: return '▲'
    if 'BEAR' in v: return '▼'
    return '◆'

def render_verdict(label, verdict, reason):
    cls = verdict_cls(verdict)
    ic  = verdict_icon(verdict)
    st.markdown(f"""
    <div class="verdict-{cls}">
      <div class="verdict-tag verdict-tag-{cls}">{esc(label)}</div>
      <div class="verdict-label-{cls}">{ic} {esc(verdict)}</div>
      <div class="verdict-reason">{esc(reason or '')}</div>
    </div>
    """, unsafe_allow_html=True)

FUND_LABELS = [
    ("revenue","Revenue"),("grossMargin","Gross Margin"),("operatingMargin","Op Margin"),
    ("netMargin","Net Margin"),("eps","EPS"),("forwardEPS","Fwd EPS"),
    ("peRatio","P/E"),("forwardPE","Fwd P/E"),("evEbitda","EV/EBITDA"),
    ("debtToEquity","Debt/Equity"),("freeCashFlow","Free Cash Flow"),
    ("roe","ROE"),("divYield","Div Yield"),
]

def rating_cls(r):
    r = (r or '').lower()
    if 'buy' in r or 'outperform' in r: return 'sig-good'
    if 'sell' in r or 'underperform' in r: return 'sig-bad'
    return 'sig-ok'


# ── FMP helpers (identical to Stock Analyzer) ─────────────────────────────────
def fmp_get(endpoint, fmp_api_key, params=None):
    base = "https://financialmodelingprep.com/api"
    url  = f"{base}{endpoint}?apikey={fmp_api_key}"
    if params:
        url += "&" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

def fmp_fetch_all(ticker, fmp_api_key):
    endpoints = {
        "quote":       f"/v3/quote/{ticker}",
        "profile":     f"/v3/profile/{ticker}",
        "ratios":      f"/v3/ratios-ttm/{ticker}",
        "income":      f"/v3/income-statement/{ticker}",
        "cashflow":    f"/v3/cash-flow-statement/{ticker}",
        "balance":     f"/v3/balance-sheet-statement/{ticker}",
        "estimates":   f"/v3/analyst-estimates/{ticker}",
        "targets":     f"/v4/price-target-consensus",
        "target_list": f"/v4/price-target",
        "dcf":         f"/v3/discounted-cash-flow/{ticker}",
        "earnings_est":      f"/v3/earnings-surprises/{ticker}",
        "earnings_next":     f"/v3/historical/earning_calendar/{ticker}",
        "earnings_upcoming": f"/v3/earning_calendar",
    }
    results = {}
    def fetch_one(key, ep):
        if key in ("targets", "target_list"):
            params = {"symbol": ticker}
        elif key == "earnings_upcoming":
            today  = _dt.now().strftime("%Y-%m-%d")
            future = (_dt.now() + _td(days=180)).strftime("%Y-%m-%d")
            params = {"symbol": ticker, "from": today, "to": future}
        else:
            params = None
        return key, fmp_get(ep, fmp_api_key, params)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_one, k, v): k for k, v in endpoints.items()}
        for fut in as_completed(futures):
            key, data = fut.result()
            results[key] = data
    return results

def finnhub_quote(ticker, fh_key):
    if not fh_key: return {"_error": "no key"}
    clean = clean_ticker(ticker)
    if not clean: return {"_error": "invalid ticker"}
    url = f"https://finnhub.io/api/v1/quote?symbol={clean}&token={fh_key}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode())
            if data.get("c", 0) == 0:
                return {"_error": f"price=0 or no data for {ticker}"}
            return data
    except Exception as e:
        return {"_error": str(e)}

def finnhub_sentiment(ticker, fh_key):
    if not fh_key: return {}
    clean = clean_ticker(ticker)
    url = f"https://finnhub.io/api/v1/news-sentiment?symbol={clean}&token={fh_key}"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode())
            if not data or not data.get("buzz"): return {}
            return data
    except Exception:
        return {}


# ── FMP context formatter (identical to Stock Analyzer) ───────────────────────
def format_fmp_context(ticker, raw):
    lines = [f"=== LIVE MARKET DATA FOR {ticker} (from Financial Modeling Prep) ==="]
    q = (raw.get("quote") or [{}])
    q = q[0] if isinstance(q, list) and q else q if isinstance(q, dict) else {}
    if q:
        price = q.get("price","N/A"); chg = q.get("changesPercentage","N/A")
        mktcap= q.get("marketCap","N/A"); hi52 = q.get("yearHigh","N/A")
        lo52  = q.get("yearLow","N/A"); pe = q.get("pe","N/A"); eps = q.get("eps","N/A")
        avg50 = q.get("priceAvg50","N/A"); avg200 = q.get("priceAvg200","N/A")
        vol   = q.get("avgVolume","N/A")
        lines.append(f"Current Price: ${price} ({chg}% today)")
        lines.append(f"Market Cap: ${mktcap:,}" if isinstance(mktcap,int) else f"Market Cap: {mktcap}")
        lines.append(f"52-Week Range: ${lo52} – ${hi52}")
        lines.append(f"50-Day MA: ${avg50}  |  200-Day MA: ${avg200}")
        lines.append(f"P/E (TTM): {pe}  |  EPS (TTM): ${eps}")
        lines.append(f"Avg Volume: {vol:,}" if isinstance(vol,int) else f"Avg Volume: {vol}")
    p = (raw.get("profile") or [{}])
    p = p[0] if isinstance(p, list) and p else p if isinstance(p, dict) else {}
    if p:
        lines.append(f"Sector: {p.get('sector','N/A')}  |  Industry: {p.get('industry','N/A')}")
        lines.append(f"Description: {str(p.get('description',''))[:300]}")
        lines.append(f"Beta: {p.get('beta','N/A')}")
    r = (raw.get("ratios") or [{}])
    r = r[0] if isinstance(r, list) and r else r if isinstance(r, dict) else {}
    if r:
        def fmt(v, pct=False, x=False):
            if v is None: return "N/A"
            try:
                f = float(v)
                if pct: return f"{f*100:.1f}%"
                if x:   return f"{f:.1f}x"
                return f"{f:.2f}"
            except: return str(v)
        lines.append("--- KEY RATIOS (TTM) ---")
        lines.append(f"P/E: {fmt(r.get('peRatioTTM'),x=True)}  |  Fwd P/E: {fmt(r.get('priceEarningsRatioTTM'),x=True)}")
        lines.append(f"P/S: {fmt(r.get('priceToSalesRatioTTM'),x=True)}  |  P/B: {fmt(r.get('priceToBookRatioTTM'),x=True)}")
        lines.append(f"EV/EBITDA: {fmt(r.get('enterpriseValueMultipleTTM'),x=True)}")
        lines.append(f"Gross Margin: {fmt(r.get('grossProfitMarginTTM'),pct=True)}  |  Net Margin: {fmt(r.get('netProfitMarginTTM'),pct=True)}")
        lines.append(f"Op Margin: {fmt(r.get('operatingProfitMarginTTM'),pct=True)}")
        lines.append(f"ROE: {fmt(r.get('returnOnEquityTTM'),pct=True)}  |  ROIC: {fmt(r.get('returnOnInvestedCapitalTTM'),pct=True)}")
        lines.append(f"Debt/Equity: {fmt(r.get('debtEquityRatioTTM'))}  |  Current Ratio: {fmt(r.get('currentRatioTTM'))}")
        lines.append(f"FCF Yield: {fmt(r.get('freeCashFlowYieldTTM'),pct=True)}")
        lines.append(f"Dividend Yield: {fmt(r.get('dividendYieldTTM'),pct=True)}")
    inc = (raw.get("income") or [{}])
    inc = inc[0] if isinstance(inc, list) and inc else {}
    def fm(v):
        if v == "N/A" or v is None: return "N/A"
        try:
            n = float(v)
            if abs(n) >= 1e9: return f"${n/1e9:.2f}B"
            if abs(n) >= 1e6: return f"${n/1e6:.1f}M"
            return f"${n:,.0f}"
        except: return str(v)
    if inc:
        lines.append("--- INCOME STATEMENT (Most Recent Annual) ---")
        lines.append(f"Period: {inc.get('date','N/A')}")
        lines.append(f"Revenue: {fm(inc.get('revenue'))}  |  Gross Profit: {fm(inc.get('grossProfit'))}")
        lines.append(f"EBITDA: {fm(inc.get('ebitda'))}  |  Operating Income: {fm(inc.get('operatingIncome'))}")
        lines.append(f"Net Income: {fm(inc.get('netIncome'))}  |  EPS: ${inc.get('eps','N/A')}")
    cf = (raw.get("cashflow") or [{}])
    cf = cf[0] if isinstance(cf, list) and cf else {}
    if cf:
        lines.append("--- CASH FLOW (Most Recent Annual) ---")
        lines.append(f"Operating CF: {fm(cf.get('operatingCashFlow'))}  |  Free CF: {fm(cf.get('freeCashFlow'))}  |  CapEx: {fm(cf.get('capitalExpenditure'))}")
    bs = (raw.get("balance") or [{}])
    bs = bs[0] if isinstance(bs, list) and bs else {}
    if bs:
        lines.append("--- BALANCE SHEET (Most Recent) ---")
        lines.append(f"Cash: {fm(bs.get('cashAndCashEquivalents'))}  |  Total Debt: {fm(bs.get('totalDebt'))}  |  Equity: {fm(bs.get('totalStockholdersEquity'))}")
    dcf = raw.get("dcf")
    if isinstance(dcf, list) and dcf: dcf = dcf[0]
    if isinstance(dcf, dict) and dcf.get("dcf"):
        lines.append(f"--- FMP DCF INTRINSIC VALUE: ${dcf.get('dcf','N/A')} (model date: {dcf.get('date','N/A')}) ---")
        lines.append("NOTE: Use this as one input but apply sector-appropriate adjustments.")
    est = (raw.get("estimates") or [{}])
    est = est[0] if isinstance(est, list) and est else {}
    if est:
        lines.append("--- ANALYST FORWARD ESTIMATES ---")
        lines.append(f"Est. Revenue (next yr): {fm(est.get('estimatedRevenueAvg'))}")
        lines.append(f"Est. EPS (next yr): ${est.get('estimatedEpsAvg','N/A')}")
        lines.append(f"Est. EBITDA (next yr): {fm(est.get('estimatedEbitdaAvg'))}")
        lines.append(f"Number of analysts: {est.get('numberAnalystEstimatedRevenue','N/A')}")
    tgt = raw.get("targets")
    if isinstance(tgt, list) and tgt: tgt = tgt[0]
    if isinstance(tgt, dict):
        lines.append("--- ANALYST PRICE TARGETS (Consensus) ---")
        lines.append(f"Consensus Target: ${tgt.get('targetConsensus','N/A')}")
        lines.append(f"High Target: ${tgt.get('targetHigh','N/A')}  |  Low Target: ${tgt.get('targetLow','N/A')}")
        lines.append(f"Median Target: ${tgt.get('targetMedian','N/A')}")
    tlist = raw.get("target_list") or []
    if isinstance(tlist, list) and tlist:
        lines.append("--- RECENT INDIVIDUAL ANALYST RATINGS ---")
        for a in tlist[:5]:
            lines.append(f"  {a.get('analystCompany','?')} | {a.get('analystName','?')} | "
                         f"Target: ${a.get('priceTarget','?')} | "
                         f"Published: {a.get('publishedDate','?')[:10] if a.get('publishedDate') else '?'}")
    lines.append(f"=== END LIVE DATA FOR {ticker} ===")
    return "\n".join(lines)


# ── Sector-aware intrinsic value calculator (identical to Stock Analyzer) ─────
SECTOR_MULTIPLES = {
    "Technology":             {"ev_rev": 8.0,  "kind": "growth"},
    "Communication Services": {"ev_rev": 6.0,  "kind": "growth"},
    "Healthcare":             {"ev_rev": 5.0,  "kind": "growth"},
    "Consumer Discretionary": {"ev_rev": 2.0,  "kind": "mixed"},
    "Utilities":              {"ev_ebitda": 10.0, "kind": "profitable"},
    "Energy":                 {"ev_ebitda": 7.0,  "kind": "profitable"},
    "Financials":             {"pb": 1.5,          "kind": "financial"},
    "Industrials":            {"ev_ebitda": 12.0,  "kind": "profitable"},
    "Materials":              {"ev_ebitda": 10.0,  "kind": "profitable"},
    "Real Estate":            {"ev_ebitda": 20.0,  "kind": "profitable"},
    "Consumer Staples":       {"ev_ebitda": 14.0,  "kind": "profitable"},
}

def calc_intrinsic_value(raw_fmp):
    try:
        q   = (raw_fmp.get("quote") or [{}])
        q   = q[0] if isinstance(q,list) and q else q if isinstance(q,dict) else {}
        inc = (raw_fmp.get("income") or [{}])
        inc = inc[0] if isinstance(inc,list) and inc else {}
        cf  = (raw_fmp.get("cashflow") or [{}])
        cf  = cf[0] if isinstance(cf,list) and cf else {}
        bs  = (raw_fmp.get("balance") or [{}])
        bs  = bs[0] if isinstance(bs,list) and bs else {}
        est = (raw_fmp.get("estimates") or [{}])
        est = est[0] if isinstance(est,list) and est else {}
        pro = (raw_fmp.get("profile") or [{}])
        pro = pro[0] if isinstance(pro,list) and pro else pro if isinstance(pro,dict) else {}
        price      = float(q.get("price") or 0)
        mkt_cap    = float(q.get("marketCap") or 0)
        shares     = float(q.get("sharesOutstanding") or 0)
        if shares == 0 and price > 0 and mkt_cap > 0:
            shares = mkt_cap / price
        fcf        = float(cf.get("freeCashFlow") or 0)
        net_income = float(inc.get("netIncome") or 0)
        revenue    = float(inc.get("revenue") or 0)
        ebitda     = float(inc.get("ebitda") or 0)
        total_debt = float(bs.get("totalDebt") or 0)
        cash_      = float(bs.get("cashAndCashEquivalents") or 0)
        fwd_rev    = float(est.get("estimatedRevenueAvg") or 0)
        book_val   = float(bs.get("totalStockholdersEquity") or 0)
        net_debt   = total_debt - cash_
        sector     = pro.get("sector","Technology")
        dcf_raw = raw_fmp.get("dcf")
        if isinstance(dcf_raw,list) and dcf_raw: dcf_raw = dcf_raw[0]
        fmp_dcf = float(dcf_raw.get("dcf",0)) if isinstance(dcf_raw,dict) else 0
        is_profitable = fcf > 0 and net_income > 0 and ebitda > 0
        is_financial  = "financial" in sector.lower() or "bank" in sector.lower()
        def fv(v): return f"${v:,.2f}"
        if is_financial and book_val > 0 and shares > 0:
            mult = SECTOR_MULTIPLES.get("Financials",{}).get("pb",1.5)
            bvps = book_val / shares
            iv   = bvps * mult
            return (fv(iv), f"P/Book {mult}x (Financials - live)", f"Book/share {fv(bvps)} x {mult}x")
        elif is_profitable and fmp_dcf > 0:
            return (fv(fmp_dcf), "FMP DCF Model (live)", f"Live FCF {fv(fcf/1e9)}B")
        elif is_profitable and ebitda > 0 and shares > 0:
            mult = SECTOR_MULTIPLES.get(sector,{}).get("ev_ebitda",12.0)
            iv   = max(0, (ebitda * mult - net_debt) / shares)
            return (fv(iv), f"EV/EBITDA {mult}x ({sector} - live)", f"EBITDA {fv(ebitda/1e9)}B x {mult}x")
        else:
            rev_use   = fwd_rev if fwd_rev > 0 else revenue
            rev_label = "forward" if fwd_rev > 0 else "TTM"
            if rev_use <= 0 or shares <= 0: return (None, None, None)
            mult = SECTOR_MULTIPLES.get(sector,{}).get("ev_rev", 8.0)
            if revenue > 0 and fwd_rev > revenue:
                growth = (fwd_rev - revenue) / revenue
                if growth > 0.5:   mult = round(mult * 1.3, 1)
                elif growth > 0.3: mult = round(mult * 1.15, 1)
            iv = max(0, (rev_use * mult - net_debt) / shares)
            return (fv(iv), f"EV/Revenue {mult}x {rev_label} (pre-profit - live)",
                    f"{fv(rev_use/1e9)}B {rev_label} rev x {mult}x minus net debt")
    except Exception:
        return (None, None, None)


# ── Authentication ────────────────────────────────────────────────────────────
import hashlib, base64

def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a PBKDF2-SHA256 hash."""
    try:
        if stored_hash.startswith('pbkdf2$'):
            _, algo, iterations, salt_b64, key_b64 = stored_hash.split('$')
            salt  = base64.b64decode(salt_b64)
            key   = base64.b64decode(key_b64)
            check = hashlib.pbkdf2_hmac(algo.replace('sha','sha-').replace('sha-256','sha256'),
                                         password.encode('utf-8'), salt, int(iterations))
            return check == key
    except Exception:
        pass
    return False

def _load_users() -> dict:
    """Load users from Streamlit Secrets. Returns {username: {name, password}}."""
    users = {}
    try:
        raw = st.secrets.get('users', {})
        for uname, udata in raw.items():
            users[uname.lower()] = {
                'name':     udata.get('name', uname.capitalize()),
                'password': udata.get('password', ''),
            }
    except Exception:
        pass
    return users

def _render_login():
    """Render the login screen. Returns True if login succeeded."""
    st.markdown("""
    <div style="max-width:420px;margin:80px auto 0">
      <div style="text-align:center;margin-bottom:32px">
        <div style="font-size:15px;letter-spacing:4px;color:#3b82f6;
                    text-transform:uppercase;margin-bottom:8px">Portfolio Analysis Terminal</div>
        <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#f0f6ff">
          NGUYENILY X
        </div>
        <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:700;
                    color:#3b82f6;letter-spacing:3px;margin-top:4px">PORTFOLIO IQ</div>
      </div>
      <div style="background:#0d1825;border:1px solid #1a2e48;padding:28px 24px;margin-bottom:16px">
        <div style="font-size:15px;letter-spacing:2px;color:#94a3b8;
                    text-transform:uppercase;margin-bottom:20px">Sign In</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", placeholder="Enter your username",
                                  key="login_username")
        password = st.text_input("Password", placeholder="Enter your password",
                                  type="password", key="login_password")
        submitted = st.form_submit_button("SIGN IN", use_container_width=True)

    if submitted:
        u = (username or '').strip().lower()
        p = (password or '')
        if not u or not p:
            st.error("Please enter both username and password.")
            return False
        users = _load_users()
        if u not in users:
            st.error("Invalid username or password.")
            return False
        if not _verify_password(p, users[u]['password']):
            st.error("Invalid username or password.")
            return False
        # Success — store in session
        st.session_state['authenticated'] = True
        st.session_state['auth_user']     = u
        st.session_state['auth_name']     = users[u]['name']
        st.rerun()

    st.markdown("""
    <div style="text-align:center;margin-top:16px;font-size:15px;color:#4a6a88">
      Contact the app administrator to get access.
    </div>
    """, unsafe_allow_html=True)
    return False

# ── Gate the entire app behind login ──────────────────────────────────────────
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
if 'auth_user' not in st.session_state:
    st.session_state['auth_user'] = ''
if 'auth_name' not in st.session_state:
    st.session_state['auth_name'] = ''

if not st.session_state['authenticated']:
    _render_login()
    st.stop()

# ── Session state helpers ─────────────────────────────────────────────────────
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

# ── Initialise session state ──────────────────────────────────────────────────
ss('holdings',      [{'ticker':'','shares':'','cost':''} for _ in range(15)])
ss('result',        None)
ss('running',       False)
ss('stop_requested',False)
ss('do_analyze',    False)
ss('data_source',   None)
ss('fmp_tickers',   [])
ss('fmp_raw_data',  {})
ss('fmp_locked',    {})
ss('finnhub_prices',{})
ss('finnhub_sent',  {})
ss('finnhub_news',  {})
ss('raw_response',  None)
ss('portfolio_mode','manual')
ss('gs_url',        '')

# Keep holdings list at exactly 15 entries
while len(st.session_state['holdings']) < 15:
    st.session_state['holdings'].append({'ticker':'','shares':'','cost':''})
st.session_state['holdings'] = st.session_state['holdings'][:15]

# ── API keys (server-side only — never exposed to browser) ────────────────────
api_key = ""
try:    api_key = st.secrets["ANTHROPIC_API_KEY"]
except: pass
if not api_key:
    try:    api_key = st.secrets.get("ANTHROPIC_API_KEY","")
    except: pass
if not api_key: api_key = os.environ.get("ANTHROPIC_API_KEY","")

fmp_key = ""
try:    fmp_key = st.secrets["FMP_API_KEY"]
except: pass
if not fmp_key:
    try:    fmp_key = st.secrets.get("FMP_API_KEY","")
    except: pass
if not fmp_key: fmp_key = os.environ.get("FMP_API_KEY","")

finnhub_key = ""
try:    finnhub_key = st.secrets["FINNHUB_API_KEY"]
except: pass
if not finnhub_key:
    try:    finnhub_key = st.secrets.get("FINNHUB_API_KEY","")
    except: pass
if not finnhub_key: finnhub_key = os.environ.get("FINNHUB_API_KEY","")

# ── Header ────────────────────────────────────────────────────────────────────
auth_name = st.session_state.get('auth_name', '')
col_hdr, col_logout = st.columns([5, 1])
with col_hdr:
    st.markdown(f"""
    <div style="display:flex;align-items:flex-end;gap:12px;margin-bottom:20px;
                padding-bottom:14px;border-bottom:1px solid #111c2a">
      <div style="width:8px;height:8px;background:#3b82f6;border-radius:50%;
                  margin-bottom:4px;box-shadow:0 0 12px #3b82f6"></div>
      <div>
        <div style="font-size:15px;letter-spacing:4px;color:#3b82f6;
                    text-transform:uppercase;margin-bottom:2px">Portfolio Analysis Terminal</div>
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#f0f6ff">
          NGUYENILY X &nbsp;<span style="color:#3b82f6">—</span>&nbsp; PORTFOLIO IQ
        </div>
        <div style="font-size:15px;color:#5a7a99;margin-top:4px">
          Welcome, <span style="color:#93c5fd;font-weight:700">{esc(auth_name)}</span>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with col_logout:
    st.markdown('<div style="padding-top:18px"></div>', unsafe_allow_html=True)
    if st.button("Sign Out", key="btn_logout", use_container_width=True):
        # Clear all session state on logout
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ── Guard: require API key ────────────────────────────────────────────────────
if not api_key:
    st.markdown("""
    <div style="background:#150505;border:1px solid #dc2626;padding:20px;color:#f87171;font-size:15px;line-height:2">
      <div style="font-family:'Syne',sans-serif;font-size:15px;letter-spacing:2px;color:#f87171;margin-bottom:12px">⚠ API KEY NOT FOUND</div>
      <b>To fix this:</b><br>
      1. Go to your app on <b>share.streamlit.io</b><br>
      2. Click the <b>⋮ menu → Settings → Secrets</b><br>
      3. Paste this (with your real keys):<br>
      <code style="background:#0a0000;padding:8px 12px;display:block;margin:8px 0;color:#fbbf24">ANTHROPIC_API_KEY = "sk-ant-..."<br>FMP_API_KEY = "..."<br>FINNHUB_API_KEY = "..."</code>
      4. Click <b>Save</b> — the app restarts automatically
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Holdings Input ────────────────────────────────────────────────────────────
with st.expander("▸ MY PORTFOLIO — up to 15 holdings", expanded=True):
    st.markdown('<div class="label" style="margin-bottom:8px">How would you like to enter your portfolio?</div>', unsafe_allow_html=True)
    mc1, mc2 = st.columns(2)
    with mc1:
        if st.button("📥 Import from Google Sheets", use_container_width=True, key="btn_mode_import"):
            st.session_state['portfolio_mode'] = 'import'
    with mc2:
        if st.button("✏️ Enter Manually", use_container_width=True, key="btn_mode_manual"):
            st.session_state['portfolio_mode'] = 'manual'

    port_mode = st.session_state.get('portfolio_mode', 'manual')

    # ── Google Sheets import ──
    if port_mode == 'import':
        st.markdown('''
        <div style="background:#090f1a;border:1px solid #1a2e48;padding:12px 14px;margin:10px 0">
          <div style="font-size:15px;letter-spacing:2px;color:#3b82f6;text-transform:uppercase;margin-bottom:8px">📊 Google Sheets Setup</div>
          <div style="font-size:15px;color:#94a3b8;line-height:2">
            1. Create a sheet with columns: <b style="color:#e2e8f0">Ticker | Shares | Avg Cost</b><br>
            2. Click <b style="color:#e2e8f0">File → Share → Publish to web → CSV → Publish</b><br>
            3. Paste the URL below
          </div>
        </div>''', unsafe_allow_html=True)

        gs_url_input = st.text_input(
            "Google Sheet Published CSV URL",
            value=st.session_state.get('gs_url',''),
            placeholder="https://docs.google.com/spreadsheets/d/.../pub?output=csv",
            key="gs_url_input"
        )
        do_import = st.button("🚀 Run Import", use_container_width=True, key="btn_do_import")

        if do_import:
            gs_url = (gs_url_input or '').strip()
            # Security: only allow Google Sheets URLs
            if not gs_url:
                st.error("Please paste a Google Sheets URL first.")
            elif not re.match(r'https://docs\.google\.com/spreadsheets/', gs_url):
                st.error("Only Google Sheets URLs are accepted.")
            else:
                with st.spinner("Fetching your portfolio..."):
                    try:
                        import csv as _csv, io as _io
                        url = gs_url
                        if 'output=csv' not in url:
                            if '/pub?' in url: url += ('&output=csv' if '?' in url else '?output=csv')
                            else:
                                m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
                                if m: url = f'https://docs.google.com/spreadsheets/d/{m.group(1)}/pub?output=csv'
                                else: st.error('Could not parse the Google Sheets URL.'); st.stop()
                        with urllib.request.urlopen(url, timeout=10) as r:
                            raw_csv = r.read().decode('utf-8-sig')
                        reader = _csv.DictReader(_io.StringIO(raw_csv))
                        rows = list(reader)
                        if not rows: st.error("The sheet appears empty.")
                        else:
                            headers = {k.lower().strip(): k for k in rows[0].keys()}
                            def find_col(candidates):
                                for cand in candidates:
                                    for h_low, h_orig in headers.items():
                                        if cand in h_low: return h_orig
                                return None
                            ticker_col = find_col(['ticker','symbol','stock'])
                            shares_col = find_col(['shares','quantity','qty','units'])
                            cost_col   = find_col(['avg cost','average cost','cost basis','avg price','average price','cost per','price'])
                            if not ticker_col: st.error(f"No Ticker/Symbol column found. Columns: **{', '.join(rows[0].keys())}**")
                            elif not shares_col: st.error(f"No Shares/Quantity column found. Columns: **{', '.join(rows[0].keys())}**")
                            else:
                                parsed = []
                                for row in rows:
                                    tk  = clean_ticker(row.get(ticker_col,''))
                                    sh  = clean_number(row.get(shares_col,''))
                                    cst = clean_number(row.get(cost_col,'') if cost_col else '')
                                    if tk and sh: parsed.append({'ticker': tk, 'shares': sh, 'cost': cst})
                                if not parsed: st.error("No valid holdings found.")
                                else:
                                    def mkt_val(h):
                                        try: return float(h['shares']) * float(h['cost']) if h['cost'] else float(h['shares'])
                                        except: return 0
                                    parsed.sort(key=mkt_val, reverse=True)
                                    parsed = parsed[:15]
                                    parsed.sort(key=lambda h: h['ticker'])
                                    st.session_state['holdings'] = [{'ticker':'','shares':'','cost':''} for _ in range(15)]
                                    for i, h in enumerate(parsed):
                                        st.session_state['holdings'][i] = h
                                        st.session_state[f'htk{i}'] = h['ticker']
                                        st.session_state[f'hsh{i}'] = h['shares']
                                        st.session_state[f'hco{i}'] = h['cost']
                                    for i in range(len(parsed), 15):
                                        for f2 in ['htk','hsh','hco']:
                                            st.session_state[f'{f2}{i}'] = ''
                                    st.session_state['gs_url'] = gs_url
                                    st.session_state['portfolio_mode'] = 'manual'
                                    st.success(f"✓ Imported {len(parsed)} holdings" + (" (top 15 by value)" if len(parsed)==15 else ""))
                                    st.rerun()
                    except Exception as e:
                        err = str(e)
                        if '404' in err: st.error('Sheet not found (404). Publish it as CSV first via File → Share → Publish to web.')
                        elif '403' in err or 'permission' in err.lower(): st.error('Permission denied. Sheet must be published publicly.')
                        else: st.error(f'Import failed: {e}')

    # ── Manual entry ──
    filled_count = sum(1 for h in st.session_state['holdings'] if h.get('ticker'))
    st.markdown(
        f'<div style="font-size:15px;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;margin:12px 0 4px">'
        f'Holdings ({filled_count}/15 filled) — Ticker · Shares · Avg Cost</div>'
        '<div style="font-size:15px;color:#3b82f6;margin-bottom:8px">ℹ️ All three fields required per row for analysis.</div>',
        unsafe_allow_html=True)
    for i in range(15):
        c1, c2, c3, c4 = st.columns([0.5, 2, 2, 2])
        with c1:
            st.markdown(f'<div style="font-size:15px;color:#fff;padding-top:8px">#{i+1}</div>', unsafe_allow_html=True)
        with c2:
            raw_tk = st.text_input(f"Tk{i}", value=st.session_state['holdings'][i].get('ticker',''),
                placeholder="AAPL", max_chars=6, key=f"htk{i}", label_visibility="collapsed")
            st.session_state['holdings'][i]['ticker'] = clean_ticker(raw_tk)
        with c3:
            raw_sh = st.text_input(f"Sh{i}", value=st.session_state['holdings'][i].get('shares',''),
                placeholder="Shares", key=f"hsh{i}", label_visibility="collapsed")
            st.session_state['holdings'][i]['shares'] = clean_number(raw_sh)
        with c4:
            raw_co = st.text_input(f"Co{i}", value=st.session_state['holdings'][i].get('cost',''),
                placeholder="Avg $", key=f"hco{i}", label_visibility="collapsed")
            st.session_state['holdings'][i]['cost'] = clean_number(raw_co)

# ── Derived values ────────────────────────────────────────────────────────────
port_holds = [h for h in st.session_state['holdings']
              if h.get('ticker') and h.get('shares') and h.get('cost')]
port_val   = 0.0
for h in port_holds:
    try: port_val += float(h['shares']) * float(h['cost'])
    except: pass

# ── Portfolio value summary ───────────────────────────────────────────────────
if port_holds:
    total_html = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:10px 0">'
    total_html += '<div class="card card-blue" style="padding:10px 14px;flex:1;min-width:140px">'
    total_html += '<div class="label">Total Cost Basis</div>'
    total_html += f'<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#f0f6ff">${port_val:,.0f}</div>'
    total_html += '</div>'
    total_html += '<div class="card" style="padding:10px 14px;flex:1;min-width:140px">'
    total_html += '<div class="label">Holdings</div>'
    total_html += f'<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#93c5fd">{len(port_holds)}</div>'
    total_html += '</div></div>'
    st.markdown(total_html, unsafe_allow_html=True)

st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

# ── Button row ────────────────────────────────────────────────────────────────
is_running = st.session_state['running']
btn_label  = (f"ANALYZE PORTFOLIO — {len(port_holds)} HOLDING{'S' if len(port_holds)!=1 else ''}"
              if port_holds else "ENTER HOLDINGS TO ANALYZE")

analyze_clicked = st.button(
    btn_label,
    disabled=not port_holds or is_running,
    use_container_width=True,
    key="btn_analyze"
)

_current_params = {}
_param_str = '&'.join(f'{k}={v}' for k, v in _current_params.items())
_stop_url   = "?action=stop"
_clear_url  = "?action=clear"

_action = st.query_params.get('action','')
if _action == 'stop':
    st.query_params.pop('action', None)
    st.session_state['running'] = False
    st.session_state['stop_requested'] = True
    st.rerun()
elif _action == 'clear':
    st.query_params.pop('action', None)
    for _k in ['result','running','data_source','fmp_tickers','stop_requested','do_analyze',
               'fmp_raw_data','fmp_locked','finnhub_prices','finnhub_sent','finnhub_news','raw_response']:
        if _k in ('result','data_source','raw_response'): st.session_state[_k] = None
        elif _k in ('running','stop_requested','do_analyze'): st.session_state[_k] = False
        elif _k in ('fmp_raw_data','fmp_locked','finnhub_prices','finnhub_sent','finnhub_news'): st.session_state[_k] = {}
        elif _k == 'fmp_tickers': st.session_state[_k] = []
    st.session_state['holdings'] = [{'ticker':'','shares':'','cost':''} for _ in range(15)]
    st.query_params.clear()
    st.rerun()

_stop_bg  = "#2d0a0a" if is_running else "#1a0808"
_stop_bdr = "#f87171" if is_running else "#dc2626"
_stop_clr = "#fca5a5" if is_running else "#f87171"
_btn_base = ("font-family:monospace;font-size:15px;font-weight:700;letter-spacing:2px;"
             "text-transform:uppercase;padding:9px 4px;width:100%;border-radius:0;"
             "display:block;text-align:center;text-decoration:none;")
st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px;margin-bottom:6px">
  <a href="{_stop_url}" style="text-decoration:none;">
    <div style="{_btn_base}background:{_stop_bg};border:1px solid {_stop_bdr};color:{_stop_clr};">
      &#9632; STOP
    </div>
  </a>
  <a href="{_clear_url}" style="text-decoration:none">
    <div style="{_btn_base}background:#2d2500;border:1px solid #fbbf24;color:#fde68a;cursor:pointer">
      &#10005; CLEAR ALL
    </div>
  </a>
</div>
""", unsafe_allow_html=True)

# ── Phase 1: arm the stop button then rerun into Phase 2 ─────────────────────
if analyze_clicked and not st.session_state['running']:
    st.session_state['running']       = True
    st.session_state['stop_requested']= False
    st.session_state['result']        = None
    st.session_state['do_analyze']    = True
    st.rerun()

# ── Phase 2: run the analysis ─────────────────────────────────────────────────
if st.session_state.get('do_analyze') and st.session_state['running']:
    st.session_state['do_analyze'] = False

    port_holds = [h for h in st.session_state['holdings']
                  if h.get('ticker') and h.get('shares') and h.get('cost')]
    port_val   = 0.0
    for h in port_holds:
        try: port_val += float(h['shares']) * float(h['cost'])
        except: pass

    # Sanitise tickers one final time at analysis time
    valid_tickers = [clean_ticker(h['ticker']) for h in port_holds if clean_ticker(h['ticker'])]

    # ── Build portfolio note for prompt ──
    port_note = (f"Portfolio ({len(port_holds)} holdings ~${port_val:,.0f}): "
                 + ", ".join(f"{h['ticker']} {esc(h['shares'])}sh@${esc(h['cost'])}"
                             for h in port_holds))

    # ── Ticker validation via Finnhub ──
    st.write(f"Validating tickers: {', '.join(valid_tickers)}...")
    if finnhub_key:
        invalid = []
        for tk in valid_tickers:
            fh = finnhub_quote(tk, finnhub_key)
            if not fh.get("c") or fh.get("c",0) == 0:
                invalid.append(tk)
        if invalid:
            st.error(f"⚠ Invalid ticker{'s' if len(invalid)>1 else ''}: **{', '.join(invalid)}**\n\n"
                     f"Please use valid stock ticker symbols (e.g. AAPL, NVDA). Company names are not supported.")
            st.session_state['running'] = False
            st.stop()
    st.write(f"✓ Tickers valid: {', '.join(valid_tickers)}")

    with st.status("Analyzing portfolio...", expanded=True) as status:
        st.write("Fetching live market data...")
        st.info("💡 Keep this tab open and active. Streamlit pauses when the tab is hidden on mobile.")

        fmp_contexts    = {}
        finnhub_prices  = {}
        local_raw_data  = {}
        local_sentiment = {}

        if fmp_key:
            def fetch_ticker(tk):
                clean_tk = clean_ticker(tk)
                fmp_raw  = fmp_fetch_all(clean_tk, fmp_key)
                fh_quote = finnhub_quote(clean_tk, finnhub_key) if finnhub_key else {}
                fh_sent  = finnhub_sentiment(clean_tk, finnhub_key) if finnhub_key else {}
                fh_earn  = {}
                fh_news  = []
                if finnhub_key:
                    try:
                        today  = _dt.now().strftime("%Y-%m-%d")
                        future = (_dt.now() + _td(days=365)).strftime("%Y-%m-%d")
                        url = (f"https://finnhub.io/api/v1/calendar/earnings"
                               f"?symbol={clean_tk}&from={today}&to={future}&token={finnhub_key}")
                        with urllib.request.urlopen(url, timeout=8) as r:
                            fh_earn = json.loads(r.read().decode())
                    except Exception:
                        fh_earn = {}
                    # Fetch recent company news (last 30 days)
                    try:
                        from_date = (_dt.now() - _td(days=30)).strftime("%Y-%m-%d")
                        to_date   = _dt.now().strftime("%Y-%m-%d")
                        news_url  = (f"https://finnhub.io/api/v1/company-news"
                                     f"?symbol={clean_tk}&from={from_date}&to={to_date}&token={finnhub_key}")
                        with urllib.request.urlopen(news_url, timeout=8) as r:
                            all_news = json.loads(r.read().decode())
                            # Keep most recent 8 articles, strip to safe fields only
                            fh_news = [
                                {
                                    "headline": str(n.get("headline",""))[:200],
                                    "source":   str(n.get("source",""))[:60],
                                    "datetime": n.get("datetime", 0),
                                    "url":      str(n.get("url",""))[:300],
                                    "summary":  str(n.get("summary",""))[:300],
                                }
                                for n in (all_news or [])
                                if n.get("headline")
                            ][:8]
                    except Exception:
                        fh_news = []
                return tk, fmp_raw, fh_quote, fh_sent, fh_earn, fh_news

            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(fetch_ticker, tk): tk for tk in valid_tickers}
                for fut in as_completed(futures):
                    tk, raw, fh, fh_sent, fh_earn, fh_news = fut.result()
                    if fh.get("c") and fh["c"] > 0:
                        if isinstance(raw.get("quote"), list) and raw["quote"]:
                            raw["quote"][0]["price"] = fh["c"]
                            raw["quote"][0]["changesPercentage"] = fh.get("dp",0)
                        elif isinstance(raw.get("quote"), dict):
                            raw["quote"]["price"] = fh["c"]
                            raw["quote"]["changesPercentage"] = fh.get("dp",0)
                        else:
                            raw["quote"] = [{"price": fh["c"], "changesPercentage": fh.get("dp",0)}]
                        finnhub_prices[tk] = fh
                        src = f"Finnhub ${fh['c']:,.2f} (real-time) + FMP (fundamentals)"
                    elif fh.get("_error"):
                        src = f"FMP only — Finnhub error: {fh['_error']}"
                    else:
                        src = "FMP only (Finnhub returned no price)"
                    fmp_contexts[tk]   = format_fmp_context(tk, raw)
                    local_raw_data[tk] = raw
                    if fh_sent: local_sentiment[tk] = fh_sent
                    if fh_earn: raw['_fh_earnings'] = fh_earn
                    if fh_news: raw['_fh_news'] = fh_news
                    st.write(f"  ✓ {tk} data fetched ({src}){', ' + str(len(fh_news)) + ' news articles' if fh_news else ''}")

            st.session_state['fmp_raw_data']   = local_raw_data
            st.session_state['finnhub_prices'] = finnhub_prices
            st.session_state['finnhub_sent']   = local_sentiment
            # Build per-ticker news map for display
            local_news = {tk: raw.get('_fh_news', []) for tk, raw in local_raw_data.items() if raw.get('_fh_news')}
            st.session_state['finnhub_news']   = local_news
        else:
            st.warning("⚠ FMP_API_KEY not set — using Claude training data only. Add FMP_API_KEY to Secrets for live data.")

        # ── Build locked data block (hard-override post-parse) ────────────────
        locked_data  = {}
        live_data_block = ""

        if fmp_contexts and local_raw_data:
            locked_lines = []
            for tk, raw_fmp in local_raw_data.items():
                locked = {}
                q = (raw_fmp.get("quote") or [{}])
                q = q[0] if isinstance(q,list) and q else q if isinstance(q,dict) else {}
                if q.get("price"):
                    p = q["price"]
                    locked["currentPrice"] = f"${p:,.2f}" if isinstance(p,(int,float)) else f"${p}"
                    locked["52wkHigh"]  = q.get("yearHigh","N/A")
                    locked["52wkLow"]   = q.get("yearLow","N/A")
                    locked["mktCap"]    = q.get("marketCap","N/A")
                    locked["pe"]        = q.get("pe","N/A")
                    locked["ma50"]      = q.get("priceAvg50","N/A")
                    locked["ma200"]     = q.get("priceAvg200","N/A")
                tgt = raw_fmp.get("targets")
                if isinstance(tgt,list) and tgt: tgt = tgt[0]
                if isinstance(tgt,dict) and tgt.get("targetConsensus"):
                    tc = tgt["targetConsensus"]
                    locked["analystConsensus"]     = f"${tc}" if not str(tc).startswith("$") else str(tc)
                    locked["analystTargetHigh"]    = tgt.get("targetHigh","N/A")
                    locked["analystTargetLow"]     = tgt.get("targetLow","N/A")
                    locked["analystTargetMedian"]  = tgt.get("targetMedian","N/A")
                dcf = raw_fmp.get("dcf")
                if isinstance(dcf,list) and dcf: dcf = dcf[0]
                if isinstance(dcf,dict) and dcf.get("dcf"):
                    locked["fmpDCF"] = f"${dcf['dcf']}"
                r2 = (raw_fmp.get("ratios") or [{}])
                r2 = r2[0] if isinstance(r2,list) and r2 else r2 if isinstance(r2,dict) else {}
                if r2:
                    def fmt_r(v):
                        if v is None: return "N/A"
                        try: return f"{float(v):.2f}"
                        except: return str(v)
                    locked["peRatio"]    = fmt_r(r2.get("peRatioTTM"))
                    locked["evEbitda"]   = fmt_r(r2.get("enterpriseValueMultipleTTM"))
                    locked["psRatio"]    = fmt_r(r2.get("priceToSalesRatioTTM"))
                    locked["netMargin"]  = f"{float(r2.get('netProfitMarginTTM',0))*100:.1f}%" if r2.get("netProfitMarginTTM") else "N/A"
                    locked["grossMargin"]= f"{float(r2.get('grossProfitMarginTTM',0))*100:.1f}%" if r2.get("grossProfitMarginTTM") else "N/A"
                    locked["roe"]        = f"{float(r2.get('returnOnEquityTTM',0))*100:.1f}%" if r2.get("returnOnEquityTTM") else "N/A"
                    locked["debtEq"]     = fmt_r(r2.get("debtEquityRatioTTM"))
                    locked["fcfYield"]   = f"{float(r2.get('freeCashFlowYieldTTM',0))*100:.1f}%" if r2.get("freeCashFlowYieldTTM") else "N/A"
                inc2 = (raw_fmp.get("income") or [{}])
                inc2 = inc2[0] if isinstance(inc2,list) and inc2 else {}
                if inc2:
                    def fm2(v):
                        if v is None: return "N/A"
                        try:
                            n=float(v)
                            if abs(n)>=1e9: return f"${n/1e9:.2f}B"
                            if abs(n)>=1e6: return f"${n/1e6:.1f}M"
                            return f"${n:,.0f}"
                        except: return str(v)
                    locked["revenue"]   = fm2(inc2.get("revenue"))
                    locked["ebitda"]    = fm2(inc2.get("ebitda"))
                    locked["netIncome"] = fm2(inc2.get("netIncome"))
                    locked["eps"]       = str(inc2.get("eps","N/A"))
                est2 = (raw_fmp.get("estimates") or [{}])
                est2 = est2[0] if isinstance(est2,list) and est2 else {}
                if est2:
                    locked["fwdEPS"]     = str(est2.get("estimatedEpsAvg","N/A"))
                    locked["fwdRevenue"] = fm2(est2.get("estimatedRevenueAvg")) if est2.get("estimatedRevenueAvg") else "N/A"
                    locked["numAnalysts"]= str(est2.get("numberAnalystEstimatedRevenue","N/A"))

                # Next earnings
                today_str = _dt.now().strftime("%Y-%m-%d")
                earn_found = False
                fh_earn_data = raw_fmp.get('_fh_earnings',{})
                fh_earn_list = fh_earn_data.get('earningsCalendar',[]) if isinstance(fh_earn_data,dict) else []
                if fh_earn_list:
                    fh_future = sorted([e for e in fh_earn_list if e.get('date','') >= today_str], key=lambda x: x.get('date',''))
                    if fh_future:
                        ne = fh_future[0]
                        locked["nextEarningsDate"]   = ne.get("date","N/A")
                        locked["nextEarningsEPS"]    = ne.get("epsEstimated","N/A")
                        locked["nextEarningsTiming"] = ne.get("hour","N/A")
                        earn_found = True
                if not earn_found:
                    earn_up   = raw_fmp.get("earnings_upcoming") or []
                    earn_hist = raw_fmp.get("earnings_next") or []
                    earn_combined = []
                    for src2 in [earn_up, earn_hist]:
                        if isinstance(src2,list): earn_combined.extend(src2)
                        elif isinstance(src2,dict) and src2.get("earningsCalendar"): earn_combined.extend(src2["earningsCalendar"])
                    future_earns = sorted([e for e in earn_combined if e.get("date","") >= today_str], key=lambda x: x.get("date",""))
                    if future_earns:
                        ne = future_earns[0]
                        locked["nextEarningsDate"]   = ne.get("date","N/A")
                        locked["nextEarningsEPS"]    = ne.get("epsEstimated","N/A")
                        locked["nextEarningsTiming"] = ne.get("time","N/A")

                # Python-calculated IV (sector-aware, correct model selection)
                iv_val, iv_meth, iv_desc = calc_intrinsic_value(raw_fmp)
                if iv_val:
                    locked['calcIV']       = iv_val
                    locked['calcIVMethod'] = iv_meth
                    locked['calcIVDesc']   = iv_desc

                # Finnhub news sentiment
                fh_sent_data = local_sentiment.get(tk, {})
                if fh_sent_data:
                    buzz = fh_sent_data.get('buzz',{})
                    sent = fh_sent_data.get('sentiment',{})
                    locked['buzzScore']          = buzz.get('buzz','N/A')
                    locked['buzzArticlesWeekly'] = buzz.get('weeklyAverage','N/A')
                    locked['sentimentBullish']   = sent.get('bullishPercent','N/A')
                    locked['sentimentBearish']   = sent.get('bearishPercent','N/A')
                    locked['companyNewsScore']   = fh_sent_data.get('companyNewsScore','N/A')
                    locked['sectorAvgBullish']   = fh_sent_data.get('sectorAverageBullishPercent','N/A')

                locked_data[tk] = locked
                locked_lines.append(f"\n--- LOCKED LIVE DATA FOR {tk} (use these exact values) ---")
                for k2, v2 in locked.items():
                    locked_lines.append(f"  {k2}: {v2}")
                if locked.get("buzzScore") not in (None,"N/A"):
                    locked_lines.append(f"  [Sentiment] buzzScore={locked.get('buzzScore')} bullish%={locked.get('sentimentBullish')} bearish%={locked.get('sentimentBearish')}")
                # Inject news headlines into prompt so Claude can factor them in
                news_for_tk = raw_fmp.get('_fh_news', [])
                if news_for_tk:
                    locked_lines.append(f"  [Recent News Headlines — last 30 days]")
                    for ni, art in enumerate(news_for_tk[:6]):
                        ts = art.get("datetime", 0)
                        try:
                            date_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
                        except Exception:
                            date_str = "?"
                        locked_lines.append(f"    {ni+1}. [{date_str}] {art.get('headline','')} (source: {art.get('source','')})")
                        if art.get("summary"):
                            locked_lines.append(f"       Summary: {art.get('summary','')[:200]}")
                # Inject upcoming earnings date
                if locked.get("nextEarningsDate"):
                    locked_lines.append(f"  [Upcoming Earnings] Date: {locked['nextEarningsDate']} | Est EPS: {locked.get('nextEarningsEPS','N/A')} | Timing: {locked.get('nextEarningsTiming','N/A')}")
                locked_lines.append(f"--- END LOCKED DATA FOR {tk} ---")

            live_data_block = (
                "\n\n=== FINANCIAL MODELING PREP LIVE DATA ==="
                "\nTHESE ARE MANDATORY VALUES. Use them exactly as provided."
                "\nDo NOT substitute your own estimates. Do NOT use training data prices."
                "\n" + "\n".join(locked_lines) +
                "\n\n" + "\n\n".join(fmp_contexts.values()) +
                "\n=== END FMP DATA ==="
            )
            st.session_state['fmp_locked'] = locked_data

        # ── Build cost basis info for each holding ────────────────────────────
        holding_map = {clean_ticker(h['ticker']): h for h in port_holds}

        # ── Claude prompt ─────────────────────────────────────────────────────
        prompt = f"""You are a senior portfolio analyst. Analyze this portfolio of {len(port_holds)} holdings worth ~${port_val:,.0f}: {port_note}

Live financial data will be appended below.
IMPORTANT: Use the EXACT Current Price from the live data for currentPrice in your JSON. Do NOT use training data prices — they are outdated.

Return ONLY valid JSON (no markdown, no explanation):
{{
  "portfolioSynergy": {{
    "overallAssessment": "2-3 sentence holistic assessment of portfolio quality, construction, and fit",
    "healthScore": 7.5,
    "diversificationScore": 6.5,
    "overallRisk": "Low/Medium/High",
    "correlationNote": "2 sentences on how holdings cluster and correlate — identify any concentration risk",
    "sectorAllocation": [
      {{"sector": "Technology", "weight": "45%", "tickers": ["AAPL","MSFT"], "assessment": "Overweight — consider trimming"}}
    ],
    "concentrationRisks": ["Top 3 holdings = 70% of portfolio", "Heavy tech weighting"],
    "recommendations": [
      {{"action": "Trim", "ticker": "AAPL", "rationale": "2 sentences specific to this portfolio", "priority": "High"}},
      {{"action": "Add", "ticker": "BRK.B", "rationale": "2 sentences on why this fills a gap", "priority": "Medium"}},
      {{"action": "Keep", "ticker": "NVDA", "rationale": "2 sentences", "priority": "Low"}}
    ],
    "suggestedAdds": [
      {{"ticker": "VYM", "name": "Vanguard High Dividend Yield ETF", "rationale": "Adds income and defensive balance to this specific portfolio", "allocationPct": "5-8%"}}
    ],
    "suggestedRemoves": [
      {{"ticker": "XYZ", "reason": "Duplicates exposure to TICKER with lower quality fundamentals"}}
    ]
  }},
  "stocks": {{
    "TICKER": {{
      "ticker": "RESOLVED_SYMBOL",
      "companyName": "Full Company Name",
      "currentPrice": "$X.XX",
      "summary": "one sentence company description",
      "verdictStock": "BULLISH",
      "verdictStockReason": "one sentence on standalone merits",
      "verdictPortfolio": "BULLISH",
      "verdictPortfolioReason": "one sentence specific to this portfolio context",
      "portfolioInsights": {{
        "concentrationRisk": "sentence on % of this portfolio and if overweight",
        "sectorOverlap": "sentence on sector overlap with other holdings",
        "correlationNote": "sentence on how it moves vs other holdings in this portfolio",
        "diversificationImpact": "sentence on what it adds or subtracts from diversification",
        "recommendation": "Buy more / Hold / Trim — one sentence rationale"
      }},
      "pricing": {{
        "intrinsicValue": "$X (if FMP DCF provided it will override this)",
        "intrinsicMethod": "method name",
        "entryPrice": "$X — suggested entry price",
        "entryRationale": "Based on: (1) intrinsic value with 15% margin of safety, (2) key technical support from 1-yr chart — 50-day MA, 200-day MA, major support zones. Cite which level anchors this price.",
        "analystConsensus": "$X",
        "targetRange": "$X-$X"
      }},
      "ivBreakdown": [
        {{"method": "DCF", "value": "$X", "desc": "WACC X%, g X%, FCF $XB"}},
        {{"method": "EV/EBITDA", "value": "$X", "desc": "Xx multiple on $XB EBITDA"}},
        {{"method": "Fwd P/E", "value": "$X", "desc": "Xx on $X fwd EPS"}},
        {{"method": "P/FCF", "value": "$X", "desc": "Xx on $XB FCF"}}
      ],
      "topAnalysts": [
        {{"name": "...", "firm": "...", "accuracyPct": "XX%", "rating": "Buy", "target": "$X", "thesis": "max 8 words"}},
        {{"name": "...", "firm": "...", "accuracyPct": "XX%", "rating": "Outperform", "target": "$X", "thesis": "max 8 words"}},
        {{"name": "...", "firm": "...", "accuracyPct": "XX%", "rating": "Hold", "target": "$X", "thesis": "max 8 words"}},
        {{"name": "...", "firm": "...", "accuracyPct": "XX%", "rating": "Buy", "target": "$X", "thesis": "max 8 words"}},
        {{"name": "...", "firm": "...", "accuracyPct": "XX%", "rating": "Outperform", "target": "$X", "thesis": "max 8 words"}}
      ],
      "fundamentals": {{
        "revenue": {{"v": "$XB", "sig": "good"}},
        "grossMargin": {{"v": "X%", "sig": "good"}},
        "operatingMargin": {{"v": "X%", "sig": "ok"}},
        "netMargin": {{"v": "X%", "sig": "ok"}},
        "eps": {{"v": "$X", "sig": "good"}},
        "forwardEPS": {{"v": "$X", "sig": "good"}},
        "peRatio": {{"v": "Xx", "sig": "ok"}},
        "forwardPE": {{"v": "Xx", "sig": "ok"}},
        "evEbitda": {{"v": "Xx", "sig": "ok"}},
        "debtToEquity": {{"v": "X.X", "sig": "ok"}},
        "freeCashFlow": {{"v": "$XB", "sig": "good"}},
        "roe": {{"v": "X%", "sig": "good"}},
        "divYield": {{"v": "X%", "sig": "ok"}}
      }},
      "sectorAnalysis": {{
        "sector": "Sector name",
        "sectorOutlook": "1 sentence on sector tailwinds/headwinds",
        "peerComparison": [
          {{"peer": "Ticker", "metric": "P/E", "peerVal": "Xx", "stockVal": "Xx", "verdict": "Premium/Discount/Inline"}},
          {{"peer": "Ticker", "metric": "Rev Growth", "peerVal": "X%", "stockVal": "X%", "verdict": "Above/Below/Inline"}},
          {{"peer": "Ticker", "metric": "Net Margin", "peerVal": "X%", "stockVal": "X%", "verdict": "Above/Below/Inline"}}
        ],
        "sectorRank": "Top quartile/Mid-tier/Laggard",
        "sectorCatalysts": "1 sentence",
        "sectorRisks": "1 sentence"
      }},
      "riskAnalysis": {{
        "overallRiskRating": "Low/Medium/High/Very High",
        "riskScore": 55,
        "businessRisk": "1 sentence",
        "financialRisk": "1 sentence",
        "macroRisk": "1 sentence",
        "regulatoryRisk": "1 sentence",
        "valuationRisk": "1 sentence",
        "keyRisks": [
          {{"risk": "specific risk", "severity": "High/Medium/Low", "likelihood": "High/Medium/Low", "mitigation": "1 sentence"}},
          {{"risk": "specific risk", "severity": "High/Medium/Low", "likelihood": "High/Medium/Low", "mitigation": "1 sentence"}},
          {{"risk": "specific risk", "severity": "High/Medium/Low", "likelihood": "High/Medium/Low", "mitigation": "1 sentence"}}
        ],
        "bearCasePrice": "$X",
        "bullCasePrice": "$X"
      }},
      "sections": {{
        "valuation": "2 informative sentences on valuation vs history and peers — not 10 placeholder words",
        "momentum": "2 informative sentences on price momentum and technicals",
        "sentiment": "2 informative sentences on news sentiment and analyst positioning"
      }},
      "earningsOutlook": {{
        "nextEarningsDate": "YYYY-MM-DD or 'Unknown'",
        "daysUntilEarnings": "X days / this week / next week / next month / Unknown",
        "estimatedEPS": "$X or N/A",
        "earningsTiming": "BMO (before market open) / AMC (after market close) / Unknown",
        "earningsImportance": "High/Medium/Low",
        "whatToWatch": "2 sentences on key metrics and themes the market will focus on",
        "priceImpactRisk": "High/Medium/Low — sentence on how much the stock typically moves on earnings"
      }},
      "newsAndEvents": {{
        "overallSentiment": "Positive/Neutral/Negative",
        "sentimentScore": 65,
        "keyThemes": ["theme 1", "theme 2", "theme 3"],
        "topStory": "1 sentence summarizing the most important recent news",
        "catalysts": "1 sentence on upcoming positive catalysts from news",
        "risks": "1 sentence on risks or negative headlines",
        "newsImpact": "Bullish/Neutral/Bearish — 1 sentence on how recent news affects near-term price",
        "upcomingEvents": [
          {{"event": "Product launch / Conference / FDA decision / Investor day", "date": "YYYY-MM-DD or approximate", "impact": "High/Medium/Low", "note": "1 sentence"}}
        ]
      }}
    }}
  }},
  "portfolioEvents": {{
    "earningsCalendar": [
      {{"ticker": "AAPL", "date": "YYYY-MM-DD", "daysUntil": "X days", "estimatedEPS": "$X", "timing": "AMC", "importance": "High", "whatToWatch": "1 sentence"}}
    ],
    "upcomingCatalysts": [
      {{"ticker": "TICKER", "event": "description", "date": "approximate date", "impact": "High/Medium/Low", "portfolioImpact": "1 sentence on how this affects the whole portfolio"}}
    ],
    "riskEvents": [
      {{"event": "Fed rate decision / macro risk / regulatory hearing", "date": "approximate", "affectedTickers": ["AAPL","MSFT"], "risk": "1 sentence"}}
    ]
  }}
}}

CRITICAL — stocks{{}} MUST contain ALL {len(valid_tickers)} tickers: [{', '.join(valid_tickers)}].
Include 5 analysts per stock. Sections text: 2 real sentences each.
newsAndEvents and earningsOutlook are REQUIRED for every ticker — use the news headlines and earnings dates in the LOCKED DATA above.
portfolioEvents.earningsCalendar must list all tickers that have an upcoming earnings date in the locked data.
If no earnings date is known, set daysUntilEarnings to "Unknown" and omit from earningsCalendar.

NEWS ANALYSIS GUIDANCE:
- Use the actual headlines provided in LOCKED DATA [Recent News Headlines] for each ticker
- Identify themes: product launches, earnings beats/misses, partnerships, regulatory actions, macro headwinds, management changes, analyst upgrades/downgrades
- If headlines are bullish (new contracts, earnings beats, product wins) → newsImpact = Bullish
- If headlines are mixed or routine → newsImpact = Neutral
- If headlines show regulatory issues, earnings misses, major negative news → newsImpact = Bearish
- sentimentScore: 0-100 (0=extremely bearish, 50=neutral, 100=extremely bullish)
- Use Finnhub sentiment data (buzzScore, bullish%, bearish%) from locked data when available

SECTOR-AWARE VALUATION — FIRST check if the company is profitable:

PRE-PROFIT / HIGH-GROWTH (negative earnings, negative FCF, negative EBITDA — e.g. RKLB, IONQ, JOBY, LUNR, ASTR, early-stage biotech/space/EV):
- DO NOT use standard DCF, EV/EBITDA, or P/E — they produce misleading low values
- USE INSTEAD:
  1. EV/Revenue: compare to high-growth peers (space: 10-25x; SaaS: 8-20x; EV: 3-8x)
  2. Forward DCF on projected profitability: analyst consensus FCF estimates 2026-2028, discount at WACC 12-15%
  3. P/S vs sector peers at similar growth rates
  4. Scenario-weighted: bull × 40% + base × 40% + bear × 20%
- NOTE in ivBreakdown: "Pre-profit company — traditional DCF/P/E not applicable. Using EV/Revenue and forward estimates."
- Analyst consensus targets for these often lag market — note explicitly

PROFITABLE companies:
Utilities (VST,NEE,DUK): WACC 7-9%, DCF terminal growth 1.5-2.5%, normalized FCF (3yr avg), EV/EBITDA 8-12x
Tech/Growth profitable (NVDA,MSFT,AAPL): WACC 9-12%, EV/EBITDA 20-40x, P/E 20-35x
Financials: P/B 1-2x and P/E, skip EV/EBITDA
Industrials/Energy: WACC 8-10%, EV/EBITDA 6-10x, cycle-normalized earnings
Show actual inputs in desc field e.g. "WACC 8.2%, g 2%, normalized FCF $1.8B"

ENTRY PRICE METHODOLOGY:
1. VALUATION FLOOR: intrinsic value × 0.85 (15% margin of safety)
2. TECHNICAL SUPPORT: strongest level from 1-yr chart — 50-day MA, 200-day MA, prior consolidation, swing lows
3. FINAL ENTRY: higher of (valuation floor) and (nearest technical support below current price)
Always explain which factor drove it in entryRationale."""

        enriched_prompt = prompt + live_data_block

        if st.session_state.get('stop_requested'):
            st.warning("Analysis stopped.")
            st.session_state['running'] = False
            st.stop()

        st.write("Running AI analysis and valuations...")
        progress_bar  = st.progress(0, text="Claude is thinking...")
        token_counter = [0]
        txt_chunks    = []

        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model="claude-sonnet-4-5",
            max_tokens=16000,
            messages=[{"role": "user", "content": enriched_prompt}]
        ) as stream:
            for text_chunk in stream.text_stream:
                if st.session_state.get('stop_requested'):
                    st.warning("Analysis stopped by user.")
                    st.session_state['running'] = False
                    st.stop()
                txt_chunks.append(text_chunk)
                token_counter[0] += 1
                if token_counter[0] % 50 == 0:
                    pct = min(0.95, token_counter[0] / 900)
                    progress_bar.progress(pct, text=f"Generating analysis... ({token_counter[0] * 4 // 1000}K tokens)")

        progress_bar.progress(1.0, text="Finalizing...")
        st.write("Building report...")
        txt    = "".join(txt_chunks)
        parsed = parse_json(txt)

        if not parsed:
            st.error(f"Could not parse response. Raw preview: {txt[:400]}")
            st.session_state['raw_response'] = txt
        else:
            # ── Hard override: inject ALL locked FMP values into parsed JSON ──
            # This is the critical pattern — Claude (LLM) cannot reliably reproduce
            # numbers from prompts. All financial data is extracted from FMP directly
            # and injected post-parse, overwriting whatever Claude produced.
            locked = st.session_state.get('fmp_locked', {})
            if locked and parsed.get("stocks"):
                for tk_key, lk in locked.items():
                    for sk in list(parsed["stocks"].keys()):
                        if sk.upper() == tk_key.upper():
                            s_data = parsed["stocks"][sk]
                            if lk.get("currentPrice"):
                                s_data["currentPrice"] = lk["currentPrice"]
                            if "pricing" not in s_data or not s_data["pricing"]:
                                s_data["pricing"] = {}
                            if lk.get("analystConsensus"):
                                s_data["pricing"]["analystConsensus"] = lk["analystConsensus"]
                            if lk.get("analystTargetHigh") and lk.get("analystTargetLow"):
                                s_data["pricing"]["targetRange"] = f"${lk['analystTargetLow']} – ${lk['analystTargetHigh']}"
                            # Python-calculated IV overrides Claude's IV estimate
                            if lk.get('calcIV'):
                                s_data['pricing']['intrinsicValue']  = lk['calcIV']
                                s_data['pricing']['intrinsicMethod'] = lk.get('calcIVMethod','Live calculation')
                                primary_iv = {'method': lk.get('calcIVMethod','Live IV'),
                                              'value':  lk['calcIV'],
                                              'desc':   lk.get('calcIVDesc','Calculated from live FMP data')}
                                if not isinstance(s_data.get('ivBreakdown'), list):
                                    s_data['ivBreakdown'] = []
                                if s_data['ivBreakdown']:
                                    s_data['ivBreakdown'][0] = primary_iv
                                else:
                                    s_data['ivBreakdown'].insert(0, primary_iv)
                            elif lk.get('fmpDCF'):
                                s_data['pricing']['intrinsicValue']  = lk['fmpDCF']
                                s_data['pricing']['intrinsicMethod'] = 'FMP DCF Model (live)'
                            if "fundamentals" not in s_data or not s_data["fundamentals"]:
                                s_data["fundamentals"] = {}
                            f2 = s_data["fundamentals"]
                            def _set(key, val):
                                if val and val != "N/A":
                                    if key not in f2: f2[key] = {}
                                    f2[key]["v"] = val
                                    f2[key].setdefault("sig","ok")
                            _set("revenue",      lk.get("revenue"))
                            _set("netMargin",    lk.get("netMargin"))
                            _set("grossMargin",  lk.get("grossMargin"))
                            _set("eps",          f"${lk['eps']}" if lk.get("eps") and lk["eps"] != "N/A" else None)
                            _set("forwardEPS",   f"${lk['fwdEPS']}" if lk.get("fwdEPS") and lk["fwdEPS"] != "N/A" else None)
                            _set("peRatio",      f"{lk['peRatio']}×" if lk.get("peRatio") and lk["peRatio"] != "N/A" else None)
                            _set("evEbitda",     f"{lk['evEbitda']}×" if lk.get("evEbitda") and lk["evEbitda"] != "N/A" else None)
                            _set("roe",          lk.get("roe"))
                            _set("debtToEquity", lk.get("debtEq"))
            elif st.session_state.get('fmp_raw_data') and parsed.get("stocks"):
                # Fallback: at minimum override currentPrice from raw data
                for tk_key, raw_fmp in st.session_state['fmp_raw_data'].items():
                    q2 = (raw_fmp.get("quote") or [{}])
                    q2 = q2[0] if isinstance(q2,list) and q2 else q2 if isinstance(q2,dict) else {}
                    live_price = q2.get("price")
                    if live_price:
                        price_str = f"${live_price:,.2f}" if isinstance(live_price,(int,float)) else f"${live_price}"
                        for sk in list(parsed["stocks"].keys()):
                            if sk.upper() == tk_key.upper():
                                parsed["stocks"][sk]["currentPrice"] = price_str

            st.session_state['result'] = parsed
            st.session_state['raw_response'] = None
            if finnhub_prices and fmp_contexts:
                st.session_state['data_source'] = "Finnhub + FMP + Claude"
            elif fmp_contexts:
                st.session_state['data_source'] = "FMP + Claude"
            else:
                st.session_state['data_source'] = "Claude only"
            st.session_state['fmp_tickers'] = list(fmp_contexts.keys())
            status.update(label="Analysis complete!", state="complete")

        st.session_state['running'] = False
        if fmp_contexts or local_raw_data:
            st.session_state['data_source']  = "Finnhub + FMP + Claude" if finnhub_prices else "FMP + Claude"
            st.session_state['fmp_tickers']  = list(fmp_contexts.keys()) if fmp_contexts else list(local_raw_data.keys())
        elif not st.session_state.get('data_source'):
            st.session_state['data_source'] = "Claude only"


# ── Results ───────────────────────────────────────────────────────────────────
if st.session_state['result']:
    data    = st.session_state['result']
    stocks  = data.get('stocks', {})
    synergy = data.get('portfolioSynergy', {})

    # ── Data source badge ──
    data_source = st.session_state.get('data_source')
    fmp_tickers = st.session_state.get('fmp_tickers', [])
    if data_source:
        tickers_str = ', '.join(fmp_tickers) if fmp_tickers else 'N/A'
        if "FMP" in (data_source or "") or "Finnhub" in (data_source or ""):
            badge_bg = "#061508"; badge_border = "#16a34a55"
            badge_icon = "📡"; badge_color = "#4ade80"; badge_label = data_source
            badge_desc = f"Live market data ({tickers_str}) + AI reasoning by Claude"
        else:
            badge_bg = "#0f1208"; badge_border = "#ca8a0455"
            badge_icon = "🧠"; badge_color = "#fbbf24"; badge_label = "Training Data"
            badge_desc = "FMP not connected — analysis based on Claude training knowledge. Add FMP_API_KEY + FINNHUB_API_KEY to Secrets for live data."
        st.markdown(f"""
        <div style="background:{badge_bg};border:1px solid {badge_border};padding:10px 14px;
                    margin-bottom:14px;display:flex;align-items:center;gap:12px">
          <div style="font-size:20px">{badge_icon}</div>
          <div>
            <div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;
                        letter-spacing:2px;text-transform:uppercase;color:{badge_color}">
              Data Source: {esc(badge_label)}
            </div>
            <div style="font-size:15px;color:#94a3b8;margin-top:2px">{esc(badge_desc)}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Portfolio value header ────────────────────────────────────────────────
    port_holds_disp = [h for h in st.session_state['holdings']
                       if h.get('ticker') and h.get('shares') and h.get('cost')]
    port_val_disp = 0.0
    for h in port_holds_disp:
        try: port_val_disp += float(h['shares']) * float(h['cost'])
        except: pass

    if port_val_disp > 0:
        st.markdown(f"""
        <div class="card card-blue" style="margin-bottom:14px">
          <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center">
            <div>
              <div class="label">Total Cost Basis</div>
              <div style="font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:#f0f6ff">${port_val_disp:,.0f}</div>
            </div>
            <div>
              <div class="label">Holdings Analyzed</div>
              <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:#93c5fd">{len(port_holds_disp)}</div>
            </div>
            {(f'<div><div class="label">Portfolio Health</div><div style="font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#4ade80">{esc(str(synergy.get("healthScore","—")))}/10</div></div>') if synergy.get("healthScore") else ""}
            {(f'<div><div class="label">Diversification</div><div style="font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:#a78bfa">{esc(str(synergy.get("diversificationScore","—")))}/10</div></div>') if synergy.get("diversificationScore") else ""}
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — PORTFOLIO SYNERGY ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    if synergy:
        st.markdown("## ◈ PORTFOLIO ANALYSIS")

        # Overall assessment
        if synergy.get("overallAssessment"):
            st.markdown('<div class="sec-hdr">◈ Overall Portfolio Assessment</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="sec-body">{esc(synergy["overallAssessment"])}</div>', unsafe_allow_html=True)

        # Health/diversification/risk scores
        score_cols = st.columns(3)
        score_items = [
            ("Portfolio Health", synergy.get("healthScore","—"), "/10", "#4ade80"),
            ("Diversification",  synergy.get("diversificationScore","—"), "/10", "#a78bfa"),
            ("Overall Risk",     synergy.get("overallRisk","—"), "", "#fbbf24"),
        ]
        for col, (lbl, val, suffix, color) in zip(score_cols, score_items):
            with col:
                st.markdown(f"""
                <div class="card" style="text-align:center;padding:14px">
                  <div class="label">{esc(lbl)}</div>
                  <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:{color}">
                    {esc(str(val))}<span style="font-size:15px;color:#5a7a99">{suffix}</span>
                  </div>
                </div>""", unsafe_allow_html=True)

        # Sector allocation
        alloc = synergy.get("sectorAllocation", [])
        if alloc:
            st.markdown('<div class="sec-hdr">◈ Sector Allocation</div>', unsafe_allow_html=True)
            alloc_html = ''
            for a in alloc:
                wt  = esc(a.get("weight","—"))
                tks = ", ".join(esc(t) for t in (a.get("tickers") or []))
                ass = esc(a.get("assessment",""))
                sec = esc(a.get("sector","—"))
                try:
                    wt_num  = float(re.sub(r'[^0-9.]','',str(a.get("weight","0"))))
                    bar_col = "#f87171" if wt_num > 40 else "#fbbf24" if wt_num > 25 else "#4ade80"
                    bar_w   = min(int(wt_num * 1.5), 100)
                except: bar_col = "#fbbf24"; bar_w = 0
                alloc_html += (
                    f'<div class="mob-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:6px">'
                    f'<span style="font-weight:700;color:#f0f6ff;font-size:15px">{sec}</span>'
                    f'<div style="display:flex;align-items:center;gap:8px">'
                    f'<div style="height:4px;width:{bar_w}px;background:{bar_col};border-radius:2px"></div>'
                    f'<span style="color:{bar_col};font-weight:700;font-size:15px">{wt}</span>'
                    f'</div></div>'
                    f'<div style="font-size:15px;color:#94a3b8;margin-bottom:4px">{tks}</div>'
                    f'<div style="font-size:15px;color:#e2e8f0;line-height:1.5">{ass}</div>'
                    f'</div>'
                )
            st.markdown(alloc_html, unsafe_allow_html=True)

        # Concentration risks
        conc_risks = synergy.get("concentrationRisks", [])
        if conc_risks:
            st.markdown('<div class="sec-hdr">◈ Concentration Risks</div>', unsafe_allow_html=True)
            risks_html = ''.join(f'<div style="padding:5px 0;border-bottom:1px solid #111c2a;font-size:15px;color:#f87171">⚠ {esc(r)}</div>' for r in conc_risks)
            st.markdown(f'<div class="sec-body">{risks_html}</div>', unsafe_allow_html=True)

        # Correlation note
        if synergy.get("correlationNote"):
            st.markdown('<div class="sec-hdr">◈ Correlation & Diversification</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="sec-body">{esc(synergy["correlationNote"])}</div>', unsafe_allow_html=True)

        # What to change
        recs = synergy.get("recommendations", [])
        if recs:
            st.markdown("## ▸ WHAT TO CHANGE")
            for rec in recs:
                action  = esc(rec.get("action",""))
                ticker  = esc(rec.get("ticker",""))
                rat     = esc(rec.get("rationale",""))
                prio    = esc(rec.get("priority",""))
                act_lwr = (rec.get("action") or "").lower()
                is_pos  = any(x in act_lwr for x in ["add","increase","keep","buy"])
                is_neg  = any(x in act_lwr for x in ["trim","reduce","remove","sell"])
                if is_pos:
                    card_cls = "card-green"; lbl_col = "#4ade80"
                elif is_neg:
                    card_cls = "card-red";   lbl_col = "#f87171"
                else:
                    card_cls = "";           lbl_col = "#fbbf24"
                prio_color = "#f87171" if prio=="High" else "#fbbf24" if prio=="Medium" else "#4ade80"
                st.markdown(f"""
                <div class="card {card_cls}" style="margin-bottom:8px">
                  <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;flex-wrap:wrap">
                    <span style="font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:{lbl_col};text-transform:uppercase">{action}</span>
                    <span style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:#f0f6ff">{ticker}</span>
                    {f'<span style="font-size:15px;padding:2px 6px;border:1px solid {prio_color}44;color:{prio_color};text-transform:uppercase;letter-spacing:1px">{prio} PRIORITY</span>' if prio else ""}
                  </div>
                  <div style="font-size:15px;color:#e2e8f0;line-height:1.6">{rat}</div>
                </div>
                """, unsafe_allow_html=True)

        # Suggested additions
        adds = synergy.get("suggestedAdds", [])
        if adds:
            st.markdown("## ➕ SUGGESTED ADDITIONS")
            add_cols = st.columns(min(len(adds), 3))
            for i, a in enumerate(adds):
                with add_cols[i % len(add_cols)]:
                    tk   = esc(a.get("ticker",""))
                    name = esc(a.get("name",""))
                    rat  = esc(a.get("rationale",""))
                    alloc_pct = esc(a.get("allocationPct",""))
                    st.markdown(f"""
                    <div class="card card-green" style="padding:14px;margin-bottom:0">
                      <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#f0f6ff">{tk}</div>
                      <div style="font-size:15px;color:#94a3b8;margin-bottom:8px">{name}</div>
                      <div style="font-size:15px;color:#e2e8f0;line-height:1.7;margin-bottom:6px">{rat}</div>
                      {f'<div style="font-size:15px;color:#4ade80;letter-spacing:1px">Suggested allocation: {alloc_pct}</div>' if alloc_pct else ""}
                    </div>
                    """, unsafe_allow_html=True)

        # Suggested removes
        removes = synergy.get("suggestedRemoves", [])
        if removes:
            st.markdown("## ➖ CONSIDER REMOVING / REDUCING")
            for r2 in removes:
                tk  = esc(r2.get("ticker",""))
                rsn = esc(r2.get("reason",""))
                st.markdown(f"""
                <div class="card card-red" style="margin-bottom:8px">
                  <div style="display:flex;gap:12px;align-items:flex-start">
                    <div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#f87171">{tk}</div>
                    <div style="font-size:15px;color:#e2e8f0;line-height:1.6;padding-top:2px">{rsn}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — PORTFOLIO NEWS & EVENTS CALENDAR
    # ══════════════════════════════════════════════════════════════════════════
    port_events = data.get('portfolioEvents', {})
    has_news = (port_events.get('earningsCalendar') or port_events.get('upcomingCatalysts') or
                port_events.get('riskEvents') or st.session_state.get('finnhub_news'))

    if has_news:
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        st.markdown("## 📅 NEWS & EVENTS CALENDAR")

        # ── Earnings calendar ──
        earn_cal = port_events.get('earningsCalendar', [])
        if earn_cal:
            earn_cal_sorted = sorted(earn_cal, key=lambda x: x.get('date','9999'))
            st.markdown('<div class="sec-hdr">◈ Upcoming Earnings — All Portfolio Holdings</div>', unsafe_allow_html=True)
            earn_html = ''
            for ec in earn_cal_sorted:
                imp   = ec.get("importance","Medium")
                imp_c = "#f87171" if imp=="High" else "#fbbf24" if imp=="Medium" else "#4ade80"
                earn_html += (
                    f'<div class="mob-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:8px">'
                    f'<span class="mob-card-ticker">{esc(ec.get("ticker",""))}</span>'
                    f'<span style="color:{imp_c};font-size:15px;font-weight:700">● {esc(imp)}</span>'
                    f'</div>'
                    f'<div class="mob-card-row">'
                    f'<span class="mob-card-label">Date</span><span class="mob-card-val" style="color:#93c5fd">{esc(ec.get("date",""))}</span>'
                    f'</div>'
                    f'<div class="mob-card-row">'
                    f'<span class="mob-card-label">In</span><span class="mob-card-val">{esc(ec.get("daysUntil",""))}</span>'
                    f'</div>'
                    f'<div class="mob-card-row">'
                    f'<span class="mob-card-label">Est. EPS</span><span class="mob-card-val" style="color:#a78bfa">{esc(ec.get("estimatedEPS",""))}</span>'
                    f'</div>'
                    f'<div class="mob-card-row">'
                    f'<span class="mob-card-label">Timing</span><span class="mob-card-val">{esc(ec.get("timing",""))}</span>'
                    f'</div>'
                    + (f'<div class="mob-card-full">{esc(ec.get("whatToWatch",""))}</div>' if ec.get("whatToWatch") else '')
                    + f'</div>'
                )
            st.markdown(earn_html, unsafe_allow_html=True)

        # ── Upcoming catalysts ──
        cats = port_events.get('upcomingCatalysts', [])
        if cats:
            st.markdown('<div class="sec-hdr">◈ Upcoming Catalysts</div>', unsafe_allow_html=True)
            for cat in cats:
                imp   = cat.get("impact","Medium")
                imp_c = "#f87171" if imp=="High" else "#fbbf24" if imp=="Medium" else "#4ade80"
                st.markdown(f"""
                <div class="card card-green" style="margin-bottom:6px;padding:11px">
                  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px">
                    <span style="font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:#f0f6ff">{esc(cat.get("ticker",""))}</span>
                    <span style="font-size:15px;color:#94a3b8">{esc(cat.get("date",""))}</span>
                    <span style="font-size:15px;padding:2px 6px;border:1px solid {imp_c}44;color:{imp_c};text-transform:uppercase;letter-spacing:1px">{esc(imp)} IMPACT</span>
                  </div>
                  <div style="font-size:15px;color:#e2e8f0;margin-bottom:3px">{esc(cat.get("event",""))}</div>
                  <div style="font-size:15px;color:#94a3b8">{esc(cat.get("portfolioImpact",""))}</div>
                </div>
                """, unsafe_allow_html=True)

        # ── Risk events ──
        risk_evts = port_events.get('riskEvents', [])
        if risk_evts:
            st.markdown('<div class="sec-hdr">◈ Macro & Risk Events to Monitor</div>', unsafe_allow_html=True)
            for re2 in risk_evts:
                affected = ", ".join(esc(t) for t in (re2.get("affectedTickers") or []))
                st.markdown(f"""
                <div class="card card-red" style="margin-bottom:6px;padding:11px">
                  <div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap">
                    <div style="flex:1">
                      <div style="font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:#f87171;margin-bottom:3px">{esc(re2.get("event",""))}</div>
                      <div style="font-size:15px;color:#94a3b8;margin-bottom:2px">{esc(re2.get("date",""))}</div>
                      <div style="font-size:15px;color:#e2e8f0">{esc(re2.get("risk",""))}</div>
                    </div>
                    {f'<div style="font-size:15px;color:#fbbf24;white-space:nowrap">Affects: {affected}</div>' if affected else ""}
                  </div>
                </div>
                """, unsafe_allow_html=True)

        # ── Raw news headlines per ticker ──
        finnhub_news_all = st.session_state.get('finnhub_news', {})
        if finnhub_news_all:
            st.markdown('<div class="sec-hdr">◈ Latest News Headlines by Holding</div>', unsafe_allow_html=True)
            for tk_news, articles in finnhub_news_all.items():
                if not articles: continue
                st.markdown(f'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;letter-spacing:2px;color:#93c5fd;text-transform:uppercase;margin:10px 0 6px">{esc(tk_news)}</div>', unsafe_allow_html=True)
                for art in articles[:5]:
                    ts = art.get("datetime", 0)
                    try:    date_str = _dt.fromtimestamp(ts).strftime("%b %d, %Y") if ts else ""
                    except: date_str = ""
                    headline = esc(art.get("headline",""))
                    source   = esc(art.get("source",""))
                    summary  = esc(art.get("summary",""))
                    url      = art.get("url","")
                    safe_url = url if re.match(r'^https?://', url) else ""
                    # Pre-compute all conditional HTML fragments
                    if safe_url:
                        hl_html = f'<a href="{html_lib.escape(safe_url)}" target="_blank" rel="noopener noreferrer" style="text-decoration:none"><div style="font-size:15px;color:#e2e8f0;font-weight:700;line-height:1.4;margin-bottom:3px">{headline}</div></a>'
                    else:
                        hl_html = f'<div style="font-size:15px;color:#e2e8f0;font-weight:700;line-height:1.4;margin-bottom:3px">{headline}</div>'
                    sum_html = f'<div style="font-size:15px;color:#94a3b8;line-height:1.5;margin-top:2px">{summary}</div>' if summary else ''
                    st.markdown(
                        f'<div style="background:#090f1a;border:1px solid #111c2a;border-left:3px solid #1a2e48;padding:10px 12px;margin-bottom:6px">'
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">'
                        f'<div style="flex:1">{hl_html}{sum_html}</div>'
                        f'<div style="text-align:right;min-width:80px;flex-shrink:0">'
                        f'<div style="font-size:15px;color:#5a7a99">{esc(date_str)}</div>'
                        f'<div style="font-size:15px;color:#3b82f6;margin-top:2px">{source}</div>'
                        f'</div></div></div>',
                        unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — PER-STOCK ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("## ◈ INDIVIDUAL STOCK ANALYSIS")

    # Build holding map for cost basis / P&L display
    holding_map = {}
    for h in st.session_state['holdings']:
        if h.get('ticker'): holding_map[clean_ticker(h['ticker'])] = h

    # Normalise stocks dict keys (Claude output)
    clean_stocks = {}
    for k, v in stocks.items():
        tk2 = clean_ticker(k)
        if tk2 and tk2 not in clean_stocks:
            clean_stocks[tk2] = {**v, 'ticker': tk2}
    stocks = clean_stocks

    # Always iterate over the USER'S holdings — never Claude's dict
    # This guarantees every holding appears even if Claude missed or miskeyed it
    for h in port_holds_disp:
        tk_key  = clean_ticker(h.get('ticker',''))
        if not tk_key: continue
        # Look up Claude's analysis — try exact match then case-insensitive
        s = stocks.get(tk_key)
        if s is None:
            for k2 in stocks:
                if k2.upper() == tk_key.upper():
                    s = stocks[k2]
                    break
        # If Claude didn't return data for this ticker, show a minimal placeholder
        if s is None:
            s = {
                'ticker':      tk_key,
                'companyName': tk_key,
                'currentPrice': '',
            }

        holding = holding_map.get(tk_key, h)
        cost_basis = None
        shares_held = None
        position_value_cost = None
        position_value_live = None
        gain_loss_pct = None

        if holding.get('shares') and holding.get('cost'):
            try:
                shares_held = float(holding['shares'])
                avg_cost    = float(holding['cost'])
                position_value_cost = shares_held * avg_cost
                pct_of_port = (position_value_cost / port_val_disp * 100) if port_val_disp > 0 else 0
                # Try to compute live P&L from current price
                cur_price_raw = s.get("currentPrice","")
                cur_price_num = float(re.sub(r'[^0-9.]','',str(cur_price_raw))) if cur_price_raw else 0
                if cur_price_num > 0:
                    position_value_live = shares_held * cur_price_num
                    gain_loss_pct = ((cur_price_num - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            except: pass

        with st.expander(f"▸ {esc(s.get('ticker',''))} — {esc(s.get('companyName',''))}  {esc(s.get('currentPrice',''))}"):

            # ── Position summary ──
            if shares_held and holding.get('cost'):
                pos_html = '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">'
                pos_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:120px"><div class="label">Shares Held</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:#f0f6ff">{shares_held:,.0f}</div></div>'
                pos_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:120px"><div class="label">Avg Cost</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:#f0f6ff">${float(holding["cost"]):,.2f}</div></div>'
                if position_value_cost:
                    pos_html += f'<div class="card card-blue" style="padding:10px 14px;flex:1;min-width:120px"><div class="label">Cost Basis</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:#93c5fd">${position_value_cost:,.0f}</div></div>'
                if gain_loss_pct is not None:
                    gl_col = "#4ade80" if gain_loss_pct >= 0 else "#f87171"
                    gl_icon= "▲" if gain_loss_pct >= 0 else "▼"
                    pos_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:120px;border-color:{gl_col}44"><div class="label">Unrealized P&L</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:{gl_col}">{gl_icon} {abs(gain_loss_pct):.1f}%</div></div>'
                if pct_of_port:
                    pos_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:120px"><div class="label">% of Portfolio</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:#fbbf24">{pct_of_port:.1f}%</div></div>'
                pos_html += '</div>'
                st.markdown(pos_html, unsafe_allow_html=True)

            # ── Pricing row ──
            pp = s.get('pricing', {})
            price_html = '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">'
            for lbl, val, color in [
                ("Current Price",    s.get("currentPrice",""),    "#f0f6ff"),
                ("Intrinsic Value",  pp.get("intrinsicValue",""), "#a78bfa"),
                ("Suggested Entry",  pp.get("entryPrice",""),     "#4ade80"),
                ("Analyst Target",   pp.get("analystConsensus",""),"#93c5fd"),
                ("Target Range",     pp.get("targetRange",""),    "#fbbf24"),
            ]:
                if val:
                    price_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:130px"><div class="label">{esc(lbl)}</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:{color}">{esc(val)}</div></div>'
            price_html += '</div>'
            st.markdown(price_html, unsafe_allow_html=True)

            # Intrinsic value method
            if pp.get("intrinsicMethod"):
                st.markdown(f'<div style="font-size:15px;color:#5a7a99;letter-spacing:1px;margin-bottom:10px">IV Method: {esc(pp["intrinsicMethod"])}</div>', unsafe_allow_html=True)

            # Verdicts
            if s.get("verdictStock"):
                render_verdict("Standalone Verdict", s["verdictStock"], s.get("verdictStockReason",""))
            if s.get("verdictPortfolio"):
                render_verdict("Portfolio Synergy", s["verdictPortfolio"], s.get("verdictPortfolioReason",""))

            # ── Portfolio Insights ──
            pi = s.get('portfolioInsights', {})
            if pi:
                st.markdown('<div class="sec-hdr">◈ Portfolio Insights</div>', unsafe_allow_html=True)
                for key, lbl in [
                    ("concentrationRisk","Concentration Risk"),
                    ("sectorOverlap","Sector Overlap"),
                    ("correlationNote","Correlation"),
                    ("diversificationImpact","Diversification Impact"),
                    ("recommendation","Recommendation"),
                ]:
                    if pi.get(key):
                        st.markdown(f'<div class="sec-body" style="margin-bottom:4px"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">{esc(lbl)}: </span>{esc(pi[key])}</div>', unsafe_allow_html=True)

            # ── IV Breakdown ──
            if s.get('ivBreakdown'):
                st.markdown('<div class="sec-hdr">◈ Intrinsic Value Breakdown</div>', unsafe_allow_html=True)
                iv_rows = ""
                for iv in s['ivBreakdown']:
                    iv_rows += f"""<tr>
                      <td style="color:#93c5fd;font-family:'Syne',sans-serif;font-size:15px">{esc(iv.get("method",""))}</td>
                      <td style="font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:#a78bfa">{esc(iv.get("value",""))}</td>
                      <td style="color:#94a3b8;font-size:15px">{esc(iv.get("desc",""))}</td>
                    </tr>"""
                st.markdown(f'<table class="data-table"><thead><tr><th>Method</th><th>Value</th><th>Inputs</th></tr></thead><tbody>{iv_rows}</tbody></table>', unsafe_allow_html=True)

            if pp.get("entryRationale"):
                st.markdown('<div class="sec-hdr">▸ Entry Price Rationale</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="sec-body">{esc(pp["entryRationale"])}</div>', unsafe_allow_html=True)

            # ── Fundamentals ──
            fund = s.get('fundamentals')
            if fund:
                st.markdown('<div class="sec-hdr">◈ Fundamentals</div>', unsafe_allow_html=True)
                fund_rows = ""
                for key, lbl in FUND_LABELS:
                    d = fund.get(key)
                    if d and d.get("v"):
                        sig_cls = "sig-good" if d.get("sig")=="good" else "sig-bad" if d.get("sig")=="bad" else "sig-ok"
                        fund_rows += f'<tr><td style="color:#94a3b8">{esc(lbl)}</td><td class="{sig_cls}" style="font-weight:700">{esc(d["v"])}</td></tr>'
                if fund_rows:
                    st.markdown(f'<table class="data-table"><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{fund_rows}</tbody></table>', unsafe_allow_html=True)

            # ── Sections ──
            sections = s.get('sections', {})
            if sections:
                st.markdown('<div class="sec-hdr">◈ Analysis</div>', unsafe_allow_html=True)
                for key, lbl in [("valuation","📊 Valuation"),("momentum","📈 Momentum"),("sentiment","💬 Sentiment")]:
                    if sections.get(key):
                        st.markdown(f'<div class="sec-body" style="margin-bottom:4px"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">{esc(lbl)}: </span>{esc(sections[key])}</div>', unsafe_allow_html=True)

            # ── Earnings Outlook ──
            eo = s.get('earningsOutlook', {})
            if eo and eo.get('nextEarningsDate') and eo.get('nextEarningsDate') != 'Unknown':
                st.markdown('<div class="sec-hdr">📅 Earnings Outlook</div>', unsafe_allow_html=True)
                ei_imp = eo.get("earningsImportance","Medium")
                ei_col = "#f87171" if ei_imp=="High" else "#fbbf24" if ei_imp=="Medium" else "#4ade80"
                pr_imp = eo.get("priceImpactRisk","Medium")
                pr_col = "#f87171" if pr_imp=="High" else "#fbbf24" if pr_imp=="Medium" else "#4ade80"
                earn_pills = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">'
                for lbl2, val2, col2 in [
                    ("Next Earnings", eo.get("nextEarningsDate",""), "#93c5fd"),
                    ("Est. EPS",      eo.get("estimatedEPS",""),     "#a78bfa"),
                    ("Timing",        eo.get("earningsTiming",""),   "#fbbf24"),
                    ("Days Until",    eo.get("daysUntilEarnings",""),"#f0f6ff"),
                ]:
                    if val2:
                        earn_pills += f'<div class="card" style="padding:8px 12px;flex:1;min-width:100px;margin-bottom:0"><div class="label">{esc(lbl2)}</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:{col2}">{esc(val2)}</div></div>'
                earn_pills += '</div>'
                st.markdown(earn_pills, unsafe_allow_html=True)
                imp_row  = f'<div style="display:flex;gap:8px;margin-bottom:8px">'
                imp_row += f'<div class="card" style="padding:8px 12px;flex:1;margin-bottom:0"><div class="label">Importance</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:{ei_col}">{esc(ei_imp)}</div></div>'
                imp_row += f'<div class="card" style="padding:8px 12px;flex:1;margin-bottom:0"><div class="label">Price Impact Risk</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:{pr_col}">{esc(pr_imp)}</div></div>'
                imp_row += '</div>'
                st.markdown(imp_row, unsafe_allow_html=True)
                if eo.get("whatToWatch"):
                    st.markdown(f'<div class="sec-body"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">What to Watch: </span>{esc(eo["whatToWatch"])}</div>', unsafe_allow_html=True)
                if eo.get("priceImpactRisk"):
                    st.markdown(f'<div class="sec-body" style="margin-top:4px"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">Price Move Risk: </span>{esc(eo.get("priceImpactRisk",""))} — {esc(str(eo.get("priceImpactRisk",""))+" risk on earnings print" if eo.get("priceImpactRisk") else "")}</div>', unsafe_allow_html=True)

            # ── News & Events ──
            ne = s.get('newsAndEvents', {})
            if ne:
                st.markdown('<div class="sec-hdr">📰 News & Events</div>', unsafe_allow_html=True)
                ni_sent   = ne.get("overallSentiment","Neutral")
                ni_impact = ne.get("newsImpact","Neutral")
                ni_score  = ne.get("sentimentScore", 50)
                try: ni_score = int(ni_score)
                except: ni_score = 50
                sent_col   = "#4ade80" if "bull" in ni_impact.lower() or "pos" in ni_sent.lower() else "#f87171" if "bear" in ni_impact.lower() or "neg" in ni_sent.lower() else "#fbbf24"
                # Sentiment bar header
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:16px;padding:10px 12px;background:#090f1a;border:1px solid #111c2a;margin-bottom:8px">
                  <div><div class="label">News Sentiment</div><div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:{sent_col}">{esc(ni_sent)}</div></div>
                  <div><div class="label">Sentiment Score</div><div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:{sent_col}">{ni_score}<span style="font-size:15px;color:#5a7a99">/100</span></div></div>
                  <div><div class="label">News Impact</div><div style="font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:{sent_col}">{esc(ni_impact)}</div></div>
                  <div style="flex:1">
                    <div class="label" style="margin-bottom:4px">Sentiment Meter</div>
                    <div style="height:5px;background:#1a2e48;border-radius:3px">
                      <div style="height:5px;width:{ni_score}%;background:{sent_col};border-radius:3px"></div>
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)
                if ne.get("topStory"):
                    st.markdown(f'<div class="sec-body" style="margin-bottom:4px"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">Top Story: </span>{esc(ne["topStory"])}</div>', unsafe_allow_html=True)
                if ne.get("catalysts"):
                    st.markdown(f'<div class="sec-body" style="margin-bottom:4px;background:#060f09;border-color:#16a34a55"><span style="color:#4ade80;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">Catalysts: </span>{esc(ne["catalysts"])}</div>', unsafe_allow_html=True)
                if ne.get("risks"):
                    st.markdown(f'<div class="sec-body" style="margin-bottom:4px;background:#150505;border-color:#dc262655"><span style="color:#f87171;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">Risks: </span>{esc(ne["risks"])}</div>', unsafe_allow_html=True)
                # Key themes
                themes = ne.get("keyThemes", [])
                if themes:
                    themes_html = ' '.join(f'<span style="display:inline-block;font-size:15px;padding:3px 8px;border:1px solid #1a2e48;background:#0d1825;color:#93c5fd;margin:2px">{esc(t)}</span>' for t in themes[:6])
                    st.markdown(f'<div style="margin-bottom:8px">{themes_html}</div>', unsafe_allow_html=True)
                # Upcoming events for this stock
                evt_list = ne.get("upcomingEvents", [])
                if evt_list:
                    st.markdown('<div style="font-size:15px;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;margin:8px 0 5px">Upcoming Events</div>', unsafe_allow_html=True)
                    for evt in evt_list:
                        e_imp    = evt.get("impact","Medium")
                        e_col    = "#f87171" if e_imp=="High" else "#fbbf24" if e_imp=="Medium" else "#4ade80"
                        note_html = f'<div style="font-size:15px;color:#94a3b8;margin-top:3px">{esc(evt.get("note",""))}</div>' if evt.get("note") else ''
                        st.markdown(
                            f'<div style="background:#090f1a;border:1px solid #111c2a;border-left:3px solid {e_col};padding:8px 12px;margin-bottom:5px">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
                            f'<span style="font-size:15px;color:#e2e8f0">{esc(evt.get("event",""))}</span>'
                            f'<span style="font-size:15px;color:{e_col};white-space:nowrap">{esc(evt.get("date",""))}</span>'
                            f'</div>{note_html}</div>',
                            unsafe_allow_html=True)
                # Actual Finnhub news headlines for this stock
                tk_news_list = st.session_state.get('finnhub_news', {}).get(tk_key, [])
                if tk_news_list:
                    st.markdown('<div style="font-size:15px;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;margin:10px 0 5px">Recent Headlines</div>', unsafe_allow_html=True)
                    for art in tk_news_list[:5]:
                        ts = art.get("datetime", 0)
                        try:    art_date = _dt.fromtimestamp(ts).strftime("%b %d") if ts else ""
                        except: art_date = ""
                        headline = esc(art.get("headline",""))
                        source   = esc(art.get("source",""))
                        summary  = esc(art.get("summary",""))
                        url      = art.get("url","")
                        safe_url = url if re.match(r'^https?://', url) else ""
                        # Pre-compute all conditional HTML fragments
                        if safe_url:
                            hl_html2 = f'<a href="{html_lib.escape(safe_url)}" target="_blank" rel="noopener noreferrer" style="text-decoration:none"><div style="font-size:15px;color:#e2e8f0;font-weight:700;line-height:1.4">{headline}</div></a>'
                        else:
                            hl_html2 = f'<div style="font-size:15px;color:#e2e8f0;font-weight:700;line-height:1.4">{headline}</div>'
                        sum_html2  = f'<div style="font-size:15px;color:#94a3b8;margin-top:2px;line-height:1.5">{summary}</div>' if summary else ''
                        date_part  = f' &middot; {esc(art_date)}' if art_date else ''
                        st.markdown(
                            f'<div style="background:#090f1a;border:1px solid #111c2a;border-left:2px solid #1a2e48;padding:8px 11px;margin-bottom:5px">'
                            f'{hl_html2}{sum_html2}'
                            f'<div style="font-size:15px;color:#5a7a99;margin-top:4px">{source}{date_part}</div>'
                            f'</div>',
                            unsafe_allow_html=True)

            # ── Analyst ratings ──
            analysts = s.get('topAnalysts', [])
            if analysts:
                st.markdown('<div class="sec-hdr">◈ Analyst Ratings</div>', unsafe_allow_html=True)
                a_html = ''
                for a in analysts:
                    r_cls  = rating_cls(a.get("rating",""))
                    r_col  = "#4ade80" if r_cls=="sig-good" else "#f87171" if r_cls=="sig-bad" else "#fbbf24"
                    thesis = esc(a.get("thesis",""))
                    a_html += (
                        f'<div class="mob-card">'
                        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:6px">'
                        f'<span style="font-size:15px;font-weight:700;color:#e2e8f0">{esc(a.get("firm",""))}</span>'
                        f'<span style="font-size:15px;font-weight:800;color:{r_col}">{esc(a.get("rating",""))}</span>'
                        f'</div>'
                        f'<div class="mob-card-row">'
                        f'<span class="mob-card-label">Analyst</span><span class="mob-card-val" style="color:#94a3b8">{esc(a.get("name",""))}</span>'
                        f'</div>'
                        f'<div class="mob-card-row">'
                        f'<span class="mob-card-label">Target</span><span class="mob-card-val" style="color:#93c5fd">{esc(a.get("target",""))}</span>'
                        f'</div>'
                        + (f'<div class="mob-card-full">{thesis}</div>' if thesis else '')
                        + f'</div>'
                    )
                st.markdown(a_html, unsafe_allow_html=True)

            # ── Sector Analysis ──
            sa = s.get('sectorAnalysis', {})
            if sa:
                st.markdown('<div class="sec-hdr">◈ Sector Analysis & Peer Comparison</div>', unsafe_allow_html=True)
                sec_html  = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">'
                if sa.get("sector"):
                    sec_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:140px"><div class="label">Sector</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;color:#93c5fd">{esc(sa["sector"])}</div></div>'
                if sa.get("sectorRank"):
                    sec_html += f'<div class="card" style="padding:10px 14px;flex:1;min-width:140px"><div class="label">Sector Rank</div><div style="font-family:Syne,sans-serif;font-size:15px;font-weight:700;color:#f0f6ff">{esc(sa["sectorRank"])}</div></div>'
                sec_html += '</div>'
                if sa.get("sectorOutlook"):
                    sec_html += f'<div class="sec-body" style="margin-bottom:10px">{esc(sa["sectorOutlook"])}</div>'
                st.markdown(sec_html, unsafe_allow_html=True)

                peers = sa.get('peerComparison', [])
                if peers:
                    peer_html = ''
                    for p2 in peers:
                        v2      = p2.get("verdict","")
                        v_color = "#4ade80" if v2 in ("Above","Premium","Inline") else "#f87171" if v2 in ("Below","Discount") else "#fbbf24"
                        peer_html += (
                            f'<div class="mob-card">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:6px">'
                            f'<span style="font-weight:700;color:#e2e8f0;font-size:15px">{esc(p2.get("peer",""))}</span>'
                            f'<span style="color:{v_color};font-weight:700;font-size:15px">{esc(v2)}</span>'
                            f'</div>'
                            f'<div class="mob-card-row"><span class="mob-card-label">Metric</span><span class="mob-card-val" style="color:#94a3b8">{esc(p2.get("metric",""))}</span></div>'
                            f'<div class="mob-card-row"><span class="mob-card-label">Peer</span><span class="mob-card-val" style="color:#cbd5e1">{esc(p2.get("peerVal","—"))}</span></div>'
                            f'<div class="mob-card-row"><span class="mob-card-label">This Stock</span><span class="mob-card-val" style="color:#f0f6ff">{esc(p2.get("stockVal","—"))}</span></div>'
                            f'</div>'
                        )
                    st.markdown(peer_html, unsafe_allow_html=True)

                cat_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px">'
                if sa.get("sectorCatalysts"):
                    cat_html += f'<div class="card card-green" style="padding:11px"><div class="label">Sector Catalysts</div><div style="font-size:15px;color:#e2e8f0;line-height:1.8;margin-top:4px">{esc(sa["sectorCatalysts"])}</div></div>'
                if sa.get("sectorRisks"):
                    cat_html += f'<div class="card card-red" style="padding:11px"><div class="label">Sector Risks</div><div style="font-size:15px;color:#e2e8f0;line-height:1.8;margin-top:4px">{esc(sa["sectorRisks"])}</div></div>'
                cat_html += '</div>'
                st.markdown(cat_html, unsafe_allow_html=True)

            # ── Risk Analysis ──
            ra = s.get('riskAnalysis', {})
            if ra:
                st.markdown('<div class="sec-hdr">⚠ Detailed Risk Analysis</div>', unsafe_allow_html=True)
                rating    = ra.get("overallRiskRating","Medium")
                risk_score= ra.get("riskScore", 50)
                try: risk_score = int(risk_score)
                except: risk_score = 50
                r_color = "#4ade80" if rating=="Low" else "#fbbf24" if rating=="Medium" else "#f87171" if rating=="High" else "#dc2626"
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:16px;padding:12px;background:#090f1a;border:1px solid #111c2a;margin-bottom:10px">
                  <div><div class="label">Risk Rating</div><div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:{r_color}">{esc(rating)}</div></div>
                  <div><div class="label">Risk Score</div><div style="font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:{r_color}">{risk_score}<span style="font-size:15px;color:#5a7a99">/100</span></div></div>
                  <div style="flex:1">
                    <div class="label" style="margin-bottom:5px">Risk Meter</div>
                    <div style="height:6px;background:#1a2e48;border-radius:3px">
                      <div style="height:6px;width:{risk_score}%;background:{r_color};border-radius:3px"></div>
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                for rkey, rlbl in [("businessRisk","🏢 Business"),("financialRisk","💰 Financial"),
                                   ("macroRisk","🌐 Macro"),("regulatoryRisk","⚖️ Regulatory"),
                                   ("valuationRisk","📊 Valuation")]:
                    if ra.get(rkey):
                        st.markdown(f'<div class="sec-body" style="margin-bottom:6px"><span style="color:#3b82f6;font-family:Syne,sans-serif;font-size:15px;letter-spacing:1px">{esc(rlbl)}: </span>{esc(ra[rkey])}</div>', unsafe_allow_html=True)

                key_risks = ra.get("keyRisks", [])
                if key_risks:
                    kr_html = ''
                    for kr in key_risks:
                        sev = kr.get("severity","Medium")
                        lik = kr.get("likelihood","Medium")
                        sc  = "#f87171" if sev=="High" else "#fbbf24" if sev=="Medium" else "#4ade80"
                        lc  = "#f87171" if lik=="High" else "#fbbf24" if lik=="Medium" else "#4ade80"
                        mit = esc(kr.get("mitigation",""))
                        kr_html += (
                            f'<div class="mob-card">'
                            f'<div style="font-size:15px;color:#e2e8f0;font-weight:700;margin-bottom:8px">{esc(kr.get("risk",""))}</div>'
                            f'<div class="mob-card-row">'
                            f'<span class="mob-card-label">Severity</span>'
                            f'<span class="mob-card-val" style="color:{sc}">● {esc(sev)}</span>'
                            f'</div>'
                            f'<div class="mob-card-row">'
                            f'<span class="mob-card-label">Likelihood</span>'
                            f'<span class="mob-card-val" style="color:{lc}">● {esc(lik)}</span>'
                            f'</div>'
                            + (f'<div class="mob-card-full">{mit}</div>' if mit else '')
                            + f'</div>'
                        )
                    st.markdown(kr_html, unsafe_allow_html=True)

                if ra.get("bearCasePrice") or ra.get("bullCasePrice"):
                    bc1, bc2 = st.columns(2)
                    with bc1:
                        st.markdown(f'<div class="card card-red" style="padding:11px"><div class="label">Bear Case Price</div><div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#f87171">{esc(ra.get("bearCasePrice","—"))}</div></div>', unsafe_allow_html=True)
                    with bc2:
                        st.markdown(f'<div class="card card-green" style="padding:11px"><div class="label">Bull Case Price</div><div style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:#4ade80">{esc(ra.get("bullCasePrice","—"))}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="disc">FOR INFORMATIONAL PURPOSES ONLY — NOT FINANCIAL ADVICE</div>', unsafe_allow_html=True)