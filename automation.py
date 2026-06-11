"""
NGUYENILY X — Portfolio IQ  |  Daily Automation
================================================
Runs headlessly (no Streamlit) every trading day at 7:15 AM EST via GitHub Actions.

Steps:
  1. Import portfolio from Google Sheet (published CSV)
  2. Fetch live data: Finnhub (prices, news) + FMP (fundamentals, earnings)
  3. Call Claude API → News & Events + Portfolio analysis JSON
  4. Render styled HTML email
  5. Send via Gmail SMTP

Secrets required (GitHub Actions → Settings → Secrets):
  ANTHROPIC_API_KEY
  FMP_API_KEY
  FINNHUB_API_KEY
  GOOGLE_SHEET_CSV_URL
  GMAIL_SENDER          e.g. yourname@gmail.com
  GMAIL_APP_PASSWORD    Gmail App Password (not your regular password)
  EMAIL_RECIPIENT       email to send to
"""

import os
import re
import json
import csv
import io
import html as html_lib
import smtplib
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime as _dt, timedelta as _td
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

# ── Helpers ───────────────────────────────────────────────────────────────────

def esc(value):
    if value is None: return ''
    return html_lib.escape(str(value))

def clean_ticker(raw):
    if not raw: return ''
    return re.sub(r'[^A-Z0-9.-]', '', str(raw).upper().strip())[:10]

def clean_number(raw):
    if raw is None: return ''
    return re.sub(r'[^0-9.]', '', str(raw).strip())[:20]

def fm(v):
    if v is None or v == 'N/A': return 'N/A'
    try:
        n = float(v)
        if abs(n) >= 1e9: return f'${n/1e9:.2f}B'
        if abs(n) >= 1e6: return f'${n/1e6:.1f}M'
        return f'${n:,.0f}'
    except: return str(v)

def log(msg):
    print(f"[{_dt.now().strftime('%H:%M:%S')}] {msg}")

# ── Load secrets ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.environ['ANTHROPIC_API_KEY']
FMP_API_KEY          = os.environ['FMP_API_KEY']
FINNHUB_API_KEY      = os.environ['FINNHUB_API_KEY']
GOOGLE_SHEET_CSV_URL = os.environ['GOOGLE_SHEET_CSV_URL']
GMAIL_SENDER         = os.environ['GMAIL_SENDER']
GMAIL_APP_PASSWORD   = os.environ['GMAIL_APP_PASSWORD']
EMAIL_RECIPIENT      = os.environ['EMAIL_RECIPIENT']

# ── Step 1: Import portfolio from Google Sheet ────────────────────────────────

def import_portfolio(sheet_url):
    log("Importing portfolio from Google Sheet...")
    url = sheet_url.strip()
    if 'output=csv' not in url:
        if '/pub?' in url:
            url += ('&output=csv' if '?' in url else '?output=csv')
        else:
            m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
            if m:
                url = f'https://docs.google.com/spreadsheets/d/{m.group(1)}/pub?output=csv'
            else:
                raise ValueError('Cannot parse Google Sheets URL')

    with urllib.request.urlopen(url, timeout=15) as r:
        raw_csv = r.read().decode('utf-8-sig')

    reader = csv.DictReader(io.StringIO(raw_csv))
    rows   = list(reader)
    if not rows:
        raise ValueError('Google Sheet is empty')

    headers = {k.lower().strip(): k for k in rows[0].keys()}

    def find_col(candidates):
        for cand in candidates:
            for h_low, h_orig in headers.items():
                if cand in h_low: return h_orig
        return None

    ticker_col = find_col(['ticker', 'symbol', 'stock'])
    shares_col = find_col(['shares', 'quantity', 'qty', 'units'])
    cost_col   = find_col(['avg cost', 'average cost', 'cost basis', 'avg price',
                           'average price', 'cost per', 'price'])

    if not ticker_col: raise ValueError(f'No Ticker column found. Columns: {list(rows[0].keys())}')
    if not shares_col: raise ValueError(f'No Shares column found. Columns: {list(rows[0].keys())}')

    holdings = []
    for row in rows:
        tk  = clean_ticker(row.get(ticker_col, ''))
        sh  = clean_number(row.get(shares_col, ''))
        cst = clean_number(row.get(cost_col,   '') if cost_col else '')
        if tk and sh:
            holdings.append({'ticker': tk, 'shares': sh, 'cost': cst})

    # Sort by market value descending, cap at 15
    def mkt_val(h):
        try: return float(h['shares']) * float(h['cost']) if h['cost'] else float(h['shares'])
        except: return 0
    holdings.sort(key=mkt_val, reverse=True)
    holdings = holdings[:15]
    log(f"  Imported {len(holdings)} holdings: {', '.join(h['ticker'] for h in holdings)}")
    return holdings

# ── Step 2: Fetch live market data ────────────────────────────────────────────

def fmp_get(endpoint, params=None):
    base = 'https://financialmodelingprep.com/api'
    url  = f'{base}{endpoint}?apikey={FMP_API_KEY}'
    if params:
        url += '&' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

def fmp_fetch_all(ticker):
    endpoints = {
        'quote':            f'/v3/quote/{ticker}',
        'profile':          f'/v3/profile/{ticker}',
        'ratios':           f'/v3/ratios-ttm/{ticker}',
        'income':           f'/v3/income-statement/{ticker}',
        'cashflow':         f'/v3/cash-flow-statement/{ticker}',
        'balance':          f'/v3/balance-sheet-statement/{ticker}',
        'estimates':        f'/v3/analyst-estimates/{ticker}',
        'targets':          f'/v4/price-target-consensus',
        'target_list':      f'/v4/price-target',
        'dcf':              f'/v3/discounted-cash-flow/{ticker}',
        'earnings_next':    f'/v3/historical/earning_calendar/{ticker}',
        'earnings_upcoming':f'/v3/earning_calendar',
    }
    results = {}
    def fetch_one(key, ep):
        if key in ('targets', 'target_list'):
            params = {'symbol': ticker}
        elif key == 'earnings_upcoming':
            today  = _dt.now().strftime('%Y-%m-%d')
            future = (_dt.now() + _td(days=180)).strftime('%Y-%m-%d')
            params = {'symbol': ticker, 'from': today, 'to': future}
        else:
            params = None
        return key, fmp_get(ep, params)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_one, k, v): k for k, v in endpoints.items()}
        for fut in as_completed(futs):
            key, data = fut.result()
            results[key] = data
    return results

def finnhub_get(path, params=None):
    url = f'https://finnhub.io/api/v1{path}?token={FINNHUB_API_KEY}'
    if params:
        url += '&' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}

def fetch_ticker_data(h):
    tk  = clean_ticker(h['ticker'])
    log(f"  Fetching {tk}...")

    fmp_raw  = fmp_fetch_all(tk)
    fh_quote = finnhub_get(f'/quote', {'symbol': tk})
    fh_sent  = finnhub_get(f'/news-sentiment', {'symbol': tk})

    # Upcoming earnings via Finnhub calendar
    today  = _dt.now().strftime('%Y-%m-%d')
    future = (_dt.now() + _td(days=365)).strftime('%Y-%m-%d')
    fh_earn = finnhub_get('/calendar/earnings', {'symbol': tk, 'from': today, 'to': future})

    # Recent news (last 30 days)
    from_date = (_dt.now() - _td(days=30)).strftime('%Y-%m-%d')
    fh_news_raw = finnhub_get('/company-news', {'symbol': tk, 'from': from_date, 'to': today})
    fh_news = [
        {
            'headline': str(n.get('headline', ''))[:200],
            'source':   str(n.get('source',   ''))[:60],
            'datetime': n.get('datetime', 0),
            'url':      str(n.get('url',      ''))[:300],
            'summary':  str(n.get('summary',  ''))[:300],
        }
        for n in (fh_news_raw if isinstance(fh_news_raw, list) else [])
        if n.get('headline')
    ][:8]

    # Override FMP price with Finnhub real-time price
    if fh_quote.get('c') and fh_quote['c'] > 0:
        if isinstance(fmp_raw.get('quote'), list) and fmp_raw['quote']:
            fmp_raw['quote'][0]['price'] = fh_quote['c']
            fmp_raw['quote'][0]['changesPercentage'] = fh_quote.get('dp', 0)
        else:
            fmp_raw['quote'] = [{'price': fh_quote['c'], 'changesPercentage': fh_quote.get('dp', 0)}]

    fmp_raw['_fh_earn'] = fh_earn
    fmp_raw['_fh_news'] = fh_news
    fmp_raw['_fh_sent'] = fh_sent

    return tk, fmp_raw

def fetch_all_holdings(holdings):
    log("Fetching live market data (parallel)...")
    raw_data = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(fetch_ticker_data, h): h['ticker'] for h in holdings}
        for fut in as_completed(futs):
            tk, data = fut.result()
            raw_data[tk] = data
            log(f"  ✓ {tk}")
    return raw_data

# ── Step 3: Build locked data + prompt context ────────────────────────────────

def build_locked_context(holdings, raw_data):
    locked_lines = ['\n=== LIVE LOCKED DATA (use exact values) ===']
    for h in holdings:
        tk  = clean_ticker(h['ticker'])
        raw = raw_data.get(tk, {})

        q = (raw.get('quote') or [{}])
        q = q[0] if isinstance(q, list) and q else q if isinstance(q, dict) else {}
        p = (raw.get('profile') or [{}])
        p = p[0] if isinstance(p, list) and p else p if isinstance(p, dict) else {}
        r = (raw.get('ratios') or [{}])
        r = r[0] if isinstance(r, list) and r else r if isinstance(r, dict) else {}
        inc = (raw.get('income') or [{}])
        inc = inc[0] if isinstance(inc, list) and inc else {}
        est = (raw.get('estimates') or [{}])
        est = est[0] if isinstance(est, list) and est else {}
        tgt = raw.get('targets')
        if isinstance(tgt, list) and tgt: tgt = tgt[0]
        fh_sent = raw.get('_fh_sent', {})
        fh_news = raw.get('_fh_news', [])
        fh_earn = raw.get('_fh_earn', {})

        lines = [f'\n--- {tk} ---']
        if q.get('price'):
            lines.append(f'  currentPrice: ${q["price"]:,.2f}')
            lines.append(f'  change: {q.get("changesPercentage", "N/A")}%')
            lines.append(f'  52wkHigh: {q.get("yearHigh", "N/A")}  52wkLow: {q.get("yearLow", "N/A")}')
            lines.append(f'  50dMA: {q.get("priceAvg50", "N/A")}  200dMA: {q.get("priceAvg200", "N/A")}')
        if p.get('sector'):
            lines.append(f'  sector: {p["sector"]}  industry: {p.get("industry","N/A")}')
        if r:
            def fmt_r(v):
                if v is None: return 'N/A'
                try: return f'{float(v):.2f}'
                except: return str(v)
            lines.append(f'  PE: {fmt_r(r.get("peRatioTTM"))}  EV/EBITDA: {fmt_r(r.get("enterpriseValueMultipleTTM"))}')
            lines.append(f'  netMargin: {fmt_r(r.get("netProfitMarginTTM"))}  grossMargin: {fmt_r(r.get("grossProfitMarginTTM"))}')
        if inc:
            lines.append(f'  revenue: {fm(inc.get("revenue"))}  netIncome: {fm(inc.get("netIncome"))}')
            lines.append(f'  ebitda: {fm(inc.get("ebitda"))}  eps: {inc.get("eps","N/A")}')
        if isinstance(tgt, dict) and tgt.get('targetConsensus'):
            lines.append(f'  analystTarget: ${tgt["targetConsensus"]}  '
                         f'high: ${tgt.get("targetHigh","N/A")}  low: ${tgt.get("targetLow","N/A")}')
        # Finnhub sentiment
        if fh_sent.get('buzz'):
            buzz = fh_sent['buzz']
            sent = fh_sent.get('sentiment', {})
            lines.append(f'  newssentiment: buzz={buzz.get("buzz","N/A")} '
                         f'bullish={sent.get("bullishPercent","N/A")} '
                         f'bearish={sent.get("bearishPercent","N/A")}')
        # Upcoming earnings
        today_str = _dt.now().strftime('%Y-%m-%d')
        earn_list = fh_earn.get('earningsCalendar', []) if isinstance(fh_earn, dict) else []
        future_earns = sorted([e for e in earn_list if e.get('date','') >= today_str],
                               key=lambda x: x.get('date',''))
        if future_earns:
            ne = future_earns[0]
            lines.append(f'  nextEarnings: {ne.get("date","N/A")} '
                         f'estEPS={ne.get("epsEstimated","N/A")} '
                         f'timing={ne.get("hour","N/A")}')
        # News headlines
        if fh_news:
            lines.append(f'  recentNews ({len(fh_news)} articles):')
            for i, art in enumerate(fh_news[:5]):
                ts = art.get('datetime', 0)
                try:    dstr = _dt.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else '?'
                except: dstr = '?'
                lines.append(f'    {i+1}. [{dstr}] {art.get("headline","")}')
                if art.get('summary'):
                    lines.append(f'       {art["summary"][:200]}')

        locked_lines.extend(lines)

    locked_lines.append('\n=== END LOCKED DATA ===')
    return '\n'.join(locked_lines)

# ── Step 4: Call Claude API ───────────────────────────────────────────────────

def run_analysis(holdings, raw_data):
    port_val = sum(
        float(h['shares']) * float(h['cost'])
        for h in holdings
        if h.get('shares') and h.get('cost')
    )
    port_note = ', '.join(
        f"{h['ticker']} {h['shares']}sh@${h['cost']}"
        for h in holdings
    )
    tickers   = [clean_ticker(h['ticker']) for h in holdings]
    locked_ctx = build_locked_context(holdings, raw_data)

    prompt = f"""You are a senior portfolio analyst. Today is {_dt.now().strftime('%A, %B %d, %Y')} at 7:15 AM EST — pre-market.

Portfolio ({len(holdings)} holdings, ~${port_val:,.0f}): {port_note}

Your job: produce a morning briefing focused on NEWS, EVENTS, and EARNINGS that could affect these holdings TODAY and this week.

Return ONLY valid JSON:
{{
  "briefingDate": "{_dt.now().strftime('%Y-%m-%d')}",
  "marketContext": "2 sentences on overall market conditions this morning",
  "portfolioSummary": {{
    "overallSentiment": "Bullish/Neutral/Bearish",
    "keyTheme": "1 sentence on the dominant theme across the portfolio today",
    "actionRequired": true,
    "urgentAlerts": ["alert 1 if any", "alert 2 if any"]
  }},
  "earningsCalendar": [
    {{
      "ticker": "TICKER",
      "date": "YYYY-MM-DD",
      "daysUntil": "Today / Tomorrow / X days",
      "estimatedEPS": "$X",
      "timing": "BMO / AMC",
      "importance": "High / Medium / Low",
      "whatToWatch": "2 sentences on key metrics and catalysts to monitor",
      "priceImpactRisk": "High / Medium / Low",
      "consensusTarget": "$X"
    }}
  ],
  "newsAndEvents": [
    {{
      "ticker": "TICKER",
      "overallSentiment": "Positive / Neutral / Negative",
      "sentimentScore": 65,
      "topStory": "1 sentence on most important news",
      "impact": "Bullish / Neutral / Bearish",
      "impactReason": "1 sentence explaining why",
      "actionSuggestion": "Hold / Consider adding / Consider trimming / Watch closely",
      "headlines": [
        {{"date": "YYYY-MM-DD", "headline": "...", "source": "...", "sentiment": "Positive/Neutral/Negative"}}
      ],
      "upcomingEvents": [
        {{"event": "...", "date": "approximate", "impact": "High/Medium/Low"}}
      ]
    }}
  ],
  "portfolioAlerts": [
    {{
      "type": "Earnings / News / Macro / Technical",
      "severity": "High / Medium / Low",
      "ticker": "TICKER or PORTFOLIO",
      "alert": "1 sentence describing the alert",
      "action": "1 sentence recommended action"
    }}
  ],
  "macroEvents": [
    {{
      "event": "Fed meeting / CPI / Jobs report / etc",
      "date": "YYYY-MM-DD or approximate",
      "affectedTickers": ["TICKER1", "TICKER2"],
      "impact": "High / Medium / Low",
      "note": "1 sentence"
    }}
  ],
  "watchList": [
    {{
      "ticker": "TICKER",
      "reason": "1 sentence on why to watch closely today",
      "priceLevel": "$X key level to watch"
    }}
  ]
}}

CRITICAL:
- newsAndEvents MUST cover ALL {len(tickers)} tickers: {tickers}
- Use actual headlines from the LOCKED DATA below — do not invent headlines
- sentimentScore: 0=extremely bearish, 50=neutral, 100=extremely bullish
- earningsCalendar: only include tickers with confirmed upcoming earnings dates
- Flag any earnings within 7 days as High importance
- Be specific — cite actual company names, products, dollar figures from the news
- Today is pre-market so flag anything market-moving from overnight/pre-market

{locked_ctx}"""

    log("Calling Claude API...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model='claude-sonnet-4-5',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}]
    )
    raw_text = ''.join(b.text for b in response.content if hasattr(b, 'text'))
    log(f"  Claude responded ({len(raw_text)} chars)")

    # Parse JSON
    txt = re.sub(r'```json\s*', '', raw_text, flags=re.I)
    txt = re.sub(r'```\s*', '', txt).strip()
    try:
        return json.loads(txt)
    except Exception:
        a, b2 = txt.find('{'), txt.rfind('}')
        if a >= 0 and b2 > a:
            try: return json.loads(txt[a:b2+1])
            except: pass
    log("  WARNING: Could not parse JSON — returning raw text")
    return {'_raw': raw_text}

# ── Step 5: Render HTML email ─────────────────────────────────────────────────

def render_email(holdings, raw_data, analysis, run_dt):
    port_val = sum(
        float(h['shares']) * float(h['cost'])
        for h in holdings
        if h.get('shares') and h.get('cost')
    )

    # Colour helpers
    def sent_color(s):
        s = (s or '').lower()
        if 'bull' in s or 'pos' in s: return '#4ade80'
        if 'bear' in s or 'neg' in s: return '#f87171'
        return '#fbbf24'

    def imp_color(i):
        i = (i or '').lower()
        if 'high' in i: return '#f87171'
        if 'low' in i:  return '#4ade80'
        return '#fbbf24'

    def sev_color(s): return imp_color(s)

    ps  = analysis.get('portfolioSummary', {})
    ec  = analysis.get('earningsCalendar', [])
    ne  = analysis.get('newsAndEvents', [])
    pa  = analysis.get('portfolioAlerts', [])
    mac = analysis.get('macroEvents', [])
    wl  = analysis.get('watchList', [])

    overall_sent  = ps.get('overallSentiment', 'Neutral')
    overall_color = sent_color(overall_sent)

    # ── Holdings summary rows ──
    holdings_rows = ''
    for h in holdings:
        tk  = clean_ticker(h['ticker'])
        raw = raw_data.get(tk, {})
        q   = (raw.get('quote') or [{}])
        q   = q[0] if isinstance(q, list) and q else q if isinstance(q, dict) else {}
        price = q.get('price')
        chg   = q.get('changesPercentage')
        try:
            cost_b = float(h['shares']) * float(h['cost']) if h.get('cost') else 0
            live_v = float(h['shares']) * float(price) if price else 0
            gl_pct = ((float(price) - float(h['cost'])) / float(h['cost']) * 100) if price and h.get('cost') else None
            gl_col = '#4ade80' if gl_pct and gl_pct >= 0 else '#f87171'
            gl_str = f'{"▲" if gl_pct >= 0 else "▼"} {abs(gl_pct):.1f}%' if gl_pct is not None else '—'
        except: cost_b = 0; live_v = 0; gl_str = '—'; gl_col = '#fbbf24'

        chg_col = '#4ade80' if chg and float(chg) >= 0 else '#f87171'
        chg_str = f'{"▲" if chg and float(chg) >= 0 else "▼"} {abs(float(chg)):.2f}%' if chg else '—'

        holdings_rows += f"""
        <tr>
          <td style="font-weight:800;color:#f0f6ff;padding:10px 12px;border-bottom:1px solid #0d1825">{esc(tk)}</td>
          <td style="color:#f0f6ff;padding:10px 12px;border-bottom:1px solid #0d1825">
            {f'${float(price):,.2f}' if price else '—'}
          </td>
          <td style="color:{chg_col};font-weight:700;padding:10px 12px;border-bottom:1px solid #0d1825">{chg_str}</td>
          <td style="color:{gl_col};font-weight:700;padding:10px 12px;border-bottom:1px solid #0d1825">{gl_str}</td>
          <td style="color:#94a3b8;padding:10px 12px;border-bottom:1px solid #0d1825">{h.get('shares','—')}</td>
          <td style="color:#94a3b8;padding:10px 12px;border-bottom:1px solid #0d1825">{f'${float(h["cost"]):,.2f}' if h.get('cost') else '—'}</td>
        </tr>"""

    # ── Alerts ──
    alerts_html = ''
    for alert in pa:
        sev = alert.get('severity','Medium')
        sc  = sev_color(sev)
        bg  = '#150505' if sev=='High' else '#0f1208' if sev=='Low' else '#0d0b02'
        bd  = '#dc262655' if sev=='High' else '#16a34a55' if sev=='Low' else '#ca8a0455'
        alerts_html += f"""
        <div style="background:{bg};border:1px solid {bd};border-left:4px solid {sc};
                    padding:12px 16px;margin-bottom:8px;border-radius:2px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-weight:800;color:{sc};font-size:13px;letter-spacing:1px;text-transform:uppercase">
              {esc(alert.get('type',''))} — {esc(alert.get('ticker',''))}
            </span>
            <span style="color:{sc};font-size:12px;border:1px solid {sc}55;padding:2px 8px">
              {esc(sev)}
            </span>
          </div>
          <div style="color:#e2e8f0;font-size:15px;margin-bottom:4px">{esc(alert.get('alert',''))}</div>
          <div style="color:#94a3b8;font-size:14px">→ {esc(alert.get('action',''))}</div>
        </div>"""

    # ── Earnings calendar ──
    earnings_html = ''
    if ec:
        for item in sorted(ec, key=lambda x: x.get('date','9999')):
            imp = item.get('importance','Medium')
            ic  = imp_color(imp)
            earnings_html += f"""
            <div style="background:#090f1a;border:1px solid #1a2e48;padding:14px 16px;
                        margin-bottom:8px;border-radius:2px">
              <div style="display:flex;justify-content:space-between;align-items:center;
                          flex-wrap:wrap;gap:8px;margin-bottom:8px">
                <span style="font-family:monospace;font-size:20px;font-weight:800;color:#f0f6ff">
                  {esc(item.get('ticker',''))}
                </span>
                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                  <span style="color:#93c5fd;font-weight:700">{esc(item.get('date',''))}</span>
                  <span style="color:#94a3b8">{esc(item.get('daysUntil',''))}</span>
                  <span style="color:{ic};font-size:12px;border:1px solid {ic}55;padding:2px 8px">
                    {esc(imp)}
                  </span>
                </div>
              </div>
              <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">
                <span style="color:#a78bfa"><b>Est. EPS:</b> {esc(item.get('estimatedEPS',''))}</span>
                <span style="color:#94a3b8"><b>Timing:</b> {esc(item.get('timing',''))}</span>
                <span style="color:#fbbf24"><b>Price Impact Risk:</b> {esc(item.get('priceImpactRisk',''))}</span>
                {f'<span style="color:#93c5fd"><b>Target:</b> {esc(item.get("consensusTarget",""))}</span>' if item.get('consensusTarget') else ''}
              </div>
              <div style="color:#e2e8f0;font-size:15px;line-height:1.6">
                {esc(item.get('whatToWatch',''))}
              </div>
            </div>"""
    else:
        earnings_html = '<div style="color:#94a3b8;padding:12px">No earnings scheduled in the near term.</div>'

    # ── News & Events per ticker ──
    news_html = ''
    for item in ne:
        tk_ne   = esc(item.get('ticker',''))
        o_sent  = item.get('overallSentiment','Neutral')
        impact  = item.get('impact','Neutral')
        sc_ne   = sent_color(o_sent)
        score   = item.get('sentimentScore', 50)
        try: score = int(score)
        except: score = 50
        action  = item.get('actionSuggestion','')
        act_col = ('#4ade80' if 'add' in (action or '').lower()
                   else '#f87171' if 'trim' in (action or '').lower()
                   else '#fbbf24')

        headlines_html = ''
        for hl in (item.get('headlines') or [])[:4]:
            hl_sent  = hl.get('sentiment','Neutral')
            hl_col   = sent_color(hl_sent)
            headlines_html += f"""
            <div style="padding:8px 0;border-bottom:1px solid #0d1825">
              <div style="display:flex;justify-content:space-between;gap:8px">
                <span style="color:#e2e8f0;font-size:14px;line-height:1.5;flex:1">
                  {esc(hl.get('headline',''))}
                </span>
                <span style="color:{hl_col};font-size:12px;white-space:nowrap;padding-top:2px">
                  ● {esc(hl_sent)}
                </span>
              </div>
              <div style="color:#5a7a99;font-size:13px;margin-top:2px">
                {esc(hl.get('source',''))} · {esc(hl.get('date',''))}
              </div>
            </div>"""

        events_html = ''
        for evt in (item.get('upcomingEvents') or [])[:3]:
            e_col = imp_color(evt.get('impact','Medium'))
            events_html += f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:6px 0;border-bottom:1px solid #0d1825;flex-wrap:wrap;gap:4px">
              <span style="color:#e2e8f0;font-size:14px">{esc(evt.get('event',''))}</span>
              <span style="color:{e_col};font-size:13px">{esc(evt.get('date',''))}</span>
            </div>"""

        news_html += f"""
        <div style="background:#0d1825;border:1px solid #1a2e48;padding:16px;
                    margin-bottom:12px;border-radius:2px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;
                      flex-wrap:wrap;gap:8px;margin-bottom:12px">
            <div>
              <div style="font-family:monospace;font-size:20px;font-weight:800;color:#f0f6ff">
                {tk_ne}
              </div>
              <div style="color:{sc_ne};font-weight:700;font-size:15px;margin-top:2px">
                {esc(o_sent)} — {esc(impact)}
              </div>
            </div>
            <div style="text-align:right">
              <div style="color:{act_col};font-size:13px;font-weight:700;
                          border:1px solid {act_col}55;padding:4px 10px;margin-bottom:4px">
                {esc(action)}
              </div>
              <div style="font-size:13px;color:#94a3b8">
                Sentiment: <span style="color:{sc_ne};font-weight:700">{score}/100</span>
              </div>
              <div style="height:4px;width:80px;background:#1a2e48;border-radius:2px;
                          margin-top:4px;margin-left:auto">
                <div style="height:4px;width:{score}%;background:{sc_ne};border-radius:2px"></div>
              </div>
            </div>
          </div>
          <div style="color:#e2e8f0;font-size:15px;line-height:1.6;margin-bottom:10px;
                      padding-bottom:10px;border-bottom:1px solid #111c2a">
            {esc(item.get('topStory',''))}
          </div>
          <div style="color:#94a3b8;font-size:14px;margin-bottom:10px">
            {esc(item.get('impactReason',''))}
          </div>
          {f'<div style="margin-bottom:10px">{headlines_html}</div>' if headlines_html else ''}
          {f'<div style="margin-top:8px"><div style="color:#3b82f6;font-size:13px;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px">Upcoming Events</div>{events_html}</div>' if events_html else ''}
        </div>"""

    # ── Macro events ──
    macro_html = ''
    for m in mac:
        ic  = imp_color(m.get('impact','Medium'))
        aff = ', '.join(esc(t) for t in (m.get('affectedTickers') or []))
        macro_html += f"""
        <div style="background:#090f1a;border:1px solid #1a2e48;border-left:3px solid {ic};
                    padding:12px 16px;margin-bottom:6px;border-radius:2px">
          <div style="display:flex;justify-content:space-between;align-items:center;
                      flex-wrap:wrap;gap:6px;margin-bottom:4px">
            <span style="color:#e2e8f0;font-weight:700;font-size:15px">{esc(m.get('event',''))}</span>
            <span style="color:{ic};font-size:13px">{esc(m.get('date',''))}</span>
          </div>
          {f'<div style="color:#fbbf24;font-size:13px;margin-bottom:4px">Affects: {aff}</div>' if aff else ''}
          <div style="color:#94a3b8;font-size:14px">{esc(m.get('note',''))}</div>
        </div>"""

    # ── Watch list ──
    watch_html = ''
    for w in wl:
        watch_html += f"""
        <div style="display:flex;justify-content:space-between;align-items:flex-start;
                    padding:10px 12px;border-bottom:1px solid #0d1825;flex-wrap:wrap;gap:6px">
          <div>
            <span style="font-family:monospace;font-weight:800;color:#f0f6ff;font-size:16px">
              {esc(w.get('ticker',''))}
            </span>
            <div style="color:#e2e8f0;font-size:14px;margin-top:3px">{esc(w.get('reason',''))}</div>
          </div>
          {f'<span style="color:#fbbf24;font-weight:700;font-size:15px">{esc(w.get("priceLevel",""))}</span>' if w.get('priceLevel') else ''}
        </div>"""

    # ── Assemble full email ──
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NGUYENILY X — Portfolio IQ Morning Briefing</title>
</head>
<body style="margin:0;padding:0;background:#060a0f;font-family:'Courier New',monospace;color:#e2e8f0">
<div style="max-width:680px;margin:0 auto;padding:20px 16px">

  <!-- Header -->
  <div style="padding:20px 0 16px;border-bottom:1px solid #1a2e48;margin-bottom:20px">
    <div style="font-size:11px;letter-spacing:4px;color:#3b82f6;text-transform:uppercase;margin-bottom:6px">
      Portfolio Analysis Terminal
    </div>
    <div style="font-size:24px;font-weight:800;color:#f0f6ff;margin-bottom:4px">
      NGUYENILY X &mdash; PORTFOLIO IQ
    </div>
    <div style="font-size:15px;color:#94a3b8">
      Morning Briefing &bull;
      {esc(run_dt.strftime('%A, %B %d, %Y'))} &bull; 7:15 AM EST
    </div>
  </div>

  <!-- Portfolio Summary -->
  <div style="background:#0d1825;border:1px solid #1a2e48;padding:16px;
              margin-bottom:16px;border-radius:2px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
                flex-wrap:wrap;gap:12px;margin-bottom:12px">
      <div>
        <div style="font-size:12px;letter-spacing:2px;color:#94a3b8;
                    text-transform:uppercase;margin-bottom:4px">Portfolio Value</div>
        <div style="font-size:26px;font-weight:800;color:#f0f6ff">${port_val:,.0f}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:12px;letter-spacing:2px;color:#94a3b8;
                    text-transform:uppercase;margin-bottom:4px">Market Sentiment</div>
        <div style="font-size:22px;font-weight:800;color:{overall_color}">{esc(overall_sent)}</div>
      </div>
    </div>
    <div style="color:#e2e8f0;font-size:15px;line-height:1.6;margin-bottom:10px">
      {esc(analysis.get('marketContext',''))}
    </div>
    <div style="color:#93c5fd;font-size:15px;font-weight:700;margin-bottom:8px">
      {esc(ps.get('keyTheme',''))}
    </div>
    {''.join(f'<div style="background:#150505;border:1px solid #dc262655;padding:8px 12px;margin-bottom:4px;font-size:14px;color:#f87171">⚠ {esc(a)}</div>' for a in ps.get('urgentAlerts',[]))}
  </div>

  <!-- Holdings Snapshot -->
  <div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;
              margin-bottom:8px;font-weight:700">◈ Holdings Snapshot</div>
  <div style="background:#0d1825;border:1px solid #1a2e48;margin-bottom:20px;
              border-radius:2px;overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:15px">
      <thead>
        <tr style="background:#090f1a">
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Ticker</th>
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Price</th>
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Today</th>
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Unrealized</th>
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Shares</th>
          <th style="text-align:left;padding:10px 12px;color:#94a3b8;
                     font-size:12px;letter-spacing:2px;text-transform:uppercase;
                     border-bottom:1px solid #1a2e48">Avg Cost</th>
        </tr>
      </thead>
      <tbody>{holdings_rows}</tbody>
    </table>
  </div>

  <!-- Alerts -->
  {'<div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;margin-bottom:8px;font-weight:700">⚠ Portfolio Alerts</div>' + alerts_html + '<div style="margin-bottom:20px"></div>' if alerts_html else ''}

  <!-- Earnings Calendar -->
  <div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;
              margin-bottom:8px;font-weight:700">📅 Upcoming Earnings</div>
  <div style="margin-bottom:20px">{earnings_html}</div>

  <!-- News & Events -->
  <div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;
              margin-bottom:8px;font-weight:700">📰 News & Events by Holding</div>
  <div style="margin-bottom:20px">{news_html}</div>

  <!-- Macro Events -->
  {'<div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;margin-bottom:8px;font-weight:700">🌐 Macro Events to Watch</div><div style="margin-bottom:20px">' + macro_html + '</div>' if macro_html else ''}

  <!-- Watch List -->
  {'<div style="font-size:13px;letter-spacing:3px;color:#3b82f6;text-transform:uppercase;margin-bottom:8px;font-weight:700">👁 Watch Closely Today</div><div style="background:#0d1825;border:1px solid #1a2e48;margin-bottom:20px;border-radius:2px">' + watch_html + '</div>' if watch_html else ''}

  <!-- Footer -->
  <div style="border-top:1px solid #1a2e48;padding-top:16px;text-align:center;
              font-size:12px;color:#4a6a88;letter-spacing:1px">
    FOR INFORMATIONAL PURPOSES ONLY &mdash; NOT FINANCIAL ADVICE<br>
    Generated by NGUYENILY X Portfolio IQ &bull; {esc(run_dt.strftime('%Y-%m-%d %H:%M EST'))}
  </div>

</div>
</body>
</html>"""

    return html

# ── Step 6: Send email via Gmail ──────────────────────────────────────────────

def send_email(html_body, run_dt, holdings):
    log("Sending email...")
    tickers   = ', '.join(clean_ticker(h['ticker']) for h in holdings)
    subject   = (f"Portfolio IQ Briefing — {run_dt.strftime('%a %b %d')} | "
                 f"{len(holdings)} Holdings | {tickers}")

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = GMAIL_SENDER
    msg['To']      = EMAIL_RECIPIENT

    # Plain-text fallback
    plain = (f"NGUYENILY X — Portfolio IQ Morning Briefing\n"
             f"{run_dt.strftime('%A, %B %d, %Y')} — 7:15 AM EST\n\n"
             f"Holdings: {tickers}\n\n"
             f"Open this email in an HTML-capable client to view the full briefing.")
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    log(f"  ✓ Email sent to {EMAIL_RECIPIENT}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    run_dt = _dt.now()
    log(f"=== NGUYENILY X Portfolio IQ — Daily Automation ===")
    log(f"Run time: {run_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1: Import portfolio
    holdings = import_portfolio(GOOGLE_SHEET_CSV_URL)

    # Step 2: Fetch live data
    raw_data = fetch_all_holdings(holdings)

    # Step 3 + 4: Build context and run Claude analysis
    analysis = run_analysis(holdings, raw_data)

    if '_raw' in analysis:
        log("WARNING: Analysis JSON could not be parsed — sending raw text fallback email")
        html_body = f"""<pre style="font-family:monospace;background:#060a0f;color:#e2e8f0;
                        padding:20px;white-space:pre-wrap">{esc(analysis['_raw'])}</pre>"""
    else:
        # Step 5: Render HTML email
        html_body = render_email(holdings, raw_data, analysis, run_dt)

    # Step 6: Send
    send_email(html_body, run_dt, holdings)
    log("=== Done ===")

if __name__ == '__main__':
    main()
