import os
import hmac
from flask import Flask, render_template_string, jsonify, request, Response
from bot_engine import CryptoScalpBot

app = Flask(__name__)
initial_balance = float(os.environ.get("INITIAL_BALANCE", "1000"))
bot = CryptoScalpBot(initial_balance=initial_balance)


@app.before_request
def protect_dashboard_controls():
    """Require Basic Auth when configured; otherwise expose GETs only."""
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not password:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return jsonify({"error": "Read-only mode. Configure DASHBOARD_PASSWORD to enable controls."}), 503
        return None
    auth = request.authorization
    supplied = auth.password if auth and auth.username == "admin" else ""
    if not hmac.compare_digest(supplied, password):
        return Response(
            "Dashboard login required.", 401,
            {"WWW-Authenticate": 'Basic realm="Crypto Paper Scanner"'}
        )
    return None


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OKX BTC-USDT-SWAP Three-Pillar Strategy Bot</title>
    <style>
        :root {
            --bg-primary: #0b0e14;
            --bg-secondary: #151a21;
            --bg-card: #1e2430;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #2a3241;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background-color: var(--bg-primary); color: var(--text-main); padding: 20px; line-height: 1.5; }
        .container { max-width: 1400px; margin: 0 auto; }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 16px;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }

        .brand h1 { font-size: 1.6rem; color: var(--text-main); display: flex; align-items: center; gap: 10px; }
        .status-badge { padding: 4px 12px; border-radius: 9999px; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; }
        .status-running { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .status-stopped { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }

        .grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
        @media (min-width: 900px) {
            .grid-3 { grid-template-columns: 1fr 1fr 1fr; }
            .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
            .grid-2-1 { grid-template-columns: 2fr 1fr; }
            .grid-1-2 { grid-template-columns: 1fr 2fr; }
        }

        .card {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4);
            margin-bottom: 20px;
        }

        .card h2 { font-size: 1.1rem; color: var(--accent-blue); margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }

        .metric-value { font-size: 1.8rem; font-weight: 700; margin-top: 4px; }
        .metric-sub { font-size: 0.85rem; color: var(--text-muted); }
        .val-positive { color: var(--accent-green); }
        .val-negative { color: var(--accent-red); }
        .val-highlight { color: var(--accent-yellow); }

        .form-group { margin-bottom: 12px; }
        label { display: block; font-size: 0.8rem; color: var(--text-muted); margin-bottom: 4px; font-weight: 600; }
        select, input {
            width: 100%; padding: 8px 12px; border-radius: 6px;
            border: 1px solid var(--border-color); background-color: var(--bg-card);
            color: var(--text-main); font-size: 0.9rem;
        }

        .btn-group { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
        button {
            padding: 9px 16px; border-radius: 6px; border: none; font-weight: 600;
            font-size: 0.88rem; cursor: pointer; transition: opacity 0.2s;
        }
        button:hover { opacity: 0.88; }
        .btn-green { background-color: var(--accent-green); color: #000000; }
        .btn-red { background-color: var(--accent-red); color: #ffffff; }
        .btn-blue { background-color: var(--accent-blue); color: #ffffff; }
        .btn-purple { background-color: var(--accent-purple); color: #ffffff; }
        .btn-outline { background: transparent; border: 1px solid var(--border-color); color: var(--text-main); }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.88rem; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border-color); }
        th { color: var(--text-muted); font-weight: 600; background: var(--bg-card); }

        .log-box {
            background-color: var(--bg-primary); border: 1px solid var(--border-color);
            border-radius: 6px; padding: 12px; height: 180px; overflow-y: auto;
            font-family: monospace; font-size: 0.82rem; color: #a7f3d0;
        }

        .tag-long { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); padding: 2px 6px; border-radius: 4px; font-weight: 700; }
        .tag-short { background: rgba(239, 68, 68, 0.2); color: var(--accent-red); padding: 2px 6px; border-radius: 4px; font-weight: 700; }
        
        .conf-badge {
            display: inline-block; background: rgba(139, 92, 246, 0.25); color: var(--accent-purple);
            padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid rgba(139, 92, 246, 0.4);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <h1>📊 OKX BTC-USDT-SWAP Strategy Bot</h1>
                <div id="lblRegime" class="metric-sub">Market regime warming up…</div>
            </div>
            <div>
                <span id="botStatusBadge" class="status-badge status-running">PAPER SCANNER</span>
            </div>
        </header>

        <!-- Metrics Overview -->
        <div class="grid grid-4" style="margin-bottom: 20px;">
            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Account Equity</div>
                <div id="lblBalance" class="metric-value">$1,000.00</div>
                <div id="lblPnL" class="metric-sub val-positive">+$0.00 (+0.0%)</div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Focus Price (<span id="lblActiveSymbol">BTC-USDT-SWAP</span>)</div>
                <div id="lblLivePrice" class="metric-value val-highlight">$0.00</div>
                <div id="lbl24hRange" class="metric-sub">24h High: $0 | Low: $0</div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">1H Context & Funding</div>
                <div id="lbl1HTrend" class="metric-value" style="font-size:1.05rem; color:var(--accent-blue);">BULLISH ↗</div>
                <div class="metric-sub">Funding Rate: <span id="lblFundingRate">+0.008%</span></div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Execution Mode</div>
                <div id="lblExecMode" class="metric-value" style="font-size:1.1rem; color:var(--accent-purple);">CHECKING…</div>
                <div class="metric-sub">Entry rule: <span id="lblMinConf">3</span>/3 pillars in every session</div>
            </div>
        </div>

        <div class="grid grid-2" style="margin-top:18px;">
            <div class="card" style="margin-bottom:0;">
                <h2>🛑 Daily risk gate</h2>
                <div id="dailyRiskStatus" class="metric-sub">Waiting for status…</div>
                <div id="controlStatus" class="metric-sub" style="margin-top:8px;color:var(--accent-yellow);">Dashboard is read-only until protected with a password.</div>
            </div>
            <div class="card" style="margin-bottom:0;">
                <h2>🎯 Current confluence counts</h2>
                <div id="candidateSummary" class="metric-sub">2/3: 0 | 3/3: 0</div>
                <div id="pillarStatus" class="metric-sub" style="margin-top:8px;white-space:pre-wrap;">Waiting for confirmed 5m pillar checks…</div>
            </div>
        </div>

        <!-- Main Workspace -->
        <div class="grid grid-2-1">
            <!-- Left Side -->
            <div>
                <!-- Active Position -->
                <div class="card">
                    <h2>
                        <span>📊 Active Open Position</span>
                        <button id="btnClosePosition" class="btn-red" style="padding:4px 10px; font-size:0.75rem;" onclick="closePositionMarket()">Close Position</button>
                    </h2>
                    <div id="activePositionBox">
                        <p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px 0;">No position open. BTC-USDT-SWAP is the only configured instrument.</p>
                    </div>
                </div>

                <!-- Live Indicators -->
                <div class="card">
                    <h2>📈 Three-Pillar Inputs <span class="metric-sub">(5m trigger, VWAP location and RSI)</span></h2>
                    <div class="grid grid-3" style="gap:10px;">
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">Rolling VWAP (~5h)</div>
                            <div id="indVWAP" class="val-highlight" style="font-weight:700;">$0.00</div>
                        </div>
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">+1 SD VWAP Band</div>
                            <div id="indVWAPUpper" class="val-positive" style="font-weight:700;">$0.00</div>
                        </div>
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">-1 SD VWAP Band</div>
                            <div id="indVWAPLower" class="val-negative" style="font-weight:700;">$0.00</div>
                        </div>
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">20 EMA</div>
                            <div id="indEMA20" style="font-weight:700;">$0.00</div>
                        </div>
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">50 EMA</div>
                            <div id="indEMA50" style="font-weight:700;">$0.00</div>
                        </div>
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">RSI (14)</div>
                            <div id="indRSI" style="font-weight:700;">50.0</div>
                        </div>
                    </div>
                </div>

                <!-- Restored three-pillar candidates -->
                <div class="card">
                    <h2>🎯 2/3 Watchlist and 3/3 Setups</h2>
                    <div style="overflow-x:auto;">
                        <table>
                            <thead><tr><th>Pair</th><th>Side</th><th>Score</th><th>Gate</th><th>Reason</th></tr></thead>
                            <tbody id="confluenceCandidatesBody">
                                <tr><td colspan="5" style="text-align:center;color:var(--text-muted);">Waiting for market data…</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Signals History Table -->
                <div class="card">
                    <h2>🚨 Confirmed BTC-USDT-SWAP Signals</h2>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Symbol</th>
                                    <th>Side</th>
                                    <th>Confluence Score</th>
                                    <th>Entry ($)</th>
                                    <th>Stop Loss ($)</th>
                                    <th>TP1 Target ($)</th>
                                    <th>TP2 Target ($)</th>
                                </tr>
                            </thead>
                            <tbody id="signalsTableBody">
                                <tr><td colspan="8" style="text-align:center; color:var(--text-muted);">Waiting for confirmed BTC-USDT-SWAP three-pillar setups...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Side: Controls & Notifications -->
            <div>
                <!-- Execution is demo-only and environment-armed; no live endpoint exists -->
                <div class="card" style="border: 1px solid var(--accent-yellow);">
                    <h2 style="color:var(--accent-yellow);">🛡️ OKX demo-only execution</h2>
                    <p style="font-size:0.85rem; color:var(--text-muted);">
                        Private orders are hard-pinned to OKX Demo Trading and require server-side demo credentials plus
                        <code>OKX_DEMO_ORDER_ARMED=1</code>. No live-order endpoint or live-key fallback is implemented.
                        Protective-stop and account reconciliation status is shown below; never paste keys here.
                    </p>
                    <div id="demoExecutionStatus" class="metric-sub" style="margin-top:8px;">Checking demo configuration…</div>
                </div>

                <!-- Strategy Controls -->
                <div class="card">
                    <h2>🎮 Focus Contract Settings</h2>
                    
                    <div class="form-group">
                        <label>Configured Contract (fixed)</label>
                        <select id="selSymbol" disabled>
                            <option value="BTC-USDT-SWAP">BTC-USDT-SWAP (OKX linear perpetual)</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label>Active strategy (fixed)</label>
                        <select id="selStrategy" disabled>
                            <option value="playbook_3pillar">Original three-pillar confluence</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label>Consensus threshold (fixed)</label>
                        <select id="selMinConf" disabled>
                            <option value="3">3/3 required in every session</option>
                        </select>
                    </div>

                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                        <div class="form-group">
                            <label>Leverage cap (1×–10×)</label>
                            <input type="number" id="inputLeverage" value="10" min="1" max="10" onchange="updateConfig()">
                        </div>
                        <div class="form-group">
                            <label>Planned Risk Per Trade (%)</label>
                            <input type="number" id="inputRisk" value="1.0" min="0.1" max="1.0" step="0.1" onchange="updateConfig()">
                        </div>
                    </div>

                    <div class="btn-group">
                        <button id="btnStartStop" class="btn-red" style="flex:1;" onclick="toggleBot()">Pause Engine</button>
                        <button id="btnReset" class="btn-outline" onclick="resetAccount()">Reset Paper Ledger</button>
                    </div>

                    <p style="font-size:0.8rem; color:var(--text-muted); margin-top:12px;">
                        One open position maximum. Risk is 1% by default with a strict $3 initial-margin cap and runtime OKX lot-size checks.
                        Entries require all 3/3 pillars in regular and Asian sessions. 2/3 is watch-only. ADX is informational; entries use the next price after the confirmed 5m close.
                    </p>
                </div>

                <!-- Telegram credentials are environment-only and never returned by the API -->
                <div class="card">
                    <h2>📱 Telegram alerts</h2>
                    <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                        Configure <code>TELEGRAM_BOT_TOKEN</code> and <code>TELEGRAM_CHAT_ID</code> as server environment variables.
                        Never paste bot tokens into the page or source code.
                    </p>
                    <div id="tgConfigStatus" class="metric-sub">Checking server configuration…</div>
                    <div class="btn-group">
                        <button id="btnTestAlert" class="btn-blue" style="flex:1; font-size:0.8rem;" onclick="testAlert('telegram')">Send Test Alert</button>
                    </div>
                </div>

                <!-- Execution Output Console -->
                <div class="card">
                    <h2>📝 Execution Output Console</h2>
                    <div id="logConsole" class="log-box">
                        Initializing BTC-USDT-SWAP three-pillar scanner...
                    </div>
                </div>
            </div>
        </div>

        <!-- Closed Trades Table -->
        <div class="card">
            <h2>📜 Closed Trades History</h2>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Symbol</th>
                            <th>Side</th>
                            <th>Strategy</th>
                            <th>Entry Price</th>
                            <th>Exit Price</th>
                            <th>Fees</th>
                            <th>Funding ($)</th>
                            <th>Slip est. ($)</th>
                            <th>Net PnL ($)</th>
                            <th>Net PnL (%)</th>
                            <th>Reason</th>
                        </tr>
                    </thead>
                    <tbody id="closedTradesBody">
<tr><td colspan="12" style="text-align:center; color:var(--text-muted);">No closed trades yet.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        let isRunning = true;

        function formatPrice(val) {
            if (val === null || val === undefined || !Number.isFinite(Number(val))) return '0.00';
            const v = Number(val);
            if (Math.abs(v) < 1.0) return v.toFixed(4);
            if (Math.abs(v) < 100.0) return v.toFixed(3);
            return v.toFixed(2);
        }

        function escapeHtml(value) {
            return String(value ?? '').replace(/[&<>\"']/g, ch => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
            })[ch]);
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status', { cache: 'no-store' });
                if (!res.ok) throw new Error(`Status request failed (${res.status})`);
                const data = await res.json();

                const badge = document.getElementById('botStatusBadge');
                isRunning = data.is_running;
                if (data.is_running) {
                    badge.className = 'status-badge status-running';
                    badge.innerText = 'SCANNER RUNNING';
                    document.getElementById('btnStartStop').innerText = 'Pause Scanner';
                    document.getElementById('btnStartStop').className = 'btn-red';
                } else {
                    badge.className = 'status-badge status-stopped';
                    badge.innerText = 'ENGINE PAUSED';
                    document.getElementById('btnStartStop').innerText = 'Start Scanner';
                    document.getElementById('btnStartStop').className = 'btn-green';
                }

                // Equity & PnL (includes open-position unrealized PnL)
                document.getElementById('lblBalance').innerText = '$' + (data.equity ?? data.balance).toFixed(2);
                const pnlEl = document.getElementById('lblPnL');
                const sign = data.total_pnl >= 0 ? '+' : '';
                pnlEl.innerText = `${sign}$${data.total_pnl.toFixed(2)} (${sign}${data.pnl_pct.toFixed(1)}%) | WR: ${data.win_rate}%`;
                pnlEl.className = data.total_pnl >= 0 ? 'metric-sub val-positive' : 'metric-sub val-negative';

                // Symbol & Ticker
                document.getElementById('lblActiveSymbol').innerText = data.active_symbol;
                document.getElementById('selSymbol').value = data.active_symbol;
                if (data.ticker) {
                    document.getElementById('lblLivePrice').innerText = '$' + formatPrice(data.ticker.last);
                    document.getElementById('lbl24hRange').innerText = `24h High: $${formatPrice(data.ticker.high24h)} | Low: $${formatPrice(data.ticker.low24h)}`;
                }

                // Execution mode is reported, never selected by the browser; credentials remain server-side.
                const isDemoMode = data.execution_mode === 'okx_demo';
                const modeText = isDemoMode
                    ? `OKX DEMO${data.demo_orders_armed ? ' • ARMED' : ' • DISARMED'}`
                    : 'PAPER SIMULATION';
                document.getElementById('lblExecMode').innerText = modeText;
                const demoStatus = document.getElementById('demoExecutionStatus');
                if (isDemoMode) {
                    demoStatus.innerText = `${data.demo_preflight_status || 'Demo preflight not checked.'} ` +
                        `Order arm: ${data.demo_orders_armed ? 'ON (demo only)' : 'OFF'}.` +
                        `${data.demo_halted ? ' DEMO EXECUTION HALTED; reconcile before entries.' : ''}` +
                        `${data.demo_external_position ? ' An untracked exchange position is present.' : ''}`;
                } else {
                    demoStatus.innerText = 'No OKX demo credentials detected. This process is paper simulation only; no exchange order can be sent.';
                }
                document.getElementById('tgConfigStatus').innerText = data.telegram_status ||
                    (data.telegram_configured ? 'Telegram alerts configured on server.' : 'Telegram alerts not configured on server.');
                const controlsEnabled = Boolean(data.dashboard_controls_enabled);
                document.getElementById('controlStatus').innerText = controlsEnabled
                    ? 'Controls enabled behind dashboard password authentication.'
                    : 'Read-only: set DASHBOARD_PASSWORD on the server to enable controls.';
                ['btnStartStop', 'btnTestAlert', 'inputLeverage', 'inputRisk']
                    .forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !controlsEnabled; });
                document.getElementById('selSymbol').disabled = true;
                document.getElementById('selStrategy').disabled = true;
                document.getElementById('selMinConf').disabled = true;
                document.getElementById('btnClosePosition').disabled = !controlsEnabled || !data.open_position;
                document.getElementById('btnReset').disabled = !controlsEnabled || isDemoMode || Boolean(data.open_position);

                // 1H Trend & Funding
                if (data.multi_1h_trend && data.multi_1h_trend[data.active_symbol]) {
                    document.getElementById('lbl1HTrend').innerText = data.multi_1h_trend[data.active_symbol];
                }
                if (data.multi_funding && data.multi_funding[data.active_symbol] !== undefined) {
                    const fr = (data.multi_funding[data.active_symbol] * 100).toFixed(4);
                    document.getElementById('lblFundingRate').innerText = (fr >= 0 ? '+' : '') + fr + '%';
                }

                // Regime & Strategy
                document.getElementById('lblRegime').innerText = data.market_regime;
                document.getElementById('lblMinConf').innerText = data.min_confluence_score;
                document.getElementById('selMinConf').value = data.min_confluence_score.toString();
                document.getElementById('selStrategy').value = data.active_strategy;
                document.getElementById('inputLeverage').value = data.leverage;
                document.getElementById('inputRisk').value = data.risk_pct;

                // Original trigger / VWAP-band / RSI pillars.
                const confluence = data.current_confluence_summary || {};
                const pillarLines = Array.isArray(confluence.confirmations) ? confluence.confirmations : [];
                const needed = Number(data.required_confluence || 2);
                const session = data.asian_session ? 'Asian UTC 22:00–06:00' : 'regular session';
                const adxValue = data.indicators && data.indicators.adx !== null && data.indicators.adx !== undefined
                    ? Number(data.indicators.adx) : NaN;
                const adxText = Number.isFinite(adxValue) ? adxValue.toFixed(2) : 'unavailable';
                document.getElementById('pillarStatus').innerText =
                    `Signal: ${confluence.direction || 'NEUTRAL'} | same-side count: ${confluence.confluence_score || 0}/3 | required: ${needed}/3 (${session})\n` +
                    `${pillarLines.length ? pillarLines.map(x => '✓ ' + x).join('\n') : 'No active pillar confirmations.'}\n` +
                    `5m ADX-14: ${adxText} (informational only; not an entry gate)`;

                // These are the same 5m inputs used by the three-pillar signal rules.
                if (data.indicators && data.indicators.vwap) {
                    document.getElementById('indVWAP').innerText = '$' + formatPrice(data.indicators.vwap);
                    document.getElementById('indVWAPUpper').innerText = '$' + formatPrice(data.indicators.vwap_upper);
                    document.getElementById('indVWAPLower').innerText = '$' + formatPrice(data.indicators.vwap_lower);
                    document.getElementById('indEMA20').innerText = '$' + formatPrice(data.indicators.ema20);
                    document.getElementById('indEMA50').innerText = '$' + formatPrice(data.indicators.ema50);
                    document.getElementById('indRSI').innerText = formatPrice(data.indicators.rsi);
                }

                // Position
                const posBox = document.getElementById('activePositionBox');
                if (data.open_position) {
                    const pos = data.open_position;
                    const sideClass = pos.side === 'LONG' ? 'tag-long' : 'tag-short';
                    const pnlClass = pos.unrealized_pnl >= 0 ? 'val-positive' : 'val-negative';
                    posBox.innerHTML = `
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:10px;">
                            <div><span class="metric-sub">Contract</span><br><strong>${pos.symbol}</strong> <span class="${sideClass}">${pos.side}</span></div>
                            <div><span class="metric-sub">Entry Price</span><br><strong>$${formatPrice(pos.entry_price)}</strong></div>
                            <div><span class="metric-sub">Current Price</span><br><strong>$${formatPrice(pos.current_price)}</strong></div>
                            <div><span class="metric-sub">ATR Stop Loss</span><br><strong class="val-negative">$${formatPrice(pos.sl_price)}</strong></div>
                            <div><span class="metric-sub">TP1 Target</span><br><strong class="val-positive">$${formatPrice(pos.tp1_price)}</strong> ${pos.tp1_hit ? '✅ (SL BE)' : ''}</div>
                            <div><span class="metric-sub">Unrealized PnL</span><br><strong class="${pnlClass}">${Number(pos.unrealized_pnl || 0) >= 0 ? '+' : ''}$${Number(pos.unrealized_pnl || 0).toFixed(2)}</strong></div>
                            <div><span class="metric-sub">Execution</span><br><strong>${pos.execution_mode === 'okx_demo' ? 'OKX DEMO' : 'PAPER SIMULATION'}</strong></div>
                            <div><span class="metric-sub">Contracts / margin</span><br><strong>${formatPrice(pos.contracts || pos.remaining_contracts || 0)} / $${formatPrice(pos.margin || 0)}</strong></div>
                        </div>
                    `;
                } else {
                    posBox.innerHTML = `<p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px 0;">No position open. BTC-USDT-SWAP is the only configured instrument.</p>`;
                }

                // Daily risk guard and three-pillar candidate tiers
                const riskState = data.daily_loss_pause ? `PAUSED: ${data.daily_pause_reason}` : 'Entry gate clear';
                document.getElementById('dailyRiskStatus').innerText =
                    `${riskState} | ${Number(data.daily_drawdown_pct || 0).toFixed(2)}% / ${Number(data.max_daily_drawdown_pct || 0).toFixed(1)}% drawdown | ` +
                    `${data.consecutive_losses}/${data.max_consecutive_losses} consecutive losses (Lagos day ${data.daily_date})`;
                const candidates = data.confluence_candidates || [];
                const c2 = candidates.filter(c => Number(c.score) === 2);
                const c3 = candidates.filter(c => Number(c.score) === 3);
                document.getElementById('candidateSummary').innerText =
                    `2/3 watch-only: ${c2.length} | 3/3 setups: ${c3.length} | ` +
                    `${candidates.filter(c => c.eligible).length} pass all active gates`;
                const candidateBody = document.getElementById('confluenceCandidatesBody');
                if (candidates.length) {
                    candidateBody.innerHTML = candidates.map(c => `
                        <tr>
                            <td>${escapeHtml(c.symbol)}</td>
                            <td><span class="${c.side === 'LONG' ? 'tag-long' : 'tag-short'}">${escapeHtml(c.side)}</span></td>
                            <td><span class="conf-badge">${escapeHtml(c.tier)}</span></td>
                            <td>${c.eligible ? 'PASS' : 'WATCH / BLOCKED'}</td>
                            <td>${escapeHtml((c.eligible ? (c.confirmations || []) : (c.block_reasons || [])).join('; '))}</td>
                        </tr>`).join('');
                } else {
                    candidateBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No 2/3-or-better directional watch candidate at this scan.</td></tr>`;
                }

                // Signals Feed
                const sigBody = document.getElementById('signalsTableBody');
                if (data.signals && data.signals.length > 0) {
                    sigBody.innerHTML = data.signals.map(s => `
                        <tr>
                            <td>${escapeHtml(s.time)}</td>
                            <td><strong>${escapeHtml(s.symbol)}</strong></td>
                            <td><span class="${s.side === 'LONG' ? 'tag-long' : 'tag-short'}">${escapeHtml(s.side)}</span></td>
                            <td><span class="conf-badge">${escapeHtml(`${s.confluence_score}/3 pillars`)}</span></td>
                            <td>$${formatPrice(s.entry)}</td>
                            <td>$${formatPrice(s.sl)}</td>
                            <td>$${formatPrice(s.tp1)}</td>
                            <td>$${formatPrice(s.tp2)}</td>
                        </tr>
                    `).join('');
                } else {
                    sigBody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-muted);">Waiting for confirmed BTC-USDT-SWAP three-pillar setups...</td></tr>`;
                }

                // Closed Trades
                const tradesBody = document.getElementById('closedTradesBody');
                if (data.closed_trades && data.closed_trades.length > 0) {
                    tradesBody.innerHTML = data.closed_trades.map(t => `
                        <tr>
                            <td>${escapeHtml(t.exit_time)}</td>
                            <td><strong>${escapeHtml(t.symbol)}</strong></td>
                            <td><span class="${t.side === 'LONG' ? 'tag-long' : 'tag-short'}">${escapeHtml(t.side)}</span></td>
                            <td>${escapeHtml(t.strategy)}</td>
                            <td>$${formatPrice(t.entry_price)}</td>
                            <td>$${formatPrice(t.exit_price)}</td>
                            <td>$${Number(t.fees || 0).toFixed(2)}</td>
                            <td>$${Number(t.funding_cashflow_usd || 0).toFixed(4)}</td>
                            <td>$${Number(t.slippage_est_usd || 0).toFixed(4)}</td>
                            <td class="${t.net_pnl >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl >= 0 ? '+' : ''}$${Number(t.net_pnl || 0).toFixed(2)}</td>
                            <td class="${t.net_pnl >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl >= 0 ? '+' : ''}${Number(t.net_pnl_pct || 0)}%</td>
                            <td>${escapeHtml(t.close_reason)}</td>
                        </tr>
                    `).join('');
                } else {
                    tradesBody.innerHTML = `<tr><td colspan="12" style="text-align:center; color:var(--text-muted);">No closed trades yet.</td></tr>`;
                }

                // Logs
                if (data.logs) {
                    const consoleEl = document.getElementById('logConsole');
                    consoleEl.textContent = data.logs.join('\\n');
                }


            } catch (err) {
                console.error("Error fetching status:", err);
            }
        }

        async function readApiMessage(res) {
            const data = await res.json().catch(() => ({}));
            return { data, message: data.error || data.message || (res.ok ? '' : `Request failed (${res.status})`) };
        }

        async function toggleBot() {
            try {
                const endpoint = isRunning ? '/api/stop' : '/api/start';
                const res = await fetch(endpoint, { method: 'POST' });
                if (!res.ok) {
                    const out = await readApiMessage(res);
                    alert(out.message);
                }
                fetchStatus();
            } catch (err) { alert(`Control request failed: ${err.message}`); }
        }

        async function updateConfig() {
            const body = {
                symbol: 'BTC-USDT-SWAP',
                strategy: 'playbook_3pillar',
                min_confluence_score: 3,
                leverage: parseInt(document.getElementById('inputLeverage').value),
                risk_pct: parseFloat(document.getElementById('inputRisk').value)
            };
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!res.ok) {
                    const out = await readApiMessage(res);
                    alert(out.message);
                }
                fetchStatus();
            } catch (err) { alert(`Configuration update failed: ${err.message}`); }
        }

        async function testAlert(platform) {
            try {
                const res = await fetch(`/api/test_alert/${platform}`, { method: 'POST' });
                const out = await readApiMessage(res);
                alert(out.message);
                fetchStatus();
            } catch (err) { alert(`Test alert failed: ${err.message}`); }
        }

        async function closePositionMarket() {
            try {
                const res = await fetch('/api/close_position', { method: 'POST' });
                const out = await readApiMessage(res);
                alert(out.message);
                fetchStatus();
            } catch (err) { alert(`Close request failed: ${err.message}`); }
        }

        async function resetAccount() {
            const amount = prompt("Enter paper-ledger starting balance ($):", "1000");
            if (amount === null) return;
            const num = parseFloat(amount);
            if (!Number.isFinite(num) || num <= 0) {
                alert('Enter a positive starting balance.');
                return;
            }
            try {
                const res = await fetch('/api/reset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ initial_balance: num })
                });
                const out = await readApiMessage(res);
                if (!res.ok) alert(out.message);
                else alert(out.message || 'Paper ledger reset.');
                fetchStatus();
            } catch (err) { alert(`Reset failed: ${err.message}`); }
        }

        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def status():
    data = bot.get_status()
    data["dashboard_controls_enabled"] = bool(os.environ.get("DASHBOARD_PASSWORD", ""))
    return jsonify(data)

@app.route('/api/start', methods=['POST'])
def start_bot():
    bot.start()
    return jsonify({"status": "started"})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    bot.stop()
    return jsonify({"status": "stopped"})

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.get_json(silent=True) or {}
    if data.get("symbol", "BTC-USDT-SWAP") != "BTC-USDT-SWAP":
        return jsonify({"error": "This approved bot is fixed to BTC-USDT-SWAP."}), 400
    if data.get("strategy", "playbook_3pillar") != "playbook_3pillar":
        return jsonify({"error": "Only the original three-pillar BTC strategy is enabled."}), 400
    try:
        min_conf = int(data.get("min_confluence_score", 3))
        leverage = int(data.get("leverage", bot.leverage))
        risk = float(data.get("risk_pct", bot.risk_pct))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric setting."}), 400
    if min_conf != 3:
        return jsonify({"error": "The entry threshold is fixed at 3/3 pillars in every session."}), 400
    if not 1 <= leverage <= 10:
        return jsonify({"error": "Leverage must be between 1× and the approved 10× cap."}), 400
    if not 0.1 <= risk <= 1.0:
        return jsonify({"error": "Planned risk must be between 0.1% and the approved 1.0% maximum."}), 400
    if bot.open_position is not None:
        return jsonify({"error": "Settings cannot be changed while a position is open."}), 409

    bot.active_symbol = "BTC-USDT-SWAP"
    bot.active_strategy = "playbook_3pillar"
    bot.min_confluence_score = 3
    bot.leverage = leverage
    bot.risk_pct = risk
    bot.add_log("Settings updated: BTC-USDT-SWAP three-pillar strategy (3/3 every session), %dx cap, %.1f%% planned risk." %
                (bot.leverage, bot.risk_pct))
    return jsonify({"status": "updated"})

@app.route('/api/bybit_config', methods=['POST'])
def disabled_legacy_exchange_config():
    return jsonify({"error": "No Bybit/Binance connector is implemented; this project is restricted to OKX demo-only execution."}), 403

@app.route('/api/notifications_config', methods=['POST'])
def notifications_config():
    # Secrets are loaded from the server environment and can never be changed/read via this endpoint.
    data = request.json or {}
    bot.enable_telegram = bool(data.get("enable_telegram", bot.enable_telegram))
    return jsonify({"status": "saved", "telegram_configured": bool(bot.telegram_token and bot.telegram_chat_id)})

@app.route('/api/test_alert/<platform>', methods=['POST'])
def test_alert(platform):
    if platform == 'telegram':
        mode = "OKX DEMO (test alert only; no order)" if bot.execution_mode == "okx_demo" else "PAPER SIMULATION"
        ok, res_msg = bot.send_telegram_alert(
            f"🧪 *TEST ALERT ONLY — NO ORDER PLACED*\n\n"
            f"Instrument: `BTC-USDT-SWAP`\n"
            f"Example rule: `3 of 3 pillars required in every session`\n"
            f"Example pillars: setup trigger, VWAP-band location, RSI momentum (illustration only)\n"
            f"Execution mode: `{mode}`\n"
            f"Illustrative price: `${bot.format_price(bot.ticker_data.get('last', 0.0))}`\n\n"
            f"This is a connectivity test, not a live signal or evidence of strategy performance."
        )
        return jsonify({"success": ok, "message": res_msg})
    return jsonify({"success": False, "message": "Unknown platform."}), 404

@app.route('/api/manual_trade', methods=['POST'])
def manual_trade():
    return jsonify({"success": False, "message": "Manual orders are disabled; no order was placed."}), 403

@app.route('/api/close_position', methods=['POST'])
def close_position():
    ok, message = bot.close_position_market()
    if not ok:
        return jsonify({"success": False, "message": message}), 409
    return jsonify({"success": True, "message": message})

@app.route('/api/reset', methods=['POST'])
def reset():
    data = request.get_json(silent=True) or {}
    try:
        new_bal = float(data.get("initial_balance", 1000.0))
        if not 0.01 <= new_bal <= 1_000_000:
            raise ValueError("Balance must be between $0.01 and $1,000,000.")
        bot.reset_account(new_bal)
    except (TypeError, ValueError) as exc:
        status_code = 409 if "while a position is open" in str(exc) or "while OKX demo mode" in str(exc) else 400
        return jsonify({"error": str(exc)}), status_code
    return jsonify({"status": "paper ledger reset", "message": "Paper ledger reset. No exchange action was sent."})

if __name__ == '__main__':
    bot.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", "5000")), threaded=True)
