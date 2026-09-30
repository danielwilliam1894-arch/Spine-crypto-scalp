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
                <h1>🛡️ 10-Coin Multi-Strategy Scalp Bot (@Spine_Scalp_bot)</h1>
            </div>
            <div>
                <span id="botStatusBadge" class="status-badge status-running">10-COIN LIVE SCANNER</span>
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
                <div class="metric-sub">Focus Contract Price (<span id="lblActiveSymbol">BTC-USDT-SWAP</span>)</div>
                <div id="lblLivePrice" class="metric-value val-highlight">$0.00</div>
                <div id="lbl24hRange" class="metric-sub">24h High: $0 | Low: $0</div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Detected Market State</div>
                <div id="lblRegime" class="metric-value" style="font-size:1.05rem; color:var(--accent-yellow);">↔ RANGING (Consolidation)</div>
                <div class="metric-sub">ADX (14) Trend Index: <span id="lblADX">18.5</span></div>
            </div>

            <div class="card" style="margin-bottom:0;">
                <div class="metric-sub">Multi-Coin Scanner</div>
                <div id="lblActiveStrategy" class="metric-value" style="font-size:1.1rem; color:var(--accent-purple);">10 Futures Pairs Active</div>
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
                        <p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px 0;">No active position open. Scanning 10 crypto futures contracts continuously...</p>
                    </div>
                </div>

                <!-- Live Indicators -->
                <div class="card">
                    <h2>📈 Focus Contract Matrix (5m Candle Scan)</h2>
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
                    <h2>🚨 Confluence Signal Alerts Feed (10 Coins)</h2>
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
                                <tr><td colspan="8" style="text-align:center; color:var(--text-muted);">Scanning for multi-strategy confluence setups across 10 coins...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Side: Controls & Notifications -->
            <div>
                <!-- Strategy Controls -->
                <div class="card">
                    <h2>🎮 Focus Contract Settings</h2>
                    
                    <div class="form-group">
                        <label>Primary Focus Contract</label>
                        <select id="selSymbol" onchange="updateConfig()">
                            <option value="BTC-USDT-SWAP">BTC-USDT-SWAP (Bitcoin)</option>
                            <option value="ETH-USDT-SWAP">ETH-USDT-SWAP (Ethereum)</option>
                            <option value="SOL-USDT-SWAP">SOL-USDT-SWAP (Solana)</option>
                            <option value="DOGE-USDT-SWAP">DOGE-USDT-SWAP (Dogecoin)</option>
                            <option value="XRP-USDT-SWAP">XRP-USDT-SWAP (Ripple)</option>
                            <option value="BNB-USDT-SWAP">BNB-USDT-SWAP (Binance Coin)</option>
                            <option value="AVAX-USDT-SWAP">AVAX-USDT-SWAP (Avalanche)</option>
                            <option value="NEAR-USDT-SWAP">NEAR-USDT-SWAP (Near Protocol)</option>
                            <option value="SUI-USDT-SWAP">SUI-USDT-SWAP (Sui Network)</option>
                            <option value="LINK-USDT-SWAP">LINK-USDT-SWAP (Chainlink)</option>
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
                            <option value="2">At least 2 Strategies Must Agree (2/3 & 3/3 Alerts Active)</option>
                            <option value="3">At least 3 Strategies Must Agree (3/3 Ultra Conservative)</option>
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

                    <h3 style="font-size:0.85rem; color:var(--text-muted); margin-top:16px; margin-bottom:8px;">Manual Confluence Signal Test</h3>
                    <div class="btn-group">
                        <button class="btn-green" style="flex:1;" onclick="triggerManualTrade('LONG')">BUY / LONG</button>
                        <button class="btn-red" style="flex:1;" onclick="triggerManualTrade('SHORT')">SELL / SHORT</button>
                    </div>
                </div>

                <!-- Phone / Messaging Push Notifications Card -->
                <div class="card">
                    <h2>📱 Telegram Chatbot Integration (@Spine_Scalp_bot)</h2>
                    <p style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">Your Telegram Token is active! Send <strong>/start</strong> or <strong>/scan</strong> to <strong>@Spine_Scalp_bot</strong> on Telegram!</p>
                    
                    <div class="form-group">
                        <label>Telegram Bot Token</label>
                        <input type="text" id="tgToken" value="8688574893:AAHbPFTSmu-MPfOpuk7SXfNokIC4SdNGwBU" onchange="saveNotifications()">
                    </div>

                    <div class="form-group">
                        <label>Telegram Chat ID</label>
                        <input type="text" id="tgChatId" value="7410039577" onchange="saveNotifications()">
                    </div>

                    <div class="btn-group">
                        <button class="btn-blue" style="flex:1; font-size:0.8rem;" onclick="testAlert('telegram')">Test Telegram Push Alert</button>
                    </div>
                </div>

                <!-- Execution Output Console -->
                <div class="card">
                    <h2>📝 Execution Output Console</h2>
                    <div id="logConsole" class="log-box">
                        Initializing 10-coin live feed...
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

        function formatPrice(val) {
            if (val === null || val === undefined) return '0.00';
            let v = parseFloat(val);
            if (Math.abs(v) < 1.0) return v.toFixed(4);
            if (Math.abs(v) < 100.0) return v.toFixed(3);
            return v.toFixed(2);
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const badge = document.getElementById('botStatusBadge');
                isRunning = data.is_running;
                if (data.is_running) {
                    badge.className = 'status-badge status-running';
                    badge.innerText = '10-COIN LIVE SCANNER';
                    document.getElementById('btnStartStop').innerText = 'Pause Engine';
                    document.getElementById('btnStartStop').className = 'btn-red';
                } else {
                    badge.className = 'status-badge status-stopped';
                    badge.innerText = 'ENGINE PAUSED';
                    document.getElementById('btnStartStop').innerText = 'Start Engine';
                    document.getElementById('btnStartStop').className = 'btn-green';
                }

                // Balance & PnL
                document.getElementById('lblBalance').innerText = '$' + data.balance.toFixed(2);
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

                // Regime & Strategy
                document.getElementById('lblRegime').innerText = data.market_regime;
                document.getElementById('lblActiveStrategy').innerText = data.active_strategy === 'multi_confluence' ? '10 Futures Pairs Active' : data.active_strategy;
                document.getElementById('lblMinConf').innerText = data.min_confluence_score;
                document.getElementById('selMinConf').value = data.min_confluence_score.toString();
                document.getElementById('selStrategy').value = data.active_strategy;
                document.getElementById('inputLeverage').value = data.leverage;
                document.getElementById('inputRisk').value = data.risk_pct;

                // Indicators
                if (data.indicators && data.indicators.vwap) {
                    document.getElementById('indVWAP').innerText = '$' + formatPrice(data.indicators.vwap);
                    document.getElementById('indVWAPUpper').innerText = '$' + formatPrice(data.indicators.vwap_upper);
                    document.getElementById('indVWAPLower').innerText = '$' + formatPrice(data.indicators.vwap_lower);
                    document.getElementById('indEMA20').innerText = '$' + formatPrice(data.indicators.ema20);
                    document.getElementById('indEMA50').innerText = '$' + formatPrice(data.indicators.ema50);
                    document.getElementById('indRSI').innerText = data.indicators.rsi.toFixed(1);
                    document.getElementById('lblADX').innerText = data.indicators.adx.toFixed(1);
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
                            <div><span class="metric-sub">Stop Loss</span><br><strong class="val-negative">$${formatPrice(pos.sl_price)}</strong></div>
                            <div><span class="metric-sub">TP1 Target</span><br><strong class="val-positive">$${formatPrice(pos.tp1_price)}</strong> ${pos.tp1_hit ? '✅ (SL BE)' : ''}</div>
                            <div><span class="metric-sub">Unrealized PnL</span><br><strong class="${pnlClass}">${pos.unrealized_pnl >= 0 ? '+' : ''}$${pos.unrealized_pnl.toFixed(2)}</strong></div>
                        </div>
                    `;
                } else {
                    posBox.innerHTML = `<p style="color:var(--text-muted); font-size:0.9rem; text-align:center; padding:20px 0;">No active position open. Scanning 10 crypto futures contracts continuously...</p>`;
                }

                // Signals Feed
                const sigBody = document.getElementById('signalsTableBody');
                if (data.signals && data.signals.length > 0) {
                    sigBody.innerHTML = data.signals.map(s => `
                        <tr>
                            <td>${s.time}</td>
                            <td><strong>${s.symbol}</strong></td>
                            <td><span class="${s.side === 'LONG' ? 'tag-long' : 'tag-short'}">${s.side}</span></td>
                            <td><span class="conf-badge">${s.confluence_score >= 3 ? '🛡️ 3/3 MAX' : '⚡ 2/3 MOD'}</span></td>
                            <td>$${formatPrice(s.entry)}</td>
                            <td>$${formatPrice(s.sl)}</td>
                            <td>$${formatPrice(s.tp1)}</td>
                            <td>$${formatPrice(s.tp2)}</td>
                        </tr>
                    `).join('');
                } else {
                    sigBody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-muted);">Scanning for multi-strategy confluence setups across 10 coins...</td></tr>`;
                }

                // Closed Trades
                const tradesBody = document.getElementById('closedTradesBody');
                if (data.closed_trades && data.closed_trades.length > 0) {
                    tradesBody.innerHTML = data.closed_trades.map(t => `
                        <tr>
                            <td>${t.exit_time}</td>
                            <td><strong>${t.symbol}</strong></td>
                            <td><span class="${t.side === 'LONG' ? 'tag-long' : 'tag-short'}">${t.side}</span></td>
                            <td>${t.strategy}</td>
                            <td>$${formatPrice(t.entry_price)}</td>
                            <td>$${formatPrice(t.exit_price)}</td>
                            <td>$${t.fees.toFixed(2)}</td>
                            <td class="${t.net_pnl >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl >= 0 ? '+' : ''}$${t.net_pnl.toFixed(2)}</td>
                            <td class="${t.net_pnl >= 0 ? 'val-positive' : 'val-negative'}">${t.net_pnl >= 0 ? '+' : ''}${t.net_pnl_pct}%</td>
                            <td>${t.close_reason}</td>
                        </tr>
                    `).join('');
                } else {
                    tradesBody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">No closed trades yet.</td></tr>`;
                }

                // Logs
                if (data.logs) {
                    const consoleEl = document.getElementById('logConsole');
                    consoleEl.innerHTML = data.logs.join('<br>');
                }

                if (data.telegram_token) document.getElementById('tgToken').value = data.telegram_token;
                if (data.telegram_chat_id) document.getElementById('tgChatId').value = data.telegram_chat_id;

            } catch (err) {
                console.error("Error fetching status:", err);
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
                telegram_token: document.getElementById('tgToken').value,
                telegram_chat_id: document.getElementById('tgChatId').value,
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
        "symbol": bot.active_symbol,
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
            f"💵 Entry: `${bot.format_price(test_signal['entry'])}`\n"
            f"🛑 SL: `${bot.format_price(test_signal['sl'])}`\n"
            f"🎯 TP1: `${bot.format_price(test_signal['tp1'])}`"
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
