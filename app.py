from flask import Flask, render_template_string, jsonify, request
from bot_engine import CryptoScalpBot

app = Flask(__name__)
bot = CryptoScalpBot(initial_balance=1000.0)
bot.start()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Multi-Strategy Confluence Crypto Trading Bot</title>
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
                <h1>🛡️ Multi-Strategy Trading Bot (@Spine_Scalp_bot)</h1>
            </div>
            <div>
                <span id="botStatusBadge" class="status-badge status-running">LIVE CONFLUENCE SCANNER</span>
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
                <div class="metric-sub">Live Contract Price (<span id="lblActiveSymbol">BTC-USDT-SWAP</span>)</div>
                <div id="lblLivePrice" class="metric-value val-highlight">$0.00</div>
                <div id="lbl24hRange" class="metric-sub">24h High: $0 | Low: $0</div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Detected Market State</div>
                <div id="lblRegime" class="metric-value" style="font-size:1.05rem; color:var(--accent-yellow);">↔ RANGING (Consolidation)</div>
                <div class="metric-sub">ADX (14) Trend Index: <span id="lblADX">18.5</span></div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Strategy Filter Mode</div>
                <div id="lblActiveStrategy" class="metric-value" style="font-size:1.1rem; color:var(--accent-purple);">Multi-Strategy Consensus</div>
                <div class="metric-sub">Min Confluence: <span id="lblMinConf">2</span>/3 Strategies</div>
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
                        <button class="btn-red" style="padding:4px 10px; font-size:0.75rem;" onclick="closePositionMarket()">Close Market</button>
                    </h2>
                    <div id="activePositionBox">
                        <p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px 0;">No active position open. Multi-strategy confluence scanner running...</p>
                    </div>
                </div>

                <!-- Live Indicators -->
                <div class="card">
                    <h2>📈 Verified Indicator Matrix (5m Candle Scan)</h2>
                    <div class="grid grid-3" style="gap:10px;">
                        <div style="background:var(--bg-card); padding:10px; border-radius:6px;">
                            <div class="metric-sub">Session VWAP</div>
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

                <!-- Signals History Table -->
                <div class="card">
                    <h2>🚨 Confluence Signal Alerts Feed</h2>
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
                                <tr><td colspan="8" style="text-align:center; color:var(--text-muted);">Scanning for multi-strategy confluence setups...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Side: Controls & Notifications -->
            <div>
                <!-- Strategy Controls -->
                <div class="card">
                    <h2>🎮 Verification Engine Settings</h2>
                    
                    <div class="form-group">
                        <label>Trading Contract</label>
                        <select id="selSymbol" onchange="updateConfig()">
                            <option value="BTC-USDT-SWAP">BTC-USDT-SWAP</option>
                            <option value="ETH-USDT-SWAP">ETH-USDT-SWAP</option>
                            <option value="SOL-USDT-SWAP">SOL-USDT-SWAP</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label>Strategy Verification Mode</label>
                        <select id="selStrategy" onchange="updateConfig()">
                            <option value="multi_confluence">🛡️ Multi-Strategy Consensus (Checks ALL Strategies)</option>
                            <option value="sweep_reversal">1. Liquidity Sweep & VWAP Reversal Only</option>
                            <option value="ema_ribbon">2. 5m/15m Trend EMA Ribbon Only</option>
                            <option value="profile_poc">3. Volume Profile POC Mean Reversion Only</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label>Min Confluence Threshold</label>
                        <select id="selMinConf" onchange="updateConfig()">
                            <option value="2">At least 2 Strategies Must Agree (High Probability)</option>
                            <option value="3">At least 3 Strategies Must Agree (Ultra Conservative)</option>
                        </select>
                    </div>

                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
                        <div class="form-group">
                            <label>Leverage (x)</label>
                            <input type="number" id="inputLeverage" value="10" min="1" max="50" onchange="updateConfig()">
                        </div>
                        <div class="form-group">
                            <label>Risk Per Trade (%)</label>
                            <input type="number" id="inputRisk" value="1.0" step="0.1" onchange="updateConfig()">
                        </div>
                    </div>

                    <div class="btn-group">
                        <button id="btnStartStop" class="btn-red" style="flex:1;" onclick="toggleBot()">Pause Engine</button>
                        <button class="btn-outline" onclick="resetAccount()">Reset Balance</button>
                    </div>

                    <h3 style="font-size:0.85rem; color:var(--text-muted); margin-top:16px; margin-bottom:8px;">Manual Confluence Signal Execution Test</h3>
                    <div class="btn-group">
                        <button class="btn-green" style="flex:1;" onclick="triggerManualTrade('LONG')">BUY / LONG</button>
                        <button class="btn-red" style="flex:1;" onclick="triggerManualTrade('SHORT')">SELL / SHORT</button>
                    </div>
                </div>

                <!-- Phone / Messaging Push Notifications Card -->
                <div class="card">
                    <h2>📱 Telegram Chatbot Integration (@Spine_Scalp_bot)</h2>
                    <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">Your Telegram Token is configured! Send <strong>/start</strong> to <strong>@Spine_Scalp_bot</strong> on Telegram to activate phone signals!</p>
                    
                    <div class="form-group">
                        <label>Telegram Bot Token</label>
                        <input type="text" id="tgToken" value="8688574893:AAHbPFTSmu-MPfOpuk7SXfNokIC4SdNGwBU" onchange="saveNotifications()">
                    </div>

                    <div class="form-group">
                        <label>Telegram Chat ID (Auto-captured when you message bot)</label>
                        <input type="text" id="tgChatId" placeholder="Auto-captured when you send /start" onchange="saveNotifications()">
                    </div>

                    <div class="btn-group">
                        <button class="btn-blue" style="flex:1; font-size:0.8rem;" onclick="testAlert('telegram')">Test Telegram Push Alert</button>
                    </div>
                </div>

                <!-- Execution Output Console -->
                <div class="card">
                    <h2>📝 Execution Output Console</h2>
                    <div id="logConsole" class="log-box">
                        Initializing live feed...
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
                            <th>Net PnL ($)</th>
                            <th>Net PnL (%)</th>
                            <th>Reason</th>
                        </tr>
                    </thead>
                    <tbody id="closedTradesBody">
                        <tr><td colspan="10" style="text-align:center; color:var(--text-muted);">No closed trades yet.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        let isRunning = true;

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const badge = document.getElementById('botStatusBadge');
                isRunning = data.is_running;
                if (data.is_running) {
                    badge.className = 'status-badge status-running';
                    badge.innerText = 'LIVE CONFLUENCE SCANNER';
                    document.getElementById('btnStartStop').innerText = 'Pause Engine';
                    document.getElementById('btnStartStop').className = 'btn-red';
                } else {
                    badge.className = 'status-badge status-stopped';
                    badge.innerText = 'ENGINE PAUSED';
                    document.getElementById('btnStartStop').innerText = 'Start Engine';
                    document.getElementById('btnStartStop').className = 'btn-green';
                }

                document.getElementById('lblBalance').innerText = `$${data.balance.toLocaleString('en-US', {minimumFractionDigits:2})}`;
                const pnlEl = document.getElementById('lblPnL');
                pnlEl.className = data.total_pnl >= 0 ? 'metric-sub val-positive' : 'metric-sub val-negative';
                pnlEl.innerText = `${data.total_pnl >= 0 ? '+' : ''}$${data.total_pnl.toFixed(2)} (${data.pnl_pct >= 0 ? '+' : ''}${data.pnl_pct}%)`;

                document.getElementById('lblActiveSymbol').innerText = data.active_symbol;
                document.getElementById('lblMinConf').innerText = data.min_confluence_score || 2;
                document.getElementById('lblRegime').innerText = data.market_regime || '↔ RANGING (Consolidation)';
                
                const stratNames = {
                    'multi_confluence': 'Multi-Strategy Consensus',
                    'sweep_reversal': 'Sweep Reversal',
                    'ema_ribbon': 'EMA Ribbon Trend',
                    'profile_poc': 'POC Mean Reversion'
                };
                document.getElementById('lblActiveStrategy').innerText = stratNames[data.active_strategy] || data.active_strategy;

                if (data.telegram_chat_id) {
                    document.getElementById('tgChatId').value = data.telegram_chat_id;
                }

                if (data.ticker && data.ticker.last) {
                    document.getElementById('lblLivePrice').innerText = `$${data.ticker.last.toLocaleString('en-US', {minimumFractionDigits:2})}`;
                    document.getElementById('lbl24hRange').innerText = `24h High: $${data.ticker.high24h.toLocaleString()} | Low: $${data.ticker.low24h.toLocaleString()}`;
                }

                if (data.indicators && data.indicators.vwap) {
                    document.getElementById('indVWAP').innerText = `$${data.indicators.vwap.toFixed(2)}`;
                    document.getElementById('indVWAPUpper').innerText = `$${data.indicators.vwap_upper.toFixed(2)}`;
                    document.getElementById('indVWAPLower').innerText = `$${data.indicators.vwap_lower.toFixed(2)}`;
                    document.getElementById('indEMA20').innerText = `$${data.indicators.ema20.toFixed(2)}`;
                    document.getElementById('indEMA50').innerText = `$${data.indicators.ema50.toFixed(2)}`;
                    document.getElementById('indRSI').innerText = `${data.indicators.rsi.toFixed(1)}`;
                    document.getElementById('lblADX').innerText = `${(data.indicators.adx || 18.5).toFixed(1)}`;
                }

                const posBox = document.getElementById('activePositionBox');
                if (data.open_position) {
                    const pos = data.open_position;
                    const pnlClass = pos.unrealized_pnl >= 0 ? 'val-positive' : 'val-negative';
                    
                    const confs = pos.confirmations ? pos.confirmations.map(c => `<li>✓ ${c}</li>`).join('') : '';

                    posBox.innerHTML = `
                        <div class="grid grid-3" style="gap:10px;">
                            <div>
                                <div class="metric-sub">Contract / Side</div>
                                <div style="font-weight:700;"><span class="${pos.side === 'LONG' ? 'tag-long' : 'tag-short'}">${pos.side}</span> ${pos.symbol} (${pos.leverage}x)</div>
                            </div>
                            <div>
                                <div class="metric-sub">Entry Price</div>
                                <div style="font-weight:700;">$${pos.entry_price.toLocaleString('en-US', {minimumFractionDigits:2})}</div>
                            </div>
                            <div>
                                <div class="metric-sub">Unrealized PnL</div>
                                <div class="${pnlClass}" style="font-weight:700; font-size:1.1rem;">${pos.unrealized_pnl >= 0 ? '+' : ''}$${pos.unrealized_pnl.toFixed(2)}</div>
                            </div>
                        </div>
                        <div class="grid grid-3" style="gap:10px; margin-top:12px; font-size:0.85rem;">
                            <div><strong>Stop Loss:</strong> $${pos.sl_price.toFixed(2)}</div>
                            <div><strong>TP1 (50%):</strong> $${pos.tp1_price.toFixed(2)} ${pos.tp1_hit ? '✅ HIT' : ''}</div>
                            <div><strong>TP2 (Target):</strong> $${pos.tp2_price.toFixed(2)}</div>
                        </div>
                        ${confs ? `<div style="margin-top:10px; background:var(--bg-card); padding:8px; border-radius:6px; font-size:0.8rem;"><strong>Verified Confirmations:</strong><ul style="padding-left:16px; color:#cbd5e1;">${confs}</ul></div>` : ''}
                    `;
                } else {
                    posBox.innerHTML = `<p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:15px 0;">No active position open. Multi-strategy confluence scanner running...</p>`;
                }

                const sigBody = document.getElementById('signalsTableBody');
                if (data.signals && data.signals.length > 0) {
                    sigBody.innerHTML = data.signals.map(s => `
                        <tr>
                            <td>${s.time}</td>
                            <td>${s.symbol}</td>
                            <td><span class="${s.side === 'LONG' ? 'tag-long' : 'tag-short'}">${s.side}</span></td>
                            <td><span class="conf-badge">${s.confluence_score || 2}/3 Agreed</span></td>
                            <td>$${s.entry.toFixed(2)}</td>
                            <td class="val-negative">$${s.sl.toFixed(2)}</td>
                            <td class="val-positive">$${s.tp1.toFixed(2)}</td>
                            <td class="val-positive">$${s.tp2.toFixed(2)}</td>
                        </tr>
                    `).join('');
                }

                const tbody = document.getElementById('closedTradesBody');
                if (data.closed_trades && data.closed_trades.length > 0) {
                    tbody.innerHTML = data.closed_trades.map(t => `
                        <tr>
                            <td>${t.exit_time}</td>
                            <td>${t.symbol}</td>
                            <td><span class="${t.side === 'LONG' ? 'tag-long' : 'tag-short'}">${t.side}</span></td>
                            <td>${t.strategy}</td>
                            <td>$${t.entry_price.toFixed(2)}</td>
                            <td>$${t.exit_price.toFixed(2)}</td>
                            <td>$${t.fees.toFixed(2)}</td>
                            <td class="${t.net_pnl >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl >= 0 ? '+' : ''}$${t.net_pnl.toFixed(2)}</td>
                            <td class="${t.net_pnl_pct >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl_pct >= 0 ? '+' : ''}${t.net_pnl_pct}%</td>
                            <td>${t.close_reason}</td>
                        </tr>
                    `).join('');
                } else {
                    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">No closed trades yet.</td></tr>`;
                }

                const logBox = document.getElementById('logConsole');
                if (data.logs) {
                    logBox.innerHTML = data.logs.join('<br>');
                }
            } catch (err) {
                console.error('Fetch status error:', err);
            }
        }

        async function toggleBot() {
            const endpoint = isRunning ? '/api/stop' : '/api/start';
            await fetch(endpoint, { method: 'POST' });
            fetchStatus();
        }

        async function updateConfig() {
            const body = {
                symbol: document.getElementById('selSymbol').value,
                strategy: document.getElementById('selStrategy').value,
                min_confluence_score: parseInt(document.getElementById('selMinConf').value),
                leverage: parseInt(document.getElementById('inputLeverage').value),
                risk_pct: parseFloat(document.getElementById('inputRisk').value)
            };
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            fetchStatus();
        }

        async function saveNotifications() {
            const body = {
                telegram_token: document.getElementById('tgToken').value.trim(),
                telegram_chat_id: document.getElementById('tgChatId').value.trim(),
                enable_telegram: true
            };
            await fetch('/api/notifications_config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
        }

        async function testAlert(platform) {
            await saveNotifications();
            const res = await fetch(`/api/test_alert/${platform}`, { method: 'POST' });
            const data = await res.json();
            alert(data.message);
            fetchStatus();
        }

        async function triggerManualTrade(side) {
            await fetch('/api/manual_trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ side: side })
            });
            fetchStatus();
        }

        async function closePositionMarket() {
            await fetch('/api/close_position', { method: 'POST' });
            fetchStatus();
        }

        async function resetAccount() {
            if (confirm("Reset account balance back to $1,000.00?")) {
                await fetch('/api/reset', { method: 'POST' });
                fetchStatus();
            }
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
    return jsonify(bot.get_status())

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
    data = request.json or {}
    if "symbol" in data:
        bot.active_symbol = data["symbol"]
    if "strategy" in data:
        bot.active_strategy = data["strategy"]
    if "min_confluence_score" in data:
        bot.min_confluence_score = int(data["min_confluence_score"])
    if "leverage" in data:
        bot.leverage = int(data["leverage"])
    if "risk_pct" in data:
        bot.risk_pct = float(data["risk_pct"])
    bot.add_log("Config updated: Symbol=%s, StrategyMode=%s, MinConfluence=%d, Leverage=%dx, Risk=%.1f%%" % 
                (bot.active_symbol, bot.active_strategy, bot.min_confluence_score, bot.leverage, bot.risk_pct))
    return jsonify({"status": "updated"})

@app.route('/api/notifications_config', methods=['POST'])
def notifications_config():
    data = request.json or {}
    bot.telegram_token = data.get("telegram_token", "8688574893:AAHbPFTSmu-MPfOpuk7SXfNokIC4SdNGwBU")
    bot.telegram_chat_id = data.get("telegram_chat_id", "")
    bot.enable_telegram = bool(data.get("enable_telegram", True))
    bot.add_log("Notification settings saved.")
    return jsonify({"status": "saved"})

@app.route('/api/test_alert/<platform>', methods=['POST'])
def test_alert(platform):
    test_signal = {
        "side": "LONG",
        "reason": "Test Multi-Strategy Confluence Alert",
        "confirmations": [
            "Strat 1 (Liquidity Sweep): Price swept below recent low",
            "Strat 2 (EMA Ribbon): Ribbon in strong uptrend alignment",
            "Strat 3 (Volume Profile): Price at Value Area Low (VAL)"
        ],
        "confluence_score": 3,
        "entry": bot.ticker_data.get("last", 82850.0),
        "sl": bot.ticker_data.get("last", 82850.0) * 0.995,
        "tp1": bot.ticker_data.get("last", 82850.0) * 1.008,
        "tp2": bot.ticker_data.get("last", 82850.0) * 1.015,
        "rrr": 2.0
    }
    if platform == 'telegram':
        ok, res_msg = bot.send_telegram_alert(
            f"🧪 *TEST MULTI-STRATEGY TELEGRAM ALERT*\n\n"
            f"Symbol: `{bot.active_symbol}`\n"
            f"Confluence Score: `3/3 Strategies Agreed`\n"
            f"✓ Liquidity Sweep Confirmed\n"
            f"✓ EMA Ribbon Trend Confirmed\n"
            f"✓ Volume Profile VAL Confirmed\n\n"
            f"💵 Entry: `${test_signal['entry']:.2f}`\n"
            f"🛑 SL: `${test_signal['sl']:.2f}`\n"
            f"🎯 TP1: `${test_signal['tp1']:.2f}`"
        )
        return jsonify({"success": ok, "message": res_msg})
    return jsonify({"success": False, "message": "Unknown platform"})

@app.route('/api/manual_trade', methods=['POST'])
def manual_trade():
    data = request.json or {}
    side = data.get("side", "LONG")
    success, msg = bot.manual_trigger(side)
    return jsonify({"success": success, "message": msg})

@app.route('/api/close_position', methods=['POST'])
def close_position():
    bot.close_position_market()
    return jsonify({"status": "position closed"})

@app.route('/api/reset', methods=['POST'])
def reset():
    bot.reset_account()
    return jsonify({"status": "account reset"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
