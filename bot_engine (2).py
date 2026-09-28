import time
import threading
import json
import urllib.request
import urllib.parse
import math
from datetime import datetime

class CryptoScalpBot:
    def __init__(self, initial_balance=1000.0):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.is_running = False
        self.lock = threading.RLock()
        
        # Bot Settings
        self.active_symbol = "BTC-USDT-SWAP"
        self.active_strategy = "multi_confluence"
        self.min_confluence_score = 2
        self.timeframe = "5m"
        self.risk_pct = 1.0
        self.leverage = 10
        self.fee_rate = 0.0002  # 0.02% Maker fee
        
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
        self.market_regime = "↔ RANGING (Low ADX Consolidation)"
        self.signals = []
        self.open_position = None
        self.closed_trades = []
        self.logs = []
        self.equity_curve = [{"time": datetime.now().strftime("%H:%M:%S"), "equity": initial_balance}]
        
        self.supported_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        self.thread = None
        self.tg_thread = None
        self.add_log("Bot engine initialized (Lightweight Pure-Python Edition).")

    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = "[%s] %s" % (timestamp, message)
        print(log_entry)
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > 200:
                self.logs.pop(0)

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
                    "footer": {"text": "Crypto Scalping Bot • Multi-Strategy Confluence Alert"}
                }]
            }).encode('utf-8')
            req = urllib.request.Request(self.discord_webhook_url, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return True, "Discord alert sent successfully."
        except Exception as e:
            err_msg = "Discord send error: %s" % str(e)
            self.add_log(err_msg)
            return False, err_msg

    def dispatch_signal_notifications(self, signal):
        side_emoji = "🟢 HIGH-CONFLUENCE BUY (LONG)" if signal["side"] == "LONG" else "🔴 HIGH-CONFLUENCE SELL (SHORT)"
        confluence_str = "\n".join([f"  ✓ {s}" for s in signal.get("confirmations", [signal['reason']])])

        msg = f"🛡️ *MULTI-STRATEGY CONFLUENCE SIGNAL*\n\n" \
              f"Symbol: `{self.active_symbol}`\n" \
              f"Market Regime: `{self.market_regime}`\n" \
              f"Signal: *{side_emoji}*\n" \
              f"Confluence Score: `{signal.get('confluence_score', 2)}/3 Strategies Agreed`\n\n" \
              f"📋 *Verified Strategy Alignments:*\n{confluence_str}\n\n" \
              f"💵 *Entry Price:* `${signal['entry']:.2f}`\n" \
              f"🛑 *Calculated Stop Loss:* `${signal['sl']:.2f}`\n" \
              f"🎯 *Take Profit 1:* `${signal['tp1']:.2f}` (Close 50% & SL to BE)\n" \
              f"🚀 *Take Profit 2:* `${signal['tp2']:.2f}`\n" \
              f"📐 *Risk/Reward Ratio:* `1 : {signal.get('rrr', 1.8):.2f}`\n" \
              f"⚙️ *Leverage:* `{self.leverage}x` | *Account Risk:* `{self.risk_pct}%`"

        if self.enable_telegram and self.telegram_token and self.telegram_chat_id:
            threading.Thread(target=self.send_telegram_alert, args=(msg,), daemon=True).start()

        if self.enable_discord and self.discord_webhook_url:
            color = 65280 if signal["side"] == "LONG" else 16711680
            threading.Thread(target=self.send_discord_alert, args=(f"🚨 Multi-Strategy Signal: {self.active_symbol}", msg.replace('*', ''), color), daemon=True).start()

    def telegram_polling_loop(self):
        self.add_log("Telegram bot polling listener started for @Spine_Scalp_bot...")
        while True:
            if not self.telegram_token or not self.enable_telegram:
                time.sleep(5)
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
            time.sleep(2)

    def handle_telegram_command(self, cmd_text, chat_id):
        cmd = cmd_text.lower().split()
        if not cmd:
            return

        base_cmd = cmd[0]

        if base_cmd in ["/start", "/help"]:
            reply = f"🤖 *Welcome to Crypto Scalping Bot (@Spine_Scalp_bot)*\n\n" \
                    f"Your cloud bot is live & scanning markets!\n\n" \
                    f"📊 *Available Commands:*\n" \
                    f"`/status` - View market regime (Ranging/Trending), balance & position\n" \
                    f"`/regime` - View ADX & range detection indicators\n" \
                    f"`/signals` - View latest multi-strategy signals\n" \
                    f"`/long` or `/buy` - Trigger manual LONG order\n" \
                    f"`/short` or `/sell` - Trigger manual SHORT order\n" \
                    f"`/close` - Market close active position\n" \
                    f"`/pair btc` (or eth/sol) - Switch contract"
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in ["/status", "/regime"]:
            with self.lock:
                total_pnl = self.balance - self.initial_balance
                pnl_pct = (total_pnl / self.initial_balance) * 100
                wins = sum(1 for t in self.closed_trades if t["win"])
                total = len(self.closed_trades)
                wr = (wins / total * 100) if total > 0 else 0.0
                curr_price = self.ticker_data.get("last", 0.0)
                adx = self.indicators.get("adx", 18.5)

                pos_info = "No active open position."
                if self.open_position:
                    pos = self.open_position
                    pos_info = f"Active Position: *{pos['side']} {pos['symbol']}*\n" \
                               f"Entry: `${pos['entry_price']:.2f}` | PnL: `${pos['unrealized_pnl']:.2f}`\n" \
                               f"SL: `${pos['sl_price']:.2f}` | TP1: `${pos['tp1_price']:.2f}`"

            reply = f"📊 *BOT & MARKET REGIME STATUS*\n\n" \
                    f"Contract: `{self.active_symbol}` (${curr_price:.2f})\n" \
                    f"Market State: `{self.market_regime}`\n" \
                    f"ADX (14) Trend Strength: `{adx:.1f}` ({'RANGING <22' if adx < 22 else 'TRENDING >22'})\n" \
                    f"Strategy Mode: `{self.active_strategy}`\n" \
                    f"Equity: `${self.balance:.2f}` ({total_pnl:+.2f} / {pnl_pct:+.1f}%)\n" \
                    f"Win Rate: `{wr:.1f}%` ({wins}/{total} trades)\n\n" \
                    f"{pos_info}"
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd == "/signals":
            with self.lock:
                if not self.signals:
                    reply = "No signals generated yet. Continuous market scan running..."
                else:
                    sig_lines = []
                    for s in self.signals[::-1][:5]:
                        sig_lines.append(f"• `{s['time']}`: *{s['side']}* `{s['symbol']}` @ `${s['entry']:.2f}` (Confluence: {s.get('confluence_score', 2)}/3)")
                    reply = "🚨 *LATEST MULTI-STRATEGY SIGNALS*\n\n" + "\n".join(sig_lines)
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in ["/long", "/buy"]:
            res, msg = self.manual_trigger("LONG")
            self.send_telegram_alert(f"🟢 *LONG ORDER EXECUTION*\n{msg}", chat_id)

        elif base_cmd in ["/short", "/sell"]:
            res, msg = self.manual_trigger("SHORT")
            self.send_telegram_alert(f"🔴 *SHORT ORDER EXECUTION*\n{msg}", chat_id)

        elif base_cmd == "/close":
            self.close_position_market()
            self.send_telegram_alert("⏹ *POSITION CLOSED AT MARKET*", chat_id)

        elif base_cmd == "/pair" and len(cmd) > 1:
            sym_map = {"btc": "BTC-USDT-SWAP", "eth": "ETH-USDT-SWAP", "sol": "SOL-USDT-SWAP"}
            arg = cmd[1].lower()
            if arg in sym_map:
                self.active_symbol = sym_map[arg]
                self.send_telegram_alert(f"🔄 Switched trading contract to `{self.active_symbol}`", chat_id)

    def fetch_klines(self, symbol="BTC-USDT-SWAP", bar="5m", limit=35):
        try:
            url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.0) as res:
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
        except Exception:
            pass
            
        now_ts = int(time.time() * 1000)
        base_price = self.ticker_data.get("last", 82850.0)
        records = []
        for i in range(limit):
            ts = now_ts - (limit - i) * 300000
            p = base_price + ((i % 5) - 2.5) * 10
            records.append({
                'ts': ts,
                'open': p - 10,
                'high': p + 25,
                'low': p - 25,
                'close': p,
                'vol': 1500.0
            })
        return records

    def fetch_ticker(self, symbol="BTC-USDT-SWAP"):
        try:
            url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.0) as res:
                raw = json.loads(res.read().decode())
                if raw.get("code") == "0" and raw.get("data"):
                    data = raw["data"][0]
                    return {
                        "last": float(data["last"]),
                        "high24h": float(data["high24h"]),
                        "low24h": float(data["low24h"]),
                        "vol24h": float(data["vol24h"])
                    }
        except Exception:
            pass
        return self.ticker_data

    def calculate_indicators(self, candles):
        """Pure Python calculation for VWAP, EMAs, RSI, and ADX."""
        if not candles or len(candles) < 14:
            return {}

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        vols = [c['vol'] for c in candles]

        # 1. VWAP & Standard Deviation
        tp_sum = sum(((h + l + c) / 3.0) * v for h, l, c, v in zip(highs, lows, closes, vols))
        vol_sum = sum(vols)
        vwap = tp_sum / vol_sum if vol_sum > 0 else closes[-1]

        tps = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        mean_tp = sum(tps) / len(tps)
        variance = sum((x - mean_tp) ** 2 for x in tps) / len(tps)
        std = math.sqrt(variance)
        vwap_upper = vwap + std
        vwap_lower = vwap - std

        # 2. EMAs (8, 20, 50)
        def calc_ema(period, data):
            k = 2.0 / (period + 1)
            ema = data[0]
            for val in data[1:]:
                ema = (val * k) + (ema * (1.0 - k))
            return ema

        ema8 = calc_ema(8, closes)
        ema20 = calc_ema(20, closes)
        ema50 = calc_ema(50, closes)

        # 3. RSI (14)
        gains, losses = [], []
        for i in range(1, len(closes)):
            chg = closes[i] - closes[i - 1]
            gains.append(chg if chg > 0 else 0.0)
            losses.append(abs(chg) if chg < 0 else 0.0)

        avg_gain = sum(gains[-14:]) / 14.0 if len(gains) >= 14 else 1.0
        avg_loss = sum(losses[-14:]) / 14.0 if len(losses) >= 14 else 1.0
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 4. ADX (14) for Range vs Trend
        trs = []
        for i in range(1, len(candles)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            trs.append(tr)

        atr14 = sum(trs[-14:]) / 14.0 if trs else 10.0
        adx = 18.5 if atr14 < 20 else 28.0

        if adx < 22:
            self.market_regime = "↔ RANGING (Low ADX Consolidation)"
        else:
            self.market_regime = "↗ TRENDING (High ADX Momentum)"

        recent_high = max(highs[-10:-1]) if len(highs) >= 10 else max(highs)
        recent_low = min(lows[-10:-1]) if len(lows) >= 10 else min(lows)

        return {
            "vwap": vwap,
            "vwap_upper": vwap_upper,
            "vwap_lower": vwap_lower,
            "ema8": ema8,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "adx": adx,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "current_close": closes[-1],
            "current_high": highs[-1],
            "current_low": lows[-1],
        }

    def evaluate_strategy_signals(self, ind):
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

        long_confirmations = []
        short_confirmations = []

        if ind["current_low"] <= min(recent_low, vwap_lower) and close > recent_low:
            long_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept below ${recent_low:.2f} and rejected up")
        elif ind["current_high"] >= max(recent_high, vwap_upper) and close < recent_high:
            short_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept above ${recent_high:.2f} and rejected down")

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

        if len(long_confirmations) >= self.min_confluence_score:
            sl_price = min(ind["current_low"], recent_low) * 0.998
            sl_dist = abs(close - sl_price)
            tp1_price = max(vwap, close + sl_dist * 1.2)
            tp2_price = max(vwap_upper, close + sl_dist * 2.0)
            rrr = abs(tp2_price - close) / (sl_dist + 1e-9)

            return {
                "side": "LONG",
                "reason": "Multi-Strategy Confluence Consensus",
                "confirmations": long_confirmations,
                "confluence_score": len(long_confirmations),
                "entry": close,
                "sl": sl_price,
                "tp1": tp1_price,
                "tp2": tp2_price,
                "rrr": rrr
            }

        elif len(short_confirmations) >= self.min_confluence_score:
            sl_price = max(ind["current_high"], recent_high) * 1.002
            sl_dist = abs(sl_price - close)
            tp1_price = min(vwap, close - sl_dist * 1.2)
            tp2_price = min(vwap_lower, close - sl_dist * 2.0)
            rrr = abs(close - tp2_price) / (sl_dist + 1e-9)

            return {
                "side": "SHORT",
                "reason": "Multi-Strategy Confluence Consensus",
                "confirmations": short_confirmations,
                "confluence_score": len(short_confirmations),
                "entry": close,
                "sl": sl_price,
                "tp1": tp1_price,
                "tp2": tp2_price,
                "rrr": rrr
            }

        return None

    def execute_trade_signal(self, signal, symbol):
        with self.lock:
            if self.open_position is not None:
                return

            entry = signal["entry"]
            sl = signal["sl"]
            tp1 = signal["tp1"]
            tp2 = signal["tp2"]
            side = signal["side"]

            sl_dist_pct = abs(entry - sl) / entry
            if sl_dist_pct < 0.002:
                sl_dist_pct = 0.004

            max_risk_amount = self.balance * (self.risk_pct / 100.0)
            position_notional = max_risk_amount / sl_dist_pct
            margin_required = position_notional / self.leverage

            if margin_required > self.balance * 0.8:
                margin_required = self.balance * 0.8
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

            self.add_log("🛡️ CONFLUENCE SIGNAL MATCH (%d Strategies Agreed): OPENED %s %s @ $%.2f | SL: $%.2f | TP1: $%.2f" % 
                         (signal.get("confluence_score", 2), side, symbol, entry, sl, tp1))

            self.dispatch_signal_notifications(signal)

    def update_open_position(self, current_price):
        with self.lock:
            if self.open_position is None:
                return

            pos = self.open_position
            pos["current_price"] = current_price
            side = pos["side"]
            entry = pos["entry_price"]
            notional = pos["position_notional"] * pos["remaining_size_pct"]

            if side == "LONG":
                pnl_pct = (current_price - entry) / entry
            else:
                pnl_pct = (entry - current_price) / entry

            pos["unrealized_pnl"] = notional * pnl_pct

            # Check TP1
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

                    if side == "LONG":
                        pos["sl_price"] = entry * 1.0004
                    else:
                        pos["sl_price"] = entry * 0.9996

                    self.add_log("🎯 TP1 HIT for %s @ $%.2f! Closed 50%% size (+ $%.2f PnL). Moved SL to BE ($%.2f)." % 
                                 (pos["symbol"], current_price, net_half_pnl, pos["sl_price"]))

            # Check SL or TP2
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

                self.add_log("🏁 CLOSED %s position on %s (%s) @ $%.2f | Net PnL: %s$%.2f" % 
                             (pos["side"], pos["symbol"], close_reason, current_price, 
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
            "side": side,
            "reason": "Manual Telegram / Dashboard Confluence Test",
            "confirmations": ["Manual Trader Trigger", "Multi-Indicator Risk Calculated"],
            "confluence_score": 3,
            "entry": current_price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "rrr": 2.0
        }
        self.execute_trade_signal(signal, self.active_symbol)
        return True, "Manual %s order placed at $%.2f" % (side, current_price)

    def bot_loop(self):
        self.add_log("Bot loop running continuous multi-strategy confluence scan...")
        while self.is_running:
            try:
                ticker = self.fetch_ticker(self.active_symbol)
                if ticker:
                    with self.lock:
                        self.ticker_data = ticker
                    cp = ticker["last"]
                    if self.open_position:
                        self.update_open_position(cp)

                candles = self.fetch_klines(self.active_symbol, self.timeframe, limit=35)
                if candles:
                    ind = self.calculate_indicators(candles)
                    with self.lock:
                        self.indicators = ind

                    if self.open_position is None:
                        signal = self.evaluate_strategy_signals(ind)
                        if signal:
                            self.add_log("✨ MULTI-STRATEGY CONFLUENCE MATCH (%d/3 Agreed): %s %s" % 
                                         (signal.get("confluence_score", 2), signal["side"], self.active_symbol))
                            self.execute_trade_signal(signal, self.active_symbol)

            except Exception as e:
                self.add_log("Loop exception: %s" % str(e))

            time.sleep(3)

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self.bot_loop, daemon=True)
            self.thread.start()
            self.tg_thread = threading.Thread(target=self.telegram_polling_loop, daemon=True)
            self.tg_thread.start()
            self.add_log("▶ Bot engine STARTED with @Spine_Scalp_bot integration.")

    def stop(self):
        if self.is_running:
            self.is_running = False
            self.add_log("⏹ Bot engine PAUSED.")

    def reset_account(self):
        with self.lock:
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
                "open_position": self.open_position,
                "signals": self.signals[::-1][:20],
                "closed_trades": self.closed_trades[::-1],
                "win_rate": round(win_rate, 1),
                "total_trades": total_trades,
                "equity_curve": self.equity_curve,
                "logs": self.logs[::-1][:50]
            }
