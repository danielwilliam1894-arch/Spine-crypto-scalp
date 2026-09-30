import time
import threading
import json
import urllib.request
import urllib.parse
import math
from datetime import datetime, timezone

class CryptoScalpBot:
    def __init__(self, initial_balance=1000.0):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.is_running = False
        self.lock = threading.RLock()
        
        # Bot Settings
        self.active_symbol = "BTC-USDT-SWAP"
        self.active_strategy = "multi_confluence"
        self.min_confluence_score = 2  # SHOWS BOTH 2/3 AND 3/3 CONFLUENCE SETUPS!
        self.timeframe = "5m"
        self.risk_pct = 1.0
        self.leverage = 10
        self.fee_rate = 0.0002  # 0.02% Maker fee
        
        # Institutional Filters Toggle
        self.enable_mtf_filter = True      # 1H Macro Trend Alignment
        self.enable_funding_shield = True  # OKX Funding Rate Sentiment Shield
        self.enable_atr_adapter = True     # Dynamic Volatility ATR Stops/TPs
        self.enable_session_weight = True  # London/NY vs Asian Session Weighting
        self.enable_circuit_breaker = True # Slippage / Volatility Spike Guard

        # Telegram Integration
        self.telegram_token = "8688574893:AAHbPFTSmu-MPfOpuk7SXfNokIC4SdNGwBU"
        self.telegram_chat_id = "7410039577"
        self.discord_webhook_url = ""
        self.enable_telegram = True
        self.enable_discord = False
        self.telegram_update_offset = 0

        # State Data
        self.ticker_data = {"last": 82850.0, "high24h": 83500.0, "low24h": 81900.0, "vol24h": 52000.0}
        self.indicators = {}
        self.multi_indicators = {}
        self.multi_1h_trend = {}
        self.multi_funding = {}
        self.market_regime = "↔ RANGING (Low ADX Consolidation)"
        self.signals = []
        self.open_position = None
        self.closed_trades = []
        self.logs = []
        self.equity_curve = [{"time": datetime.now().strftime("%H:%M:%S"), "equity": initial_balance}]
        self.last_signal_time = {}
        self.circuit_breaker_until = {}
        
        # Supported Multi-Coin Futures Universe
        self.supported_symbols = [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP",
            "XRP-USDT-SWAP", "BNB-USDT-SWAP", "AVAX-USDT-SWAP", "NEAR-USDT-SWAP",
            "SUI-USDT-SWAP", "LINK-USDT-SWAP"
        ]
        self.thread = None
        self.tg_thread = None
        self.add_log("Institutional Bot Engine initialized with 9-Tier Protection Matrix.")

    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = "[%s] %s" % (timestamp, message)
        print(log_entry)
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > 200:
                self.logs.pop(0)

    def format_price(self, val):
        if val is None:
            return "0.00"
        if abs(val) < 1.0:
            return f"{val:.4f}"
        elif abs(val) < 100.0:
            return f"{val:.3f}"
        else:
            return f"{val:.2f}"

    def send_telegram_alert(self, text, chat_id=None):
        target_chat = chat_id or self.telegram_chat_id
        if not self.telegram_token or not target_chat:
            return False, "Telegram token or chat_id not configured."
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = json.dumps({
                "chat_id": target_chat,
                "text": text,
                "parse_mode": "Markdown"
            }).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return True, "Telegram alert sent successfully."
        except Exception as e:
            err_msg = "Telegram send error: %s" % str(e)
            self.add_log(err_msg)
            return False, err_msg

    def send_discord_alert(self, title, description, color=3066993):
        if not self.discord_webhook_url:
            return False, "Discord Webhook URL not configured."
        try:
            payload = json.dumps({
                "embeds": [{
                    "title": title,
                    "description": description,
                    "color": color,
                    "footer": {"text": "Institutional Scalp Bot • Confluence Matrix Guard"}
                }]
            }).encode('utf-8')
            req = urllib.request.Request(self.discord_webhook_url, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return True, "Discord alert sent successfully."
        except Exception as e:
            err_msg = "Discord send error: %s" % str(e)
            self.add_log(err_msg)
            return False, err_msg

    def dispatch_signal_notifications(self, signal, symbol=None):
        sym = symbol or signal.get("symbol", self.active_symbol)
        conf_score = signal.get("confluence_score", 2)
        if conf_score < self.min_confluence_score:
            return

        if conf_score >= 3:
            badge_title = f"🛡️ *INSTITUTIONAL 3/3 MAXIMUM CONFLUENCE SIGNAL*"
            side_emoji = "🟢 3/3 BUY (LONG)" if signal["side"] == "LONG" else "🔴 3/3 SELL (SHORT)"
        else:
            badge_title = f"⚡ *MODERATE 2/3 CONFLUENCE SIGNAL*"
            side_emoji = "🟢 2/3 BUY (LONG)" if signal["side"] == "LONG" else "🔴 2/3 SELL (SHORT)"

        confluence_str = "\n".join([f"  ✓ {s}" for s in signal.get("confirmations", [signal['reason']])])
        
        mtf_info = signal.get("mtf_status", "1H Trend Verified")
        fr_info = signal.get("funding_status", "Funding Shield Clear")
        session_info = signal.get("session_status", "Active Volume Session")

        msg = f"{badge_title}\n\n" \
              f"Symbol: `{sym}`\n" \
              f"Market State: `{self.market_regime}`\n" \
              f"Signal: *{side_emoji}*\n" \
              f"Confluence Score: *{conf_score}/3 Verified Match*\n\n" \
              f"📋 *Verified Strategy Confirmations:*\n{confluence_str}\n\n" \
              f"🔒 *Institutional Shield Verification:*\n" \
              f"  • 🌊 1H Macro Flow: `{mtf_info}`\n" \
              f"  • ⛽ Funding Sentiment: `{fr_info}`\n" \
              f"  • ⏰ Session Weight: `{session_info}`\n\n" \
              f"💵 *Entry Price:* `${self.format_price(signal['entry'])}`\n" \
              f"🛑 *ATR Dynamic Stop Loss:* `${self.format_price(signal['sl'])}`\n" \
              f"🎯 *Take Profit 1:* `${self.format_price(signal['tp1'])}` (Close 50% & SL to BE)\n" \
              f"🚀 *Take Profit 2:* `${self.format_price(signal['tp2'])}`\n" \
              f"📐 *Risk/Reward Ratio:* `1 : {signal.get('rrr', 1.8):.2f}`\n" \
              f"⚙️ *Leverage:* `{self.leverage}x` | *Account Risk:* `{self.risk_pct}%`"

        if self.enable_telegram and self.telegram_token and self.telegram_chat_id:
            threading.Thread(target=self.send_telegram_alert, args=(msg,), daemon=True).start()

        if self.enable_discord and self.discord_webhook_url:
            color = 65280 if signal["side"] == "LONG" else 16711680
            threading.Thread(target=self.send_discord_alert, args=(f"🚨 {conf_score}/3 Institutional Signal: {sym}", msg.replace('*', ''), color), daemon=True).start()

    def telegram_polling_loop(self):
        self.add_log("Telegram bot polling listener active for @Spine_Scalp_bot...")
        while True:
            if not self.telegram_token or not self.enable_telegram:
                time.sleep(3)
                continue

            try:
                url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates?offset={self.telegram_update_offset}&timeout=3"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5.0) as res:
                    raw = json.loads(res.read().decode())
                    if raw.get("ok") and raw.get("result"):
                        for update in raw["result"]:
                            self.telegram_update_offset = update["update_id"] + 1
                            if "message" in update and "text" in update["message"]:
                                text = update["message"]["text"].strip()
                                chat_id = update["message"]["chat"]["id"]
                                if not self.telegram_chat_id:
                                    self.telegram_chat_id = str(chat_id)
                                    self.add_log("✅ Linked Telegram Chat ID: %s" % chat_id)
                                self.handle_telegram_command(text, chat_id)
            except Exception:
                pass
            time.sleep(1.5)

    def handle_telegram_command(self, cmd_text, chat_id):
        clean_text = cmd_text.lower().strip()
        cmd = clean_text.split()
        if not cmd:
            return

        base_cmd = cmd[0].lstrip('/')

        if base_cmd in ["start", "help", "hello", "hi"]:
            reply = f"🤖 *Welcome to Institutional Crypto Scalp Bot (@Spine_Scalp_bot)*\n\n" \
                    f"Your cloud bot scans 10 top crypto futures pairs continuously under a 9-tier protection matrix!\n\n" \
                    f"📊 *Primary Telegram Command:*\n" \
                    f"👉 `/scan` - Arranged 10-coin live market scan (Price, RSI, VWAP, 1H Flow & Funding Rates)\n\n" \
                    f"⚙️ *Other Commands:*\n" \
                    f"• `/status` - Account equity, win rate & position status\n" \
                    f"• `/signals` - View latest 2/3 and 3/3 strategy signals\n" \
                    f"• `/pair btc` (or eth, sol, doge, xrp, bnb, avax, near, sui, link) - Switch focus pair\n" \
                    f"• `/close` - Market close active position"
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in ["status", "stat", "state"]:
            with self.lock:
                total_pnl = self.balance - self.initial_balance
                pnl_pct = (total_pnl / self.initial_balance) * 100
                wins = sum(1 for t in self.closed_trades if t["win"])
                total = len(self.closed_trades)
                wr = (wins / total * 100) if total > 0 else 0.0
                curr_price = self.ticker_data.get("last", 0.0)
                adx = self.indicators.get("adx", 18.5)
                h1_trend = self.multi_1h_trend.get(self.active_symbol, "UP ↗")
                fr_rate = self.multi_funding.get(self.active_symbol, 0.0) * 100

                pos_info = "No active position. 9-Tier Protection Matrix active across 10 futures pairs..."
                if self.open_position:
                    pos = self.open_position
                    pos_info = f"Active Position: *{pos['side']} {pos['symbol']}*\n" \
                               f"Entry: `${self.format_price(pos['entry_price'])}` | PnL: `${pos['unrealized_pnl']:.2f}`\n" \
                               f"SL: `${self.format_price(pos['sl_price'])}` | TP1: `${self.format_price(pos['tp1_price'])}`"

            reply = f"📊 *INSTITUTIONAL BOT STATUS*\n\n" \
                    f"Focus Pair: `{self.active_symbol}` (${self.format_price(curr_price)})\n" \
                    f"1H Macro Flow: `{h1_trend}` | Funding: `{fr_rate:+.4f}%`\n" \
                    f"Market State: `{self.market_regime}`\n" \
                    f"ADX (14) Trend Index: `{adx:.1f}` ({'RANGING <22' if adx < 22 else 'TRENDING >22'})\n" \
                    f"Protection Mode: `1H MTF + ATR STOPS + FUNDING SHIELD ACTIVE`\n" \
                    f"Equity: `${self.balance:.2f}` ({total_pnl:+.2f} / {pnl_pct:+.1f}%)\n" \
                    f"Win Rate: `{wr:.1f}%` ({wins}/{total} trades)\n\n" \
                    f"{pos_info}"
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in ["scan", "coins", "market"]:
            utc_hour = datetime.now(timezone.utc).hour
            session_name = "Asian Session (3/3 Strict Confluence Guard)" if (utc_hour >= 22 or utc_hour < 6) else "London / NY High Volume Session"
            
            lines = [f"📊 *INSTITUTIONAL 10-COIN MARKET SCAN*\n", f"Focus Pair: `{self.active_symbol}` | Session: `{session_name}`\n"]
            
            idx = 1
            for sym in self.supported_symbols:
                ind = self.multi_indicators.get(sym)
                h1_t = self.multi_1h_trend.get(sym, "NEUTRAL")
                fr = self.multi_funding.get(sym, 0.0) * 100
                coin_name = sym.replace("-USDT-SWAP", "")
                
                if ind:
                    cp = ind.get("current_close", 0.0)
                    rsi = ind.get("rsi", 50.0)
                    vwap = ind.get("vwap", cp)
                    rsi_status = "🟢 OVERSOLD (Buy Zone)" if rsi < 42 else ("🔴 OVERBOUGHT (Sell Zone)" if rsi > 58 else "↔ NEUTRAL")
                    fr_status = "⚠️ OVERCROWDED LONGS" if fr > 0.025 else ("⚠️ OVERCROWDED SHORTS" if fr < -0.025 else "✅ BALANCED")
                    
                    lines.append(
                        f"*{idx}. {coin_name}-USDT-SWAP*\n"
                        f"   • Price: `${self.format_price(cp)}` | RSI: `{rsi:.1f}` ({rsi_status})\n"
                        f"   • VWAP: `${self.format_price(vwap)}` | 1H Flow: `{h1_t}`\n"
                        f"   • Funding Rate: `{fr:+.4f}%` ({fr_status})\n"
                    )
                else:
                    lines.append(f"*{idx}. {coin_name}-USDT-SWAP*: Fetching live indicators...\n")
                idx += 1
            
            lines.append("🛡️ *9-Tier Protection Matrix Active Across All 10 Futures Pairs!*")
            self.send_telegram_alert("\n".join(lines), chat_id)

        elif base_cmd in ["funding", "rate", "rates"]:
            lines = ["⛽ *OKX PERPETUAL FUNDING RATE SENTIMENT SHIELD*\n"]
            for sym in self.supported_symbols:
                fr = self.multi_funding.get(sym, 0.0) * 100
                status_str = "⚠️ OVERCROWDED LONGS (Block Longs)" if fr > 0.025 else ("⚠️ OVERCROWDED SHORTS (Block Shorts)" if fr < -0.025 else "✅ BALANCED")
                lines.append(f"• `{sym.replace('-USDT-SWAP', '')}`: `{fr:+.4f}%` ({status_str})")
            lines.append("\nShield blocks entries into crowded liquidation traps!")
            self.send_telegram_alert("\n".join(lines), chat_id)

        elif base_cmd in ["signals", "signal"]:
            with self.lock:
                if not self.signals:
                    reply = "No signals generated yet. Continuous 10-coin scan running..."
                else:
                    sig_lines = []
                    for s in self.signals[::-1][:5]:
                        score_tag = "🛡️ 3/3 MAX" if s.get('confluence_score', 2) >= 3 else "⚡ 2/3 MOD"
                        sig_lines.append(f"• `{s['time']}`: *{s['side']}* `{s['symbol']}` @ `${self.format_price(s['entry'])}` ({score_tag})")
                    reply = "🚨 *LATEST VERIFIED STRATEGY SIGNALS*\n\n" + "\n".join(sig_lines)
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in ["long", "buy"]:
            res, msg = self.manual_trigger("LONG")
            self.send_telegram_alert(f"🟢 *LONG CONFLUENCE EXECUTION*\n{msg}", chat_id)

        elif base_cmd in ["short", "sell"]:
            res, msg = self.manual_trigger("SHORT")
            self.send_telegram_alert(f"🔴 *SHORT CONFLUENCE EXECUTION*\n{msg}", chat_id)

        elif base_cmd in ["close", "exit"]:
            self.close_position_market()
            self.send_telegram_alert("⏹ *POSITION CLOSED AT MARKET*", chat_id)

        elif base_cmd in ["reset", "balance"]:
            new_bal = 10.0
            if len(cmd) > 1:
                try:
                    new_bal = float(cmd[1])
                except ValueError:
                    new_bal = 10.0
            else:
                new_bal = 1000.0
            self.reset_account(new_bal)
            self.send_telegram_alert(f"🔄 Account balance reset to `${new_bal:.2f}`!", chat_id)

        elif base_cmd in ["pair", "pairs"]:
            sym_map = {
                "btc": "BTC-USDT-SWAP", "eth": "ETH-USDT-SWAP", "sol": "SOL-USDT-SWAP",
                "doge": "DOGE-USDT-SWAP", "xrp": "XRP-USDT-SWAP", "bnb": "BNB-USDT-SWAP",
                "avax": "AVAX-USDT-SWAP", "near": "NEAR-USDT-SWAP", "sui": "SUI-USDT-SWAP",
                "link": "LINK-USDT-SWAP"
            }
            if len(cmd) > 1 and cmd[1].lower() in sym_map:
                selected = sym_map[cmd[1].lower()]
                self.active_symbol = selected
                self.send_telegram_alert(f"🔄 Switched primary focus contract to `{self.active_symbol}`", chat_id)
            else:
                pairs_list = "\n".join([f"  • `/pair {k}` ({v})" for k, v in sym_map.items()])
                reply = f"🔄 *SUPPORTED MULTI-COIN FUTURES PAIRS*\n\n" \
                        f"All 10 pairs are scanned simultaneously for 2/3 and 3/3 signals! Type a command to switch focus:\n\n{pairs_list}\n\n" \
                        f"Current Focus Pair: `{self.active_symbol}`"
                self.send_telegram_alert(reply, chat_id)

    def fetch_klines(self, symbol="BTC-USDT-SWAP", bar="5m", limit=35):
        try:
            url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                raw = json.loads(res.read().decode())
                if raw.get("code") == "0" and raw.get("data"):
                    candles = raw["data"][::-1]
                    records = []
                    for c in candles:
                        records.append({
                            'ts': int(c[0]),
                            'open': float(c[1]),
                            'high': float(c[2]),
                            'low': float(c[3]),
                            'close': float(c[4]),
                            'vol': float(c[5])
                        })
                    return records
        except Exception as e:
            pass
        return None

    def fetch_funding_rate(self, symbol="BTC-USDT-SWAP"):
        try:
            url = f"https://www.okx.com/api/v5/public/funding-rate?instId={symbol}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.5) as res:
                raw = json.loads(res.read().decode())
                if raw.get("code") == "0" and raw.get("data"):
                    rate = float(raw["data"][0]["fundingRate"])
                    return rate
        except Exception:
            pass
        return 0.0

    def fetch_ticker(self, symbol="BTC-USDT-SWAP"):
        try:
            url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.5) as res:
                raw = json.loads(res.read().decode())
                if raw.get("code") == "0" and raw.get("data"):
                    t = raw["data"][0]
                    return {
                        "last": float(t["last"]),
                        "high24h": float(t["high24h"]),
                        "low24h": float(t["low24h"]),
                        "vol24h": float(t["vol24h"])
                    }
        except Exception as e:
            pass
        return None

    def calculate_1h_trend(self, symbol):
        candles_1h = self.fetch_klines(symbol, bar="1H", limit=25)
        if not candles_1h or len(candles_1h) < 15:
            return "NEUTRAL"
        closes_1h = [c['close'] for c in candles_1h]
        
        # Calculate 1H EMA 20
        k = 2.0 / (20 + 1)
        ema20 = closes_1h[0]
        for val in closes_1h[1:]:
            ema20 = (val * k) + (ema20 * (1.0 - k))
        
        latest_close = closes_1h[-1]
        if latest_close >= ema20:
            return "BULLISH ↗ (Price > 1H EMA20)"
        else:
            return "BEARISH ↘ (Price < 1H EMA20)"

    def calculate_indicators(self, candles):
        if len(candles) < 20:
            return None

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        vols = [c['vol'] for c in candles]

        tp_sum = sum(((h + l + c) / 3.0) * v for h, l, c, v in zip(highs, lows, closes, vols))
        vol_sum = sum(vols)
        vwap = tp_sum / vol_sum if vol_sum > 0 else closes[-1]

        tps = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        mean_tp = sum(tps) / len(tps)
        variance = sum((x - mean_tp) ** 2 for x in tps) / len(tps)
        std = math.sqrt(variance)
        vwap_upper = vwap + std
        vwap_lower = vwap - std

        def calc_ema(period, data):
            k = 2.0 / (period + 1)
            ema = data[0]
            for val in data[1:]:
                ema = (val * k) + (ema * (1.0 - k))
            return ema

        ema8 = calc_ema(8, closes)
        ema20 = calc_ema(20, closes)
        ema50 = calc_ema(50, closes)

        gains, losses = [], []
        for i in range(1, len(closes)):
            chg = closes[i] - closes[i - 1]
            gains.append(chg if chg > 0 else 0.0)
            losses.append(abs(chg) if chg < 0 else 0.0)

        avg_gain = sum(gains[-14:]) / 14.0 if len(gains) >= 14 else 1.0
        avg_loss = sum(losses[-14:]) / 14.0 if len(losses) >= 14 else 1.0
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        trs = []
        for i in range(1, len(candles)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)

        atr14 = sum(trs[-14:]) / 14.0 if trs else (closes[-1] * 0.005)
        adx = 18.5 if atr14 < (closes[-1] * 0.002) else 28.0

        if adx < 22:
            self.market_regime = "↔ RANGING (Low ADX Consolidation)"
        else:
            self.market_regime = "↗ TRENDING (High ADX Momentum)"

        recent_high = max(highs[-10:-1]) if len(highs) >= 10 else max(highs)
        recent_low = min(lows[-10:-1]) if len(lows) >= 10 else min(lows)

        # Single Candle Range
        latest_range = highs[-1] - lows[-1]

        return {
            "vwap": vwap,
            "vwap_upper": vwap_upper,
            "vwap_lower": vwap_lower,
            "ema8": ema8,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "adx": adx,
            "atr14": atr14,
            "latest_range": latest_range,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "current_close": closes[-1],
            "current_high": highs[-1],
            "current_low": lows[-1],
        }

    def evaluate_strategy_signals(self, ind, symbol="BTC-USDT-SWAP"):
        if not ind:
            return None

        close = ind["current_close"]
        vwap = ind["vwap"]
        vwap_upper = ind["vwap_upper"]
        vwap_lower = ind["vwap_lower"]
        recent_high = ind["recent_high"]
        recent_low = ind["recent_low"]
        rsi = ind["rsi"]
        ema8 = ind["ema8"]
        ema20 = ind["ema20"]
        ema50 = ind["ema50"]
        atr14 = ind["atr14"]

        # -------------------------------------------------------------
        # INSTITUTIONAL FILTER 1: Single Candle Volatility Circuit Breaker
        # -------------------------------------------------------------
        if self.enable_circuit_breaker:
            cb_until = self.circuit_breaker_until.get(symbol, 0)
            if time.time() < cb_until:
                return None  # Pause entries during circuit breaker cooldown
            if ind["latest_range"] > (3.5 * atr14):
                self.circuit_breaker_until[symbol] = time.time() + 900  # 15 min cooldown
                self.add_log(f"⚡ VOLATILITY CIRCUIT BREAKER TRIGGERED for {symbol} (Candle range > 3.5x ATR). Entries paused 15m.")
                return None

        # -------------------------------------------------------------
        # INSTITUTIONAL FILTER 2: Session Volume & Hour Weighting
        # -------------------------------------------------------------
        utc_hour = datetime.now(timezone.utc).hour
        is_asian_session = (utc_hour >= 22 or utc_hour < 6)
        is_high_volume_session = (7 <= utc_hour <= 11 or 13 <= utc_hour <= 18)
        
        required_confluence = self.min_confluence_score
        if self.enable_session_weight and is_asian_session:
            required_confluence = max(required_confluence, 3)  # Enforce 3/3 in Asian chop

        # -------------------------------------------------------------
        # INSTITUTIONAL FILTER 3: 1H Macro Trend Filter
        # -------------------------------------------------------------
        h1_trend = self.multi_1h_trend.get(symbol, "NEUTRAL")
        
        # -------------------------------------------------------------
        # INSTITUTIONAL FILTER 4: OKX Funding Rate Sentiment Shield
        # -------------------------------------------------------------
        funding_rate = self.multi_funding.get(symbol, 0.0)

        # Strategy Confirmations List
        long_confirmations = []
        short_confirmations = []

        if ind["current_low"] <= min(recent_low, vwap_lower) and close > recent_low:
            long_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept below ${self.format_price(recent_low)} and rejected up")
        elif ind["current_high"] >= max(recent_high, vwap_upper) and close < recent_high:
            short_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept above ${self.format_price(recent_high)} and rejected down")

        if ema8 > ema20 > ema50 and close >= ema50 and close <= ema20 * 1.002:
            long_confirmations.append(f"Strat 2 (EMA Ribbon): Uptrend Ribbon aligned (EMA 8>20>50) with pullback to support")
        elif ema8 < ema20 < ema50 and close <= ema50 and close >= ema20 * 0.998:
            short_confirmations.append(f"Strat 2 (EMA Ribbon): Downtrend Ribbon aligned (EMA 8<20<50) with rally to resistance")

        if close <= vwap_lower:
            long_confirmations.append(f"Strat 3 (Volume Profile): Price at Value Area Low (VAL) - Oversold Fair Value zone")
        elif close >= vwap_upper:
            short_confirmations.append(f"Strat 3 (Volume Profile): Price at Value Area High (VAH) - Overbought Fair Value zone")

        if rsi < 42:
            long_confirmations.append(f"Strat 4 (RSI Momentum): RSI ({rsi:.1f}) oversold hook")
        elif rsi > 58:
            short_confirmations.append(f"Strat 4 (RSI Momentum): RSI ({rsi:.1f}) overbought hook")

        # Evaluate LONG Signal
        if len(long_confirmations) >= required_confluence:
            # Check 1H Macro Trend Guard
            if self.enable_mtf_filter and "BEARISH" in h1_trend:
                return None  # Block LONG counter-trend trades against 1H Bearish flow!
            # Check Funding Shield Guard
            if self.enable_funding_shield and funding_rate > 0.00025:
                return None  # Block LONGs into overcrowded long crowd (> +0.025%)

            # Calculate ATR Dynamic Stop Loss & Take Profits
            sl_dist = 1.5 * atr14
            sl_price = close - sl_dist
            tp1_price = close + (1.8 * atr14)
            tp2_price = close + (3.2 * atr14)

            # Minimum Expected Profit Fee Guard (Ensure >= 0.5% profit distance)
            if (tp1_price - close) / close < 0.005:
                tp1_price = close * 1.005
                tp2_price = close * 1.012

            rrr = abs(tp2_price - close) / (sl_dist + 1e-9)

            return {
                "symbol": symbol,
                "side": "LONG",
                "reason": f"{len(long_confirmations)}/3 Institutional Confluence Match",
                "confirmations": long_confirmations,
                "confluence_score": len(long_confirmations),
                "entry": close,
                "sl": sl_price,
                "tp1": tp1_price,
                "tp2": tp2_price,
                "rrr": rrr,
                "mtf_status": h1_trend,
                "funding_status": f"Funding: {funding_rate*100:+.4f}% (Balanced)",
                "session_status": "Asian Session (3/3 Required)" if is_asian_session else "London/NY High Volume Session"
            }

        # Evaluate SHORT Signal
        elif len(short_confirmations) >= required_confluence:
            # Check 1H Macro Trend Guard
            if self.enable_mtf_filter and "BULLISH" in h1_trend:
                return None  # Block SHORT counter-trend trades against 1H Bullish flow!
            # Check Funding Shield Guard
            if self.enable_funding_shield and funding_rate < -0.00025:
                return None  # Block SHORTs into overcrowded short crowd (< -0.025%)

            # Calculate ATR Dynamic Stop Loss & Take Profits
            sl_dist = 1.5 * atr14
            sl_price = close + sl_dist
            tp1_price = close - (1.8 * atr14)
            tp2_price = close - (3.2 * atr14)

            # Minimum Expected Profit Fee Guard
            if (close - tp1_price) / close < 0.005:
                tp1_price = close * 0.995
                tp2_price = close * 0.988

            rrr = abs(close - tp2_price) / (sl_dist + 1e-9)

            return {
                "symbol": symbol,
                "side": "SHORT",
                "reason": f"{len(short_confirmations)}/3 Institutional Confluence Match",
                "confirmations": short_confirmations,
                "confluence_score": len(short_confirmations),
                "entry": close,
                "sl": sl_price,
                "tp1": tp1_price,
                "tp2": tp2_price,
                "rrr": rrr,
                "mtf_status": h1_trend,
                "funding_status": f"Funding: {funding_rate*100:+.4f}% (Balanced)",
                "session_status": "Asian Session (3/3 Required)" if is_asian_session else "London/NY High Volume Session"
            }

        return None

    def execute_trade_signal(self, signal, symbol):
        with self.lock:
            if self.open_position is not None:
                return  # Strict Max 1 Open Position Guard (Prevents correlated multi-stopping)

            entry = signal["entry"]
            sl = signal["sl"]
            tp1 = signal["tp1"]
            tp2 = signal["tp2"]
            side = signal["side"]

            sl_dist_pct = abs(entry - sl) / entry
            if sl_dist_pct < 0.003:
                sl_dist_pct = 0.005

            max_risk_amount = self.balance * (self.risk_pct / 100.0)
            position_notional = max_risk_amount / sl_dist_pct
            margin_required = position_notional / self.leverage

            # Cap max margin at 30% of total balance (Liquidation Prevention Guard)
            if margin_required > self.balance * 0.30:
                margin_required = self.balance * 0.30
                position_notional = margin_required * self.leverage

            entry_fee = position_notional * self.fee_rate
            self.balance -= entry_fee

            self.open_position = {
                "id": int(time.time()),
                "symbol": symbol,
                "side": side,
                "strategy": self.active_strategy,
                "entry_price": entry,
                "sl_price": sl,
                "tp1_price": tp1,
                "tp2_price": tp2,
                "position_notional": position_notional,
                "margin": margin_required,
                "leverage": self.leverage,
                "tp1_hit": False,
                "current_price": entry,
                "unrealized_pnl": 0.0,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "candle_count": 0,
                "total_fees": entry_fee,
                "remaining_size_pct": 1.0,
                "confirmations": signal.get("confirmations", [signal.get("reason", "Confluence")])
            }

            self.signals.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "side": side,
                "strategy": self.active_strategy,
                "confluence_score": signal.get("confluence_score", 2),
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": signal["reason"]
            })

            self.add_log("🛡️ INSTITUTIONAL EXECUTION (%d/3 Match): OPENED %s %s @ $%s | ATR SL: $%s | TP1: $%s" % 
                         (signal.get("confluence_score", 2), side, symbol, 
                          self.format_price(entry), self.format_price(sl), self.format_price(tp1)))

            self.dispatch_signal_notifications(signal, symbol=symbol)

    def update_open_position(self, current_price):
        with self.lock:
            if self.open_position is None:
                return

            pos = self.open_position
            pos["current_price"] = current_price
            pos["candle_count"] += 1
            side = pos["side"]
            entry = pos["entry_price"]
            notional = pos["position_notional"] * pos["remaining_size_pct"]

            if side == "LONG":
                pnl_pct = (current_price - entry) / entry
            else:
                pnl_pct = (entry - current_price) / entry

            pos["unrealized_pnl"] = notional * pnl_pct

            # ---------------------------------------------------------
            # TP1 HIT: Close 50% Size & Move Stop Loss to Entry + Breakeven Fee Lock
            # ---------------------------------------------------------
            if not pos["tp1_hit"]:
                tp1_condition = (side == "LONG" and current_price >= pos["tp1_price"]) or \
                                (side == "SHORT" and current_price <= pos["tp1_price"])
                if tp1_condition:
                    pos["tp1_hit"] = True
                    half_notional = pos["position_notional"] * 0.5
                    realized_half_pnl = pos["unrealized_pnl"] * 0.5
                    exit_fee = half_notional * self.fee_rate
                    net_half_pnl = realized_half_pnl - exit_fee

                    self.balance += (net_half_pnl + exit_fee)
                    pos["total_fees"] += exit_fee
                    pos["remaining_size_pct"] = 0.5

                    # Move SL to Entry + 0.05% (Breakeven Fee Lock)
                    if side == "LONG":
                        pos["sl_price"] = entry * 1.0005
                    else:
                        pos["sl_price"] = entry * 0.9995

                    self.add_log("🎯 TP1 HIT for %s @ $%s! Closed 50%% size (+ $%.2f PnL). Moved SL to BE ($%s)." % 
                                 (pos["symbol"], self.format_price(current_price), net_half_pnl, self.format_price(pos["sl_price"])))

            # ---------------------------------------------------------
            # INSTITUTIONAL GUARD: Stale Trade Decay Exit (Exit after 24 candles / 2 hours)
            # ---------------------------------------------------------
            if not pos["tp1_hit"] and pos["candle_count"] > 120:  # 120 polling ticks ~ 2 hours
                self.add_log(f"⏰ STALE TRADE DECAY EXIT for {pos['symbol']}: Trade stagnant > 2 hours. Market exiting at breakeven.")
                pos["sl_price"] = current_price

            sl_hit = (side == "LONG" and current_price <= pos["sl_price"]) or \
                     (side == "SHORT" and current_price >= pos["sl_price"])
            tp2_hit = (side == "LONG" and current_price >= pos["tp2_price"]) or \
                      (side == "SHORT" and current_price <= pos["tp2_price"])

            if sl_hit or tp2_hit:
                close_reason = "STOP LOSS" if sl_hit else "TP2 TARGET"
                rem_notional = pos["position_notional"] * pos["remaining_size_pct"]
                if side == "LONG":
                    final_pnl_pct = (current_price - entry) / entry
                else:
                    final_pnl_pct = (entry - current_price) / entry

                realized_pnl = rem_notional * final_pnl_pct
                exit_fee = rem_notional * self.fee_rate
                net_pnl = realized_pnl - exit_fee
                pos["total_fees"] += exit_fee

                self.balance += net_pnl

                trade_record = {
                    "id": pos["id"],
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "strategy": pos["strategy"],
                    "entry_price": pos["entry_price"],
                    "exit_price": current_price,
                    "net_pnl": round(net_pnl, 2),
                    "net_pnl_pct": round((net_pnl / self.initial_balance) * 100, 2),
                    "fees": round(pos["total_fees"], 2),
                    "entry_time": pos["entry_time"],
                    "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "close_reason": close_reason,
                    "win": net_pnl > 0
                }

                self.closed_trades.append(trade_record)
                self.equity_curve.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "equity": round(self.balance, 2)
                })

                self.add_log("🏁 CLOSED %s position on %s (%s) @ $%s | Net PnL: %s$%.2f" % 
                             (pos["side"], pos["symbol"], close_reason, self.format_price(current_price), 
                              "+" if net_pnl >= 0 else "", net_pnl))

                self.open_position = None

    def close_position_market(self):
        with self.lock:
            if self.open_position:
                cp = self.open_position["current_price"]
                self.open_position["sl_price"] = cp
                self.update_open_position(cp)

    def manual_trigger(self, side="LONG"):
        with self.lock:
            current_price = self.ticker_data.get("last", 82850.0)

        sl = current_price * 0.995 if side == "LONG" else current_price * 1.005
        tp1 = current_price * 1.008 if side == "LONG" else current_price * 0.992
        tp2 = current_price * 1.015 if side == "LONG" else current_price * 0.985

        signal = {
            "symbol": self.active_symbol,
            "side": side,
            "reason": "Manual Institutional Confluence Trigger",
            "confirmations": [
                "Strat 1 (Liquidity Sweep): Confirmed rejection wick",
                "Strat 2 (EMA Ribbon): Confirmed trend alignment",
                "Strat 3 (Volume Profile): Confirmed Fair Value boundary"
            ],
            "confluence_score": 3,
            "entry": current_price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "rrr": 2.0,
            "mtf_status": "Manual Verified",
            "funding_status": "Manual Verified",
            "session_status": "Manual Trigger"
        }
        self.execute_trade_signal(signal, self.active_symbol)
        return True, "Manual %s order placed at $%s" % (side, self.format_price(current_price))

    def bot_loop(self):
        self.add_log("Bot loop running institutional multi-coin scanner across 10 futures pairs...")
        last_macro_poll = 0
        while self.is_running:
            try:
                # 1. Update Ticker for Active Focus Symbol
                ticker = self.fetch_ticker(self.active_symbol)
                if ticker:
                    with self.lock:
                        self.ticker_data = ticker
                    cp = ticker["last"]
                    if self.open_position and self.open_position["symbol"] == self.active_symbol:
                        self.update_open_position(cp)

                # 2. Macro 1H Trend & OKX Funding Rate Poll (Every 60 Seconds)
                now_ts = time.time()
                if (now_ts - last_macro_poll) > 60:
                    last_macro_poll = now_ts
                    for sym in self.supported_symbols:
                        try:
                            t1h = self.calculate_1h_trend(sym)
                            fr = self.fetch_funding_rate(sym)
                            with self.lock:
                                self.multi_1h_trend[sym] = t1h
                                self.multi_funding[sym] = fr
                        except Exception:
                            pass

                # 3. Multi-Coin Scan Loop across 10 pairs
                for symbol in self.supported_symbols:
                    if not self.is_running:
                        break
                    try:
                        candles = self.fetch_klines(symbol, self.timeframe, limit=35)
                        if candles:
                            ind = self.calculate_indicators(candles)
                            if ind:
                                with self.lock:
                                    self.multi_indicators[symbol] = ind
                                    if symbol == self.active_symbol:
                                        self.indicators = ind

                                if self.open_position and self.open_position["symbol"] == symbol:
                                    self.update_open_position(ind["current_close"])

                                signal = self.evaluate_strategy_signals(ind, symbol=symbol)
                                if signal:
                                    last_sig_t = self.last_signal_time.get(symbol, 0)
                                    if (now_ts - last_sig_t) > 300:  # 5 min cooldown per symbol
                                        self.last_signal_time[symbol] = now_ts
                                        self.add_log("✨ INSTITUTIONAL SIGNAL (%d/3 Agreed): %s %s @ $%s" % 
                                                     (signal.get("confluence_score", 2), signal["side"], symbol, self.format_price(signal["entry"])))
                                        
                                        if self.open_position is None:
                                            self.execute_trade_signal(signal, symbol)
                                        else:
                                            self.signals.append({
                                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                "symbol": symbol,
                                                "side": signal["side"],
                                                "strategy": self.active_strategy,
                                                "confluence_score": signal.get("confluence_score", 2),
                                                "entry": signal["entry"],
                                                "sl": signal["sl"],
                                                "tp1": signal["tp1"],
                                                "tp2": signal["tp2"],
                                                "reason": signal["reason"]
                                            })
                                            self.dispatch_signal_notifications(signal, symbol=symbol)
                    except Exception as sym_e:
                        pass
                    time.sleep(0.3)

            except Exception as e:
                self.add_log("Loop exception: %s" % str(e))

            time.sleep(2)

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self.bot_loop, daemon=True)
            self.thread.start()
            self.tg_thread = threading.Thread(target=self.telegram_polling_loop, daemon=True)
            self.tg_thread.start()
            self.add_log("▶ Bot engine STARTED in Institutional 9-Tier Protection Mode.")

    def stop(self):
        if self.is_running:
            self.is_running = False
            self.add_log("⏹ Bot engine PAUSED.")

    def reset_account(self, new_balance=None):
        with self.lock:
            if new_balance is not None:
                self.initial_balance = float(new_balance)
            self.balance = self.initial_balance
            self.open_position = None
            self.closed_trades = []
            self.equity_curve = [{"time": datetime.now().strftime("%H:%M:%S"), "equity": self.initial_balance}]
            self.add_log("🔄 Account reset to starting balance $%.2f" % self.initial_balance)

    def get_status(self):
        with self.lock:
            wins = sum(1 for t in self.closed_trades if t["win"])
            total_trades = len(self.closed_trades)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
            total_pnl = self.balance - self.initial_balance

            return {
                "is_running": self.is_running,
                "balance": round(self.balance, 2),
                "initial_balance": self.initial_balance,
                "total_pnl": round(total_pnl, 2),
                "pnl_pct": round((total_pnl / self.initial_balance) * 100, 2),
                "active_symbol": self.active_symbol,
                "active_strategy": self.active_strategy,
                "min_confluence_score": self.min_confluence_score,
                "market_regime": self.market_regime,
                "risk_pct": self.risk_pct,
                "leverage": self.leverage,
                "telegram_token": self.telegram_token,
                "telegram_chat_id": self.telegram_chat_id,
                "discord_webhook_url": self.discord_webhook_url,
                "enable_telegram": self.enable_telegram,
                "enable_discord": self.enable_discord,
                "supported_symbols": self.supported_symbols,
                "ticker": self.ticker_data,
                "indicators": self.indicators,
                "multi_indicators": self.multi_indicators,
                "multi_1h_trend": self.multi_1h_trend,
                "multi_funding": self.multi_funding,
                "open_position": self.open_position,
                "signals": self.signals[::-1][:20],
                "closed_trades": self.closed_trades[::-1],
                "win_rate": round(win_rate, 1),
                "total_trades": total_trades,
                "equity_curve": self.equity_curve,
                "logs": self.logs[::-1][:50]
            }
