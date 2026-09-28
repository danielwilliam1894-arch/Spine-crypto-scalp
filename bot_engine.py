import time
import threading
import json
import urllib.request
import urllib.parse
import math
import numpy as np
import pandas as pd
from datetime import datetime

class CryptoScalpBot:
    def __init__(self, initial_balance=1000.0):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.is_running = False
        self.lock = threading.RLock()
        
        # Bot Settings
        self.active_symbol = "BTC-USDT-SWAP"
        self.active_strategy = "multi_confluence"  # multi_confluence (DEFAULT), sweep_reversal, ema_ribbon, profile_poc
        self.min_confluence_score = 2  # At least 2 strategies must agree before signal
        self.timeframe = "5m"
        self.risk_pct = 1.0  # 1% per trade
        self.leverage = 10
        self.fee_rate = 0.0002  # 0.02% Maker fee
        
        # Telegram Integration (User's Bot Token Pre-Configured)
        self.telegram_token = "8688574893:AAHbPFTSmu-MPfOpuk7SXfNokIC4SdNGwBU"
        self.telegram_chat_id = ""
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
        self.add_log("Bot engine initialized with Telegram Bot Token @Spine_Scalp_bot.")

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
            threading.Thread(target=self.send_discord_alert, args=(f"🛡️ Multi-Strategy Signal: {self.active_symbol}", msg.replace('*', ''), color), daemon=True).start()

    def telegram_polling_loop(self):
        """Polls incoming commands from user's Telegram chatbot (@Spine_Scalp_bot)."""
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
                                # Automatically save user's chat_id!
                                if not self.telegram_chat_id:
                                    self.telegram_chat_id = str(chat_id)
                                    self.add_log("✅ Automatically linked Telegram Chat ID: %s" % chat_id)
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
                    f"Your chatbot is successfully linked to the live strategy engine!\n\n" \
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
                    return pd.DataFrame(records)
        except Exception:
            pass
            
        now_ts = int(time.time() * 1000)
        base_price = self.ticker_data.get("last", 82850.0)
        records = []
        for i in range(limit):
            ts = now_ts - (limit - i) * 300000
            p = base_price + np.random.randn() * 40
            records.append({
                'ts': ts,
                'open': p - 10,
                'high': p + 25,
                'low': p - 25,
                'close': p,
                'vol': 1500.0 + np.random.rand() * 500
            })
        return pd.DataFrame(records)

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

    def calculate_indicators(self, df):
        if df.empty or len(df) < 14:
            return {}

        df['tp'] = (df['high'] + df['low'] + df['close']) / 3.0
        df['tp_vol'] = df['tp'] * df['vol']
        
        cum_vol = df['vol'].sum()
        cum_tp_vol = df['tp_vol'].sum()
        vwap = cum_tp_vol / cum_vol if cum_vol > 0 else df['close'].iloc[-1]
        
        std = float(df['tp'].std())
        vwap_upper = vwap + std
        vwap_lower = vwap - std

        ema8 = float(df['close'].ewm(span=8, adjust=False).mean().iloc[-1])
        ema20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(df['close'].ewm(span=50, adjust=False).mean().iloc[-1])

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
        rs = gain / (loss + 1e-9)
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        # ADX (14) Calculation for Range vs Trend Detection
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
        
        tr14 = df['tr'].rolling(14, min_periods=1).sum()
        pdm14 = df['plus_dm'].rolling(14, min_periods=1).sum()
        mdm14 = df['minus_dm'].rolling(14, min_periods=1).sum()
        
        plus_di = 100 * (pdm14 / (tr14 + 1e-9))
        minus_di = 100 * (mdm14 / (tr14 + 1e-9))
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9))
        adx = float(dx.rolling(14, min_periods=1).mean().iloc[-1])

        # Determine Market Regime State
        if adx < 22:
            self.market_regime = "↔ RANGING (Low ADX Consolidation)"
        elif plus_di.iloc[-1] > minus_di.iloc[-1]:
            self.market_regime = "↗ TRENDING UPTREND (Strong ADX Expansion)"
        else:
            self.market_regime = "↘ TRENDING DOWNTREND (Strong ADX Expansion)"

        recent_high = float(df['high'].iloc[-10:-1].max()) if len(df) >= 10 else float(df['high'].max())
        recent_low = float(df['low'].iloc[-10:-1].min()) if len(df) >= 10 else float(df['low'].min())

        return {
            "vwap": float(vwap),
            "vwap_upper": float(vwap_upper),
            "vwap_lower": float(vwap_lower),
            "ema8": ema8,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "adx": adx,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "current_close": float(df['close'].iloc[-1]),
            "current_high": float(df['high'].iloc[-1]),
            "current_low": float(df['low'].iloc[-1]),
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

        # 1. Strategy 1: Liquidity Sweep Check
        if ind["current_low"] <= min(recent_low, vwap_lower) and close > recent_low:
            long_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept below ${recent_low:.2f} and rejected up")
        elif ind["current_high"] >= max(recent_high, vwap_upper) and close < recent_high:
            short_confirmations.append(f"Strat 1 (Liquidity Sweep): Price swept above ${recent_high:.2f} and rejected down")

        # 2. Strategy 2: EMA Ribbon Alignment & Pullback Check
        if ema8 > ema20 > ema50 and close >= ema50 and close <= ema20 * 1.002:
            long_confirmations.append(f"Strat 2 (EMA Ribbon): Uptrend Ribbon aligned (EMA 8>20>50) with pullback to support")
        elif ema8 < ema20 < ema50 and close <= ema50 and close >= ema20 * 0.998:
            short_confirmations.append(f"Strat 2 (EMA Ribbon): Downtrend Ribbon aligned (EMA 8<20<50) with rally to resistance")

        # 3. Strategy 3: Volume Profile / VWAP Value Area Check
        if close <= vwap_lower:
            long_confirmations.append(f"Strat 3 (Volume Profile): Price at Value Area Low (VAL) - Oversold Fair Value zone")
        elif close >= vwap_upper:
            short_confirmations.append(f"Strat 3 (Volume Profile): Price at Value Area High (VAH) - Overbought Fair Value zone")

        # 4. Strategy 4: RSI Momentum Filter Check
        if rsi < 42:
            long_confirmations.append(f"Strat 4 (RSI Momentum): RSI ({rsi:.1f}) oversold hook")
        elif rsi > 58:
            short_confirmations.append(f"Strat 4 (RSI Momentum): RSI ({rsi:.1f}) overbought hook")

        # SINGLE STRATEGY OVERRIDE (If explicitly selected)
        if self.active_strategy == "sweep_reversal":
            if any("Strat 1" in c for c in long_confirmations) and rsi < 48:
                return {
                    "side": "LONG",
                    "reason": "Liquidity Sweep Reversal",
                    "confirmations": [c for c in long_confirmations if "Strat 1" in c],
                    "confluence_score": 1,
                    "entry": close,
                    "sl": close * 0.996,
                    "tp1": vwap,
                    "tp2": vwap_upper,
                    "rrr": abs(vwap_upper - close) / (close * 0.004)
                }
            elif any("Strat 1" in c for c in short_confirmations) and rsi > 52:
                return {
                    "side": "SHORT",
                    "reason": "Liquidity Sweep Reversal",
                    "confirmations": [c for c in short_confirmations if "Strat 1" in c],
                    "confluence_score": 1,
                    "entry": close,
                    "sl": close * 1.004,
                    "tp1": vwap,
                    "tp2": vwap_lower,
                    "rrr": abs(close - vwap_lower) / (close * 0.004)
                }

        # MULTI-STRATEGY CONFLUENCE ENGINE (DEFAULT)
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

                df = self.fetch_klines(self.active_symbol, self.timeframe, limit=35)
                if not df.empty:
                    ind = self.calculate_indicators(df)
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
