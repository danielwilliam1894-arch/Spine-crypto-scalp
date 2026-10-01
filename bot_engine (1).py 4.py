import time
import threading
import json
import os
import tempfile
import urllib.request
import urllib.parse
import csv
import uuid
import math
import re
import urllib.error
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from datetime import datetime, timezone, timedelta

from okx_demo import OKXDemoClient, OKXDemoError


def _load_local_env_file():
    """Load non-overriding KEY=VALUE settings from a private project .env file, if present."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or key in os.environ:
                    continue
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '\"'}:
                    value = value[1:-1]
                elif " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
                os.environ[key] = value
    except FileNotFoundError:
        return
    except OSError:
        # Configuration loading fails closed: callers will report missing required settings.
        return


_load_local_env_file()

LAGOS_TZ = timezone(timedelta(hours=1), name="Africa/Lagos")
CONFLUENCE_MAX = 3

class CryptoScalpBot:
    def __init__(self, initial_balance=1000.0, state_path=None):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.is_running = False
        self.lock = threading.RLock()
        
        # Original three-pillar setup; user-selected entry threshold is 3/3 in every session.
        self.active_symbol = "BTC-USDT-SWAP"
        self.active_strategy = "playbook_3pillar"
        self.min_confluence_score = 3
        self.timeframe = "5m"
        self.risk_pct = 1.0  # approved default planned risk per stop
        self.leverage = 10
        self.margin_cap_usd = 3.0  # hard initial-margin cap; never treated as fixed position sizing
        self.margin_cap_pct = 0.0  # retained only for compatibility with legacy status clients
        self.fee_rate = float(os.environ.get("OKX_TAKER_FEE_RATE", "0.00055"))
        self.slippage_bps = 5.0
        self.max_adx = None  # ADX is descriptive only in the restored three-pillar strategy.
        self.trade_log_path = os.environ.get("TRADE_LOG_PATH", os.path.join(os.path.dirname(__file__), "trade_log.csv"))
        self.funding_history = []
        self._last_funding_refresh_epoch = 0.0
        self._demo_algo_id = None

        # Exchange Execution Settings: no live mode exists in this build.
        self.okx_demo_client = OKXDemoClient.from_env()
        self.execution_mode = "okx_demo" if self.okx_demo_client is not None else "paper"
        self.demo_orders_armed = self.execution_mode == "okx_demo" and os.environ.get("OKX_DEMO_ORDER_ARMED", "") == "1"
        self.demo_ready = False
        self.demo_halted = False
        self.demo_preflight_status = "Demo credentials are not configured." if self.execution_mode == "paper" else "Demo preflight not yet checked."
        self.demo_equity = None
        self.demo_initial_equity = None
        self._demo_equity_updated = 0.0
        self._demo_instrument = None
        self._demo_last_position_check = 0.0
        self._demo_reconciling = False
        self._pending_demo_entry = None
        self.demo_external_position = None
        self.live_execution_enabled = False

        # Institutional Filters Toggle
        self.enable_mtf_filter = True      # 1H Macro Trend Alignment
        self.enable_funding_shield = True  # OKX Funding Rate Sentiment Shield
        self.enable_atr_adapter = True     # Dynamic Volatility ATR Stops/TPs
        self.enable_session_weight = True  # London/NY vs Asian Session Weighting
        self.enable_circuit_breaker = True # Slippage / Volatility Spike Guard

        # Telegram Integration
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.discord_webhook_url = ""
        self.enable_telegram = True
        self.enable_discord = False
        self.telegram_update_offset = 0
        self.telegram_polling_status = "not started"
        self.telegram_last_poll_epoch = 0.0
        self.telegram_last_success_epoch = 0.0
        self.telegram_last_error = ""
        self.telegram_last_error_epoch = 0.0
        self.telegram_send_failures = 0
        self.telegram_daily_noon_enabled = os.environ.get("TELEGRAM_DAILY_NOON_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.last_noon_summary_date = ""
        self._last_noon_summary_attempt_date = ""
        self._last_noon_summary_attempt_epoch = 0.0
        self.last_ticker_update_epoch = 0.0
        self.last_indicator_update_epoch = 0.0

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
        self._logged_once = set()
        self.equity_curve = [{"time": datetime.now().strftime("%H:%M:%S"), "equity": initial_balance}]
        self.last_signal_time = {}
        self.last_processed_signal_close = {}
        self.circuit_breaker_until = {}
        
        # Risk gates reset at midnight Lagos time and are persisted locally.
        self.state_path = state_path or os.environ.get(
            "BOT_STATE_PATH", os.path.join(os.path.dirname(__file__), "bot_state.json")
        )
        self.consecutive_losses = 0
        self.max_consecutive_losses = 2
        self.daily_start_equity = float(initial_balance)
        self.max_daily_drawdown_pct = 2.0
        self.daily_date = datetime.now(LAGOS_TZ).date().isoformat()
        self.daily_loss_pause = False
        self.daily_pause_reason = ""
        self.current_daily_drawdown_pct = 0.0
        self.stale_trade_seconds = 2 * 60 * 60

        # The approved scope is the single BTC perpetual contract.
        self.supported_symbols = ["BTC-USDT-SWAP"]
        self.thread = None
        self.tg_thread = None
        self._load_state()
        self._refresh_daily_guard()
        self.add_log("OKX BTC three-pillar strategy initialized in %s mode; live trading is not supported." % self.execution_mode.upper())
        if self.execution_mode == "paper":
            self.add_log("OKX demo credentials are not configured; simulated paper orders only.")

    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = "[%s] %s" % (timestamp, message)
        print(log_entry)
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > 200:
                self.logs.pop(0)

    def _log_once(self, key, message):
        with self.lock:
            if key in self._logged_once:
                return
            self._logged_once.add(key)
        self.add_log(message)

    def _append_trade_log_event(self, event_type, position, details=None):
        """Append a credential-free, audit-friendly event row to the CSV trade ledger."""
        if not self.trade_log_path:
            return
        details = details or {}
        fields = [
            "event_type", "event_time_utc", "event_time_lagos", "trade_id", "mode",
            "symbol", "side", "strategy", "confluence_score", "adx_5m",
            "entry_bar_close_ms", "entry_time", "exit_time", "signal_bar_close_price",
            "entry_quote_price", "entry_price", "exit_price",
            "initial_stop", "current_stop", "tp1_price", "tp2_price", "tp1_hit",
            "position_notional_usd", "quantity_contracts", "margin_usd", "leverage",
            "risk_pct", "risk_budget_usd", "planned_initial_risk_usd", "R_net", "fee_rate",
            "slippage_bps", "slippage_cost_est_usd", "funding_cashflow_usd", "funding_source",
            "fees_usd", "gross_pnl_usd", "net_pnl_usd",
            "close_reason", "entry_order_id",
            "exit_order_ids", "stop_algo_id", "strategy_votes_json", "confirmations_json",
            "event_details_json",
        ]
        now_utc = datetime.now(timezone.utc)
        row = {
            "event_type": event_type,
            "event_time_utc": now_utc.isoformat(timespec="milliseconds"),
            "event_time_lagos": now_utc.astimezone(LAGOS_TZ).strftime("%Y-%m-%d %H:%M:%S%z"),
            "trade_id": position.get("id", ""),
            "mode": position.get("execution_mode", self.execution_mode),
            "symbol": position.get("symbol", ""),
            "side": position.get("side", ""),
            "strategy": position.get("strategy", ""),
            "confluence_score": position.get("confluence_score", ""),
            "adx_5m": position.get("adx_5m", ""),
            "entry_bar_close_ms": position.get("entry_bar_close_ms", ""),
            "entry_time": position.get("entry_time", ""),
            "exit_time": details.get("exit_time", ""),
            "signal_bar_close_price": position.get("signal_bar_close_price", ""),
            "entry_quote_price": position.get("entry_quote_price", ""),
            "entry_price": position.get("entry_price", ""),
            "exit_price": details.get("exit_price", ""),
            "initial_stop": position.get("initial_sl_price", position.get("sl_price", "")),
            "current_stop": position.get("sl_price", ""),
            "tp1_price": position.get("tp1_price", ""),
            "tp2_price": position.get("tp2_price", ""),
            "tp1_hit": position.get("tp1_hit", False),
            "position_notional_usd": position.get("position_notional", ""),
            "quantity_contracts": position.get("contracts", ""),
            "margin_usd": position.get("margin", ""),
            "leverage": position.get("leverage", ""),
            "risk_pct": position.get("risk_pct", ""),
            "risk_budget_usd": position.get("risk_budget_usd", ""),
            "planned_initial_risk_usd": position.get("planned_initial_risk_usd", ""),
            "R_net": details.get("R_net", ""),
            "fee_rate": position.get("fee_rate", self.fee_rate),
            "slippage_bps": position.get("slippage_bps", self.slippage_bps),
            "slippage_cost_est_usd": position.get("slippage_cost_est_usd", ""),
            "funding_cashflow_usd": position.get("funding_cashflow_usd", ""),
            "funding_source": position.get("funding_source", ""),
            "fees_usd": details.get("fees_usd", position.get("total_fees", "")),
            "gross_pnl_usd": details.get("gross_pnl_usd", position.get("realized_gross_pnl", "")),
            "net_pnl_usd": details.get("net_pnl_usd", ""),
            "close_reason": details.get("close_reason", ""),
            "entry_order_id": position.get("entry_order_id", ""),
            "exit_order_ids": json.dumps(position.get("exit_order_ids", [])),
            "stop_algo_id": position.get("stop_algo_id", ""),
            "strategy_votes_json": json.dumps(position.get("strategy_votes", {}), sort_keys=True, default=str),
            "confirmations_json": json.dumps(position.get("confirmations", []), default=str),
            "event_details_json": json.dumps(details, sort_keys=True, default=str),
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.trade_log_path))
            os.makedirs(directory, exist_ok=True)
            needs_header = not os.path.exists(self.trade_log_path) or os.path.getsize(self.trade_log_path) == 0
            with open(self.trade_log_path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                if needs_header:
                    writer.writeheader()
                writer.writerow(row)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            self._log_once("trade_log_write", f"Trade-log write failed ({type(exc).__name__}); state remains in the local bot ledger.")

    def _state_snapshot(self):
        """Non-secret runtime state; demo credentials are never serialized."""
        return {
            "version": 4,
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "consecutive_losses": self.consecutive_losses,
            "daily_start_equity": self.daily_start_equity,
            "daily_date": self.daily_date,
            "daily_loss_pause": self.daily_loss_pause,
            "daily_pause_reason": self.daily_pause_reason,
            "current_daily_drawdown_pct": self.current_daily_drawdown_pct,
            "closed_trades": self.closed_trades[-500:],
            "equity_curve": self.equity_curve[-1000:],
            "signals": self.signals[-1000:],
            "open_position": self.open_position,
            "demo_halted": self.demo_halted,
            "demo_initial_equity": self.demo_initial_equity,
            "pending_demo_entry": self._pending_demo_entry,
            "funding_history": self.funding_history[-400:],
            "last_noon_summary_date": self.last_noon_summary_date,
        }

    def _save_state(self):
        """Atomically persist non-secret paper-account and daily-risk state."""
        if not self.state_path:
            return
        try:
            with self.lock:
                payload = self._state_snapshot()
                directory = os.path.dirname(os.path.abspath(self.state_path))
                os.makedirs(directory, exist_ok=True)
                fd, temp_path = tempfile.mkstemp(prefix=".bot-state-", dir=directory, text=True)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_path, self.state_path)
                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
        except Exception as exc:
            self.add_log(f"⚠️ Could not persist bot state: {exc}")

    def _load_state(self):
        """Restore paper/strategy state only; never restore credentials."""
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            if state.get("version") not in (1, 2, 3, 4):
                return
            self.balance = float(state.get("balance", self.balance))
            self.initial_balance = float(state.get("initial_balance", self.initial_balance))
            self.consecutive_losses = max(0, int(state.get("consecutive_losses", 0)))
            self.daily_start_equity = float(state.get("daily_start_equity", self.initial_balance))
            self.daily_date = str(state.get("daily_date", self.daily_date))
            self.daily_loss_pause = bool(state.get("daily_loss_pause", False))
            self.daily_pause_reason = str(state.get("daily_pause_reason", ""))
            self.current_daily_drawdown_pct = float(state.get("current_daily_drawdown_pct", 0.0))
            self.closed_trades = list(state.get("closed_trades", []))[-500:]
            self.equity_curve = list(state.get("equity_curve", self.equity_curve))[-1000:]
            self.signals = list(state.get("signals", []))[-1000:]
            self.funding_history = list(state.get("funding_history", []))[-400:]
            self.last_noon_summary_date = str(state.get("last_noon_summary_date", ""))
            restored_position = state.get("open_position")
            self.open_position = restored_position
            self.demo_halted = bool(state.get("demo_halted", False))
            saved_demo_equity = state.get("demo_initial_equity")
            self.demo_initial_equity = float(saved_demo_equity) if saved_demo_equity is not None else None
            self._pending_demo_entry = state.get("pending_demo_entry")
            if self._pending_demo_entry:
                self.demo_halted = True
                self.demo_preflight_status = "Unresolved demo order intent restored; manual/exchange reconciliation required."
        except Exception as exc:
            self.add_log(f"⚠️ Could not restore bot state; starting fresh paper ledger: {exc}")

    def _current_equity(self):
        with self.lock:
            if self.execution_mode == "okx_demo" and self.demo_equity is not None:
                return float(self.demo_equity)
            equity = self.balance
            if self.open_position and self.open_position.get("execution_mode") != "okx_demo":
                equity += float(self.open_position.get("unrealized_pnl", 0.0))
            return equity

    def _refresh_daily_guard(self, now=None):
        """Roll risk counters at midnight Lagos time and pause entries at daily limits."""
        now = now or datetime.now(LAGOS_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=LAGOS_TZ)
        today = now.astimezone(LAGOS_TZ).date().isoformat()
        with self.lock:
            equity = self._current_equity()
            if today != self.daily_date:
                self.daily_date = today
                self.daily_start_equity = max(equity, 0.01)
                self.consecutive_losses = 0
                self.daily_loss_pause = False
                self.daily_pause_reason = ""
                self.current_daily_drawdown_pct = 0.0
                self.add_log(f"📅 New Lagos trading day: risk counters reset; start equity ${self.daily_start_equity:.2f}.")
                self._save_state()

            if self.daily_start_equity > 0:
                self.current_daily_drawdown_pct = max(
                    0.0, (self.daily_start_equity - equity) / self.daily_start_equity * 100.0
                )
            if (self.current_daily_drawdown_pct >= self.max_daily_drawdown_pct
                    and not self.daily_loss_pause):
                self.daily_loss_pause = True
                self.daily_pause_reason = f"daily drawdown reached {self.current_daily_drawdown_pct:.2f}%"
                self.add_log(f"🛑 DAILY LOSS GUARD: {self.daily_pause_reason}; new entries paused until midnight Lagos time.")
                self._save_state()
            return not self.daily_loss_pause

    def _record_trade_outcome(self, net_pnl, now=None):
        with self.lock:
            if net_pnl > 0:
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
                self.add_log(f"⚠️ CONSECUTIVE LOSS COUNT: {self.consecutive_losses}/{self.max_consecutive_losses}")
            if self.consecutive_losses >= self.max_consecutive_losses and not self.daily_loss_pause:
                self.daily_loss_pause = True
                self.daily_pause_reason = f"{self.consecutive_losses} consecutive net losses"
                self.add_log(f"🛑 DAILY LOSS GUARD: {self.daily_pause_reason}; new entries paused until midnight Lagos time.")
            self._refresh_daily_guard(now=now)
            self._save_state()

    def format_price(self, val):
        if val is None:
            return "0.00"
        if abs(val) < 1.0:
            return f"{val:.4f}"
        elif abs(val) < 100.0:
            return f"{val:.3f}"
        else:
            return f"{val:.2f}"

    def _telegram_post(self, endpoint, payload, timeout=8.0):
        """Call the Telegram API without ever logging or returning the token-bearing URL."""
        url = f"https://api.telegram.org/bot{self.telegram_token}/{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            try:
                raw = exc.read().decode("utf-8", errors="replace")
            except Exception:
                raw = ""
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            kind = type(reason).__name__ if reason is not None else type(exc).__name__
            return False, None, f"network error ({kind})"
        except Exception as exc:
            return False, None, f"request failed ({type(exc).__name__})"

        try:
            result = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            result = {}
        if isinstance(result, dict) and result.get("ok") is True:
            return True, status_code, ""
        code = result.get("error_code", status_code) if isinstance(result, dict) else status_code
        description = result.get("description", "Telegram returned an unrecognized response") if isinstance(result, dict) else "Telegram returned an unrecognized response"
        description = " ".join(str(description).replace(self.telegram_token, "[redacted]").split())[:180]
        return False, code, description

    def send_telegram_alert(self, text, chat_id=None):
        target_chat = chat_id or self.telegram_chat_id
        if not self.telegram_token or not target_chat:
            message = "Telegram is not configured: set TELEGRAM_BOT_TOKEN and numeric TELEGRAM_CHAT_ID on the server."
            self.telegram_last_error = message
            self.telegram_last_error_epoch = time.time()
            return False, message
        if not self.enable_telegram:
            return False, "Telegram notifications are disabled in server configuration."

        ok, code, detail = self._telegram_post("sendMessage", {
            "chat_id": target_chat, "text": str(text), "parse_mode": "Markdown",
        })
        used_plain_fallback = False
        if not ok and str(code) == "400" and "entit" in str(detail).lower():
            # Dynamic feed/reason text can contain Markdown-reserved characters. Retry only
            # a definite Telegram parse rejection, never after a timeout/ambiguous send.
            plain = re.sub(r"[`*_]", "", str(text))
            ok, code, detail = self._telegram_post("sendMessage", {"chat_id": target_chat, "text": plain})
            used_plain_fallback = ok
        if ok:
            self.telegram_last_success_epoch = time.time()
            self.telegram_last_error = ""
            self.telegram_last_error_epoch = 0.0
            message = "Telegram alert sent successfully."
            if used_plain_fallback:
                message += " Markdown was rejected, so it was delivered as plain text."
            return True, message

        self.telegram_send_failures += 1
        self.telegram_last_error = f"Telegram send rejected ({code}): {detail}"
        self.telegram_last_error_epoch = time.time()
        # Telegram API descriptions contain the actionable error; never log the request URL/token.
        self._log_once(f"telegram_send_{code}_{detail[:50]}", self.telegram_last_error)
        return False, self.telegram_last_error

    def send_discord_alert(self, title, description, color=3066993):
        if not self.discord_webhook_url:
            return False, "Discord Webhook URL not configured."
        try:
            payload = json.dumps({
                "embeds": [{
                    "title": title,
                    "description": description,
                    "color": color,
                    "footer": {"text": "Crypto Futures Paper Scanner • 3-Pillar Confluence"}
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
        conf_score = int(signal.get("confluence_score", 0))
        if conf_score != 3:
            return

        badge_title = f"🎯 *{conf_score}/3 THREE-PILLAR SETUP*"
        side_emoji = f"🟢 {conf_score}/3 LONG" if signal["side"] == "LONG" else f"🔴 {conf_score}/3 SHORT"
        confluence_str = "\n".join([f"  ✓ {item}" for item in signal.get("confirmations", [signal.get("reason", "confirmed pillar")])])
        mtf_info = signal.get("mtf_status", "not supplied")
        fr_info = signal.get("funding_status", "not supplied")
        session_info = signal.get("session_status", "3/3 required in every session")
        adx = signal.get("adx")
        adx_info = f"`{float(adx):.2f}` (informational only)" if isinstance(adx, (int, float)) else "unavailable (not an entry gate)"
        if self.execution_mode == "okx_demo":
            exec_info = "OKX DEMO" + (" — order arm enabled" if self.demo_orders_armed else " — disarmed")
        else:
            exec_info = "PAPER SIMULATION — no exchange order sent"

        msg = f"{badge_title}\n\n" \
              f"Instrument: `{sym}`\n" \
              f"Setup: *{side_emoji}* — candidate only; not a guarantee\n" \
              f"Pillars: *{conf_score}/3 same-direction confirmations*\n\n" \
              f"📋 *Confirmed pillars:*\n{confluence_str}\n\n" \
              f"Session gate: `{session_info}`\n" \
              f"Context: 1H `{mtf_info}` | Funding `{fr_info}` | 5m ADX-14 {adx_info}\n" \
              f"Execution mode: `{exec_info}`\n" \
              f"This setup alert is not an order confirmation.\n\n" \
              f"Signal close `${self.format_price(signal['entry'])}` | SL `${self.format_price(signal['sl'])}`\n" \
              f"TP1 `${self.format_price(signal['tp1'])}` (50% scale-out) | TP2 `${self.format_price(signal['tp2'])}`\n" \
              f"TP2-distance / stop-distance: `1 : {signal.get('rrr', 0.0):.2f}` (not a win-rate estimate)\n" \
              f"Sizing limits: `{self.risk_pct:.2f}%` planned equity risk including fee/slippage reserves; max initial margin `${self.margin_cap_usd:.2f}` at ≤`{self.leverage}×`. Actual fills and gaps can differ."

        if self.enable_telegram and self.telegram_token and self.telegram_chat_id:
            threading.Thread(target=self.send_telegram_alert, args=(msg,), daemon=True).start()

        if self.enable_discord and self.discord_webhook_url:
            color = 65280 if signal["side"] == "LONG" else 16711680
            threading.Thread(target=self.send_discord_alert, args=(f"🚨 {conf_score}/3 Pillar Candidate: {sym}", msg.replace('*', ''), color), daemon=True).start()

    def maybe_send_daily_noon_summary(self, now=None):
        """Send one daily Lagos-noon market/status note, separate from entry alerts."""
        if (not self.telegram_daily_noon_enabled or not self.enable_telegram
                or not self.telegram_token or not self.telegram_chat_id):
            return False
        now = now or datetime.now(LAGOS_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=LAGOS_TZ)
        local_now = now.astimezone(LAGOS_TZ)
        if local_now.hour < 12:
            return False
        today = local_now.date().isoformat()
        now_epoch = local_now.timestamp()
        with self.lock:
            if self.last_noon_summary_date == today:
                return False
            if (self._last_noon_summary_attempt_date == today
                    and now_epoch - self._last_noon_summary_attempt_epoch < 300.0):
                return False
            self._last_noon_summary_attempt_date = today
            self._last_noon_summary_attempt_epoch = now_epoch

        status = self.get_status()
        summary = status.get("current_confluence_summary", {})
        candidates = status.get("confluence_candidates", [])
        best = max(candidates, key=lambda row: (bool(row.get("eligible")), int(row.get("score", 0)))) if candidates else None

        price = None
        if self.last_ticker_update_epoch and now_epoch - self.last_ticker_update_epoch <= 180.0:
            price = (status.get("ticker") or {}).get("last")
        price_text = f"`${self.format_price(float(price))}`" if isinstance(price, (int, float)) and price > 0 else "unavailable/stale"

        fresh_indicators = bool(self.last_indicator_update_epoch and now_epoch - self.last_indicator_update_epoch <= 360.0)
        if not fresh_indicators:
            reading = "Market indicators are warming up or stale."
            action = "NO ENTRY decision from this update; wait for a fresh confirmed 3/3 setup alert."
        elif best and int(best.get("score", 0)) >= 3 and best.get("eligible"):
            reading = f"{best['side']} {best['score']}/3 currently passes the configured filters."
            action = "This scheduled snapshot is NOT an entry signal. Wait for a separate confirmed setup alert with entry, stop and targets before considering a trade."
        elif best and int(best.get("score", 0)) >= 3:
            blockers = ", ".join(best.get("block_reasons", [])) or "a safety filter"
            reading = f"{best['side']} {best['score']}/3, but blocked by: {blockers}."
            action = "NO ENTRY based on this snapshot; wait for the configured gates to clear and a fresh confirmed alert."
        elif best:
            reading = f"{best['side']} {best['score']}/3 (watch-only)."
            action = "NO ENTRY: 2/3 is watch-only; this strategy requires 3/3 in every session."
        else:
            score = int(summary.get("confluence_score", 0) or 0)
            direction = summary.get("direction", "NEUTRAL")
            reading = f"{direction} {score}/3; no qualifying candidate is currently listed."
            action = "NO ENTRY based on this snapshot; wait for a separate confirmed 3/3 setup alert."

        risk_state = "PAUSED by daily risk guard" if status.get("daily_loss_pause") else "risk gate clear"
        msg = (
            "🕛 *DAILY BTC MARKET CHECK — LAGOS*\n\n"
            f"Time: `{local_now.strftime('%Y-%m-%d %H:%M')} WAT`\n"
            f"Instrument: `BTC-USDT-SWAP`\n"
            f"Last price: {price_text}\n"
            f"Confluence: {reading}\n"
            f"Risk status: `{risk_state}`\n\n"
            f"Decision: {action}\n\n"
            "This is a scheduled status snapshot, not a trade order or a profitability claim."
        )
        ok, result = self.send_telegram_alert(msg)
        if ok:
            with self.lock:
                self.last_noon_summary_date = today
            self._save_state()
            self.add_log(f"Telegram daily noon market check sent for Lagos day {today}.")
            return True
        self._log_once(f"telegram_noon_{today}", f"Daily noon Telegram check was not delivered: {result}")
        return False

    def telegram_polling_loop(self):
        self.add_log("Telegram command listener started; credentials remain server-side.")
        while self.is_running:
            if not self.enable_telegram:
                self.telegram_polling_status = "disabled"
                time.sleep(3)
                continue
            if not self.telegram_token:
                self.telegram_polling_status = "not configured; add TELEGRAM_BOT_TOKEN to the server environment"
                time.sleep(3)
                continue
            if self.telegram_chat_id:
                try:
                    int(self.telegram_chat_id)
                except (TypeError, ValueError):
                    self.telegram_polling_status = "TELEGRAM_CHAT_ID must be numeric; commands are blocked"
                    time.sleep(3)
                    continue
            else:
                self.telegram_polling_status = "setup-only mode; send /start to receive the numeric chat id; other commands are blocked"

            try:
                query = urllib.parse.urlencode({"offset": self.telegram_update_offset, "timeout": 3})
                url = f"https://api.telegram.org/bot{self.telegram_token}/getUpdates?{query}"
                req = urllib.request.Request(url, headers={"User-Agent": "OKXStrategyBot/1.0"})
                with urllib.request.urlopen(req, timeout=8.0) as response:
                    raw = json.loads(response.read().decode("utf-8", errors="replace"))
                self.telegram_last_poll_epoch = time.time()
                if not isinstance(raw, dict) or raw.get("ok") is not True:
                    description = raw.get("description", "Telegram returned an invalid getUpdates response") if isinstance(raw, dict) else "invalid Telegram response"
                    description = " ".join(str(description).split())[:160]
                    self.telegram_polling_status = f"poll error: {description}"
                    self._log_once(f"telegram_poll_api_{description[:60]}", f"Telegram polling error: {description}")
                    time.sleep(2)
                    continue

                self.telegram_polling_status = "connected; waiting for commands"
                for update in raw.get("result", []):
                    update_id = int(update.get("update_id", -1))
                    if update_id >= 0:
                        self.telegram_update_offset = max(self.telegram_update_offset, update_id + 1)
                    message = update.get("message") or update.get("edited_message") or {}
                    text = str(message.get("text", "")).strip()
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    if not text or chat_id is None:
                        continue
                    if not self.telegram_chat_id:
                        command = text.split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").lower()
                        if command in {"start", "id"}:
                            setup_message = (
                                f"Telegram setup reply. Your numeric chat id is `{chat_id}`.\n"
                                "Add it as `TELEGRAM_CHAT_ID` in the server environment (or private project `.env`) and restart. "
                                "Until then, all bot commands are disabled."
                            )
                            sent, send_message = self.send_telegram_alert(setup_message, chat_id)
                            self.telegram_polling_status = (
                                "setup reply sent; configure TELEGRAM_CHAT_ID and restart"
                                if sent else f"setup reply failed: {send_message}"
                            )
                        else:
                            self.telegram_polling_status = "setup-only mode; only /start and /id are accepted until TELEGRAM_CHAT_ID is configured"
                        continue
                    try:
                        chat_matches = int(chat_id) == int(self.telegram_chat_id)
                    except (TypeError, ValueError):
                        chat_matches = False
                    if not chat_matches:
                        self.telegram_polling_status = "connected, but ignored a command from a chat other than TELEGRAM_CHAT_ID"
                        self._log_once(
                            "telegram_chat_mismatch",
                            "Telegram command ignored because its chat id does not match TELEGRAM_CHAT_ID.",
                        )
                        continue
                    try:
                        self.handle_telegram_command(text, chat_id)
                    except Exception as exc:
                        self.telegram_polling_status = f"command handler error ({type(exc).__name__})"
                        self._log_once(
                            f"telegram_handler_{type(exc).__name__}",
                            f"Telegram command handler failed ({type(exc).__name__}); command was not retried.",
                        )
            except urllib.error.HTTPError as exc:
                try:
                    body = json.loads(exc.read().decode("utf-8", errors="replace"))
                except Exception:
                    body = {}
                description = body.get("description", f"HTTP {getattr(exc, 'code', 'error')}") if isinstance(body, dict) else "Telegram HTTP error"
                description = " ".join(str(description).replace(self.telegram_token, "[redacted]").split())[:160]
                self.telegram_polling_status = f"poll error: {description}"
                self._log_once(f"telegram_poll_http_{getattr(exc, 'code', 0)}", f"Telegram polling failed: {description}. Check bot token, network, and webhook/polling configuration.")
                time.sleep(3)
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", None)
                kind = type(reason).__name__ if reason is not None else type(exc).__name__
                self.telegram_polling_status = f"network error ({kind})"
                self._log_once(f"telegram_poll_network_{kind}", f"Telegram polling network error ({kind}); check outbound HTTPS access.")
                time.sleep(3)
            except Exception as exc:
                self.telegram_polling_status = f"poll error ({type(exc).__name__})"
                self._log_once(f"telegram_poll_{type(exc).__name__}", f"Telegram polling failed ({type(exc).__name__}).")
                time.sleep(3)
            time.sleep(1.0)

    def handle_telegram_command(self, cmd_text, chat_id):
        clean_text = cmd_text.lower().strip()
        cmd = clean_text.split()
        if not cmd:
            return

        # Telegram group commands may arrive as /command@BotUsername.
        base_cmd = cmd[0].split('@', 1)[0].lstrip('/')
        if base_cmd in {"start", "help", "hello", "hi"}:
            reply = (
                "🤖 *OKX BTC-USDT-SWAP strategy bot*\n\n"
                "Commands:\n"
                "• `/scan` — current three-pillar checks, 2/3 watches and 3/3 setups\n"
                "• `/test` — send an immediate Telegram delivery test (no order)\n"
                "• Daily summary — scheduled at 12:00 Lagos time when enabled\n"
                "• `/status` — execution mode, equity, risk gate and Telegram readiness\n"
                "• `/signals` — latest strategy signals\n"
                "• `/paper` — show current mode; cannot switch or arm execution\n"
                "• `/pair` — show the fixed BTC-USDT-SWAP instrument\n"
                "• `/close` — request a paper close or OKX demo reduce-only close\n"
                "• `/reset 1000` — reset the paper ledger only when flat\n\n"
                "Entry rule: all 3 pillars are required in every session, including regular hours. ADX is informational only. No live endpoint is available."
            )
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in {"test", "ping"}:
            test_message = (
                "🧪 *TELEGRAM DELIVERY TEST — NO ORDER*\n\n"
                "Your bot can send messages to this chat. Strategy alerts require 3/3 pillars; "
                "this is only a connectivity check, not a market signal or performance claim."
            )
            ok, result = self.send_telegram_alert(test_message, chat_id)
            if not ok:
                self.add_log(f"Telegram /test command failed: {result}")

        elif base_cmd in {"status", "stat", "state"}:
            status = self.get_status()
            summary = status["current_confluence_summary"]
            candidates = status["confluence_candidates"]
            tier2 = [c for c in candidates if c["score"] == 2]
            tier3 = [c for c in candidates if c["score"] == 3]
            ready = sum(1 for c in candidates if c["eligible"])
            pause = status["daily_pause_reason"] if status["daily_loss_pause"] else "clear"
            mode = "OKX DEMO" if status["execution_mode"] == "okx_demo" else "PAPER SIMULATION"
            mode += " (armed)" if status["demo_orders_armed"] else " (disarmed)" if status["execution_mode"] == "okx_demo" else ""
            needed = status["required_confluence"]
            session = "Asian UTC session" if status["asian_session"] else "regular session"
            adx = (status.get("indicators") or {}).get("adx")
            adx_text = f"{adx:.2f} (informational)" if isinstance(adx, (int, float)) else "unavailable (not a gate)"
            reply = (
                "📊 *BTC THREE-PILLAR BOT STATUS*\n\n"
                f"Running: `{status['is_running']}` | Mode: `{mode}`\n"
                f"Instrument: `BTC-USDT-SWAP` (${self.format_price(self.ticker_data.get('last', 0))})\n"
                f"Current setup: `{summary.get('direction', 'NEUTRAL')}` | max `{summary.get('confluence_score', 0)}/3` | ADX-14 `{adx_text}`\n"
                f"Required now: `{needed}/3` ({session})\n"
                f"Equity: `${status['equity']:.2f}` | Net PnL: `${status['total_pnl']:+.2f}`\n"
                f"Closed trades: `{status['total_trades']}` | Historical win rate: `{status['win_rate']:.1f}%` (not a forecast)\n"
                f"Daily gate: `{pause}` | Drawdown `{status['daily_drawdown_pct']:.2f}% / {status['max_daily_drawdown_pct']:.1f}%` | "
                f"Loss streak `{status['consecutive_losses']}/{status['max_consecutive_losses']}`\n"
                f"Candidates: `{len(tier2)}` 2/3 watch-only, `{len(tier3)}` at 3/3; `{ready}` pass active gates\n"
                f"Demo state: `{status['demo_preflight_status']}` | halted `{status['demo_halted']}`"
            )
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in {"scan", "coins", "market"}:
            status = self.get_status()
            summary = status["current_confluence_summary"]
            needed = status["required_confluence"]
            session = "Asian UTC session" if status["asian_session"] else "regular session"
            lines = [
                "📊 *BTC-USDT-SWAP THREE-PILLAR SCAN*",
                f"Setup: `{summary.get('direction', 'NEUTRAL')}` | confirmations `{summary.get('confluence_score', 0)}/3` | required `{needed}/3` ({session})",
            ]
            lines.extend(f"✓ {item}" for item in summary.get("confirmations", []))
            candidates = status["confluence_candidates"]
            if candidates:
                lines.append("Candidates:")
                for row in candidates:
                    state = "PASS" if row["eligible"] else "BLOCKED: " + "; ".join(row["block_reasons"])
                    lines.append(f"• `{row['side']} {row['score']}/3` — {state}")
            else:
                lines.append("No 2/3-or-better watch candidate in the latest confirmed 5m bar; entries require 3/3.")
            lines.append("ADX-14 is informational only; alerts are signals, not order confirmations.")
            lines.append(f"Execution mode: `{status['execution_mode']}`; no live endpoint.")
            self.send_telegram_alert("\n".join(lines), chat_id)

        elif base_cmd in {"bybit", "bybit_testnet", "binance"}:
            self.send_telegram_alert(
                "This bot has no Bybit/Binance connector. The approved exchange scope is OKX Demo Trading only. Do not send API secrets in Telegram.",
                chat_id,
            )

        elif base_cmd == "paper":
            mode = "OKX DEMO" if self.execution_mode == "okx_demo" else "PAPER SIMULATION"
            if self.execution_mode == "okx_demo":
                mode += " (armed)" if self.demo_orders_armed else " (disarmed)"
            self.send_telegram_alert(f"Execution mode is server-configured: `{mode}`. This command cannot switch modes or enable orders.", chat_id)

        elif base_cmd in {"funding", "rate", "rates"}:
            rate = self.multi_funding.get("BTC-USDT-SWAP", 0.0) * 100
            self.send_telegram_alert(
                f"⛽ BTC-USDT-SWAP latest observed funding: `{rate:+.4f}%`. Funding is context only; the legacy funding shield blocks crowded directional entries above its configured threshold. It is not proof of positioning or a reversal.",
                chat_id,
            )

        elif base_cmd in {"signals", "signal"}:
            with self.lock:
                if not self.signals:
                    reply = "No strategy signals recorded yet. Waiting for a confirmed 5m three-pillar setup."
                else:
                    sig_lines = []
                    for signal in self.signals[::-1][:5]:
                        score = int(signal.get("confluence_score", 0))
                        sig_lines.append(
                            f"• `{signal['time']}`: *{signal['side']}* `{signal['symbol']}` @ `${self.format_price(signal['entry'])}` ({score}/3 pillars)"
                        )
                    reply = "🚨 *LATEST STRATEGY SIGNALS*\n\n" + "\n".join(sig_lines)
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in {"long", "buy", "short", "sell"}:
            _, message = self.manual_trigger("LONG" if base_cmd in {"long", "buy"} else "SHORT")
            self.send_telegram_alert(f"🔒 {message}", chat_id)

        elif base_cmd in {"close", "exit"}:
            ok, message = self.close_position_market()
            self.send_telegram_alert(("✅ " if ok else "⚠️ ") + message, chat_id)

        elif base_cmd in {"reset", "balance"}:
            try:
                new_balance = float(cmd[1]) if len(cmd) > 1 else 1000.0
                if not 0.01 <= new_balance <= 1_000_000:
                    raise ValueError("Balance must be between $0.01 and $1,000,000.")
                self.reset_account(new_balance)
                reply = f"Paper ledger reset to `${new_balance:.2f}`. No exchange action was sent."
            except (TypeError, ValueError) as exc:
                reply = f"Reset declined: {exc}"
            self.send_telegram_alert(reply, chat_id)

        elif base_cmd in {"pair", "pairs"}:
            self.send_telegram_alert(
                "This bot is fixed to `BTC-USDT-SWAP`; instrument switching is disabled.", chat_id
            )

    def fetch_klines(self, symbol="BTC-USDT-SWAP", bar="5m", limit=35):
        """Fetch chronological, confirmed OKX candles, paging when a full session is needed."""
        intervals = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1H": 3_600_000}
        if bar not in intervals or limit <= 0:
            return None
        try:
            rows = {}
            cursor = None
            page_count = 0
            previous_oldest = None
            while len(rows) < limit and page_count < 20:
                page_limit = min(300, limit - len(rows))
                params = {"instId": symbol, "bar": bar, "limit": str(max(1, page_limit))}
                path = "/api/v5/market/candles" if cursor is None else "/api/v5/market/history-candles"
                if cursor is not None:
                    params["after"] = str(cursor)
                url = "https://www.okx.com" + path + "?" + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, headers={"User-Agent": "OKXPaperStrategy/2.0"})
                with urllib.request.urlopen(req, timeout=8.0) as res:
                    raw = json.loads(res.read().decode())
                if raw.get("code") != "0" or not raw.get("data"):
                    break
                page_count += 1
                page = raw["data"]
                for c in page:
                    if len(c) <= 8 or str(c[8]) != "1":
                        continue
                    ts = int(c[0])
                    rows[ts] = {
                        "ts": ts, "open": float(c[1]), "high": float(c[2]),
                        "low": float(c[3]), "close": float(c[4]), "vol": float(c[5]),
                    }
                oldest = min(int(c[0]) for c in page)
                if oldest == previous_oldest or oldest <= 0:
                    break
                previous_oldest = oldest
                cursor = oldest
                if len(page) < page_limit:
                    break
            candles = [rows[k] for k in sorted(rows)]
            return candles[-limit:] if candles else None
        except Exception as exc:
            self._log_once("candle_fetch", f"OKX candle fetch failed ({type(exc).__name__}).")
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

    def fetch_funding_history(self, symbol="BTC-USDT-SWAP"):
        """Fetch settled funding observations available from OKX's public endpoint."""
        rows = {}
        cursor = None
        previous_oldest = None
        try:
            for _ in range(6):
                params = {"instId": symbol, "limit": "100"}
                if cursor is not None:
                    params["after"] = str(cursor)
                url = "https://www.okx.com/api/v5/public/funding-rate-history?" + urllib.parse.urlencode(params)
                req = urllib.request.Request(url, headers={"User-Agent": "OKXPaperStrategy/2.0"})
                with urllib.request.urlopen(req, timeout=8.0) as res:
                    raw = json.loads(res.read().decode())
                if raw.get("code") != "0" or not raw.get("data"):
                    break
                timestamps = []
                for item in raw["data"]:
                    ts = int(item.get("fundingTime", 0))
                    timestamps.append(ts)
                    realized = item.get("realizedRate")
                    if realized not in (None, "") and ts > 0:
                        rows[ts] = {"ts": ts, "rate": float(realized)}
                if not timestamps:
                    break
                oldest = min(timestamps)
                if oldest == previous_oldest or len(raw["data"]) < 100:
                    break
                previous_oldest, cursor = oldest, oldest
            return [rows[t] for t in sorted(rows)]
        except Exception as exc:
            self._log_once("funding_history", f"OKX settled funding fetch failed ({type(exc).__name__}); settled funding history unavailable; paper funding PnL may be unverified.")
            return []

    def refresh_funding_history(self, now_epoch=None, symbol="BTC-USDT-SWAP"):
        """Refresh settled funding history used only for paper PnL accounting."""
        now_epoch = time.time() if now_epoch is None else float(now_epoch)
        if now_epoch - self._last_funding_refresh_epoch >= 3600:
            history = self.fetch_funding_history(symbol)
            if history:
                with self.lock:
                    self.funding_history = history[-400:]
                    self._save_state()
            self._last_funding_refresh_epoch = now_epoch

    def _ensure_demo_ready(self, require_armed=True):
        """Preflight only the hard-pinned OKX demo account; never falls back to live."""
        if self.execution_mode != "okx_demo" or self.okx_demo_client is None:
            self.demo_preflight_status = "Demo credentials are not configured."
            return False
        if require_armed and not self.demo_orders_armed:
            self.demo_preflight_status = "Demo credentials detected, but OKX_DEMO_ORDER_ARMED=1 is required; no entry order request sent."
            return False
        if self.demo_halted and require_armed:
            return False
        if self.demo_ready and time.time() - self._demo_equity_updated < 60.0:
            return True
        try:
            account = self.okx_demo_client.account_config()
            if account.get("posMode") != "net_mode":
                raise OKXDemoError("Demo account must use net position mode; no order was sent.")
            instrument = self.okx_demo_client.instrument("BTC-USDT-SWAP")
            if instrument.get("instId") != "BTC-USDT-SWAP" or instrument.get("state") != "live":
                raise OKXDemoError("BTC-USDT-SWAP demo instrument is not live.")
            required_fields = ("ctVal", "ctValCcy", "lotSz", "minSz", "tickSz")
            if any(instrument.get(key) in (None, "") for key in required_fields):
                raise OKXDemoError("Instrument sizing metadata is incomplete.")
            if any(Decimal(str(instrument[key])) <= 0 for key in ("ctVal", "lotSz", "minSz", "tickSz")):
                raise OKXDemoError("Instrument sizing metadata contains non-positive values.")
            if str(instrument["ctValCcy"]).upper() not in {"BTC", "USDT", "USD"}:
                raise OKXDemoError("Unsupported BTC contract-value currency; sizing is blocked.")
            self._demo_instrument = instrument
            self.okx_demo_client.set_leverage("BTC-USDT-SWAP", int(self.leverage))
            remote_positions = self.okx_demo_client.positions("BTC-USDT-SWAP")
            local_demo_position = self.open_position if self.open_position and self.open_position.get("execution_mode") == "okx_demo" else None
            if remote_positions and local_demo_position is None:
                self.demo_halted = True
                self.demo_external_position = remote_positions[0]
                self.demo_preflight_status = "Untracked OKX demo position detected; manual reconciliation required."
                self._save_state()
                return False
            if not remote_positions and local_demo_position is not None:
                self.demo_halted = True
                self.demo_preflight_status = "Stored demo trade is absent on OKX; reconciling exchange exit fills."
                if not require_armed:
                    self._reconcile_demo_closed_position()
                self._save_state()
                return False
            if remote_positions and local_demo_position is not None:
                remote = remote_positions[0]
                expected_side = "LONG" if float(remote.get("pos", 0.0)) > 0 else "SHORT"
                stored_qty = float(local_demo_position.get("remaining_contracts", local_demo_position.get("contracts", 0.0)))
                remote_qty = abs(float(remote.get("pos", 0.0)))
                lot_size = float(instrument.get("lotSz", 0.0))
                if (remote.get("instId") != local_demo_position.get("symbol") or expected_side != local_demo_position.get("side")
                        or abs(remote_qty - stored_qty) > max(lot_size, 1e-8)):
                    self.demo_halted = True
                    self.demo_preflight_status = "Demo position differs from stored trade; entries halted."
                    self._save_state()
                    return False
                stop_client_id = local_demo_position.get("stop_client_id")
                if not stop_client_id:
                    self.demo_halted = True
                    self.demo_preflight_status = "Stored demo position has no protective-stop client id; emergency reduce-only close initiated."
                    self._save_state()
                    self._demo_exit_position("PROTECTIVE STOP MISSING", full_close=True)
                    return False
                try:
                    live_stop = self.okx_demo_client.find_algo("BTC-USDT-SWAP", stop_client_id)
                except Exception:
                    live_stop = None
                if not live_stop or not live_stop.get("algoId"):
                    self.demo_halted = True
                    self.demo_preflight_status = "Stored demo position lacks a confirmed live protective stop; emergency reduce-only close initiated."
                    self._save_state()
                    self._demo_exit_position("PROTECTIVE STOP MISSING", full_close=True)
                    return False
                local_demo_position["stop_algo_id"] = str(live_stop["algoId"])
            self._demo_instrument = instrument
            self.demo_equity = self.okx_demo_client.usdt_equity()
            if self.demo_initial_equity is None:
                self.demo_initial_equity = self.demo_equity
            self._demo_equity_updated = time.time()
            self.demo_ready = self.demo_equity > 0
            self._demo_last_position_check = self._demo_equity_updated
            self.demo_preflight_status = "OKX demo account, net mode, instrument sizing, leverage, and position state verified."
            return self.demo_ready
        except Exception as exc:
            self.demo_ready = False
            self.demo_preflight_status = f"Demo preflight failed ({type(exc).__name__}); entries fail closed."
            self._log_once("demo_preflight", self.demo_preflight_status)
            return False

    @staticmethod
    def _decimal_to_step(value, step, rounding=ROUND_DOWN):
        value_d = Decimal(str(value))
        step_d = Decimal(str(step))
        if step_d <= 0:
            raise ValueError("step must be positive")
        return (value_d / step_d).to_integral_value(rounding=rounding) * step_d

    @staticmethod
    def _decimal_text(value):
        text = format(Decimal(value).normalize(), "f")
        return text if text else "0"

    def _demo_contract_quantity(self, notional_usd, price):
        meta = self._demo_instrument
        if not meta:
            return None, 0.0, "instrument metadata unavailable"
        ct_val = Decimal(str(meta["ctVal"]))
        ccy = str(meta["ctValCcy"]).upper()
        price_d = Decimal(str(price))
        unit_notional = ct_val * price_d if ccy == "BTC" else ct_val
        if unit_notional <= 0:
            return None, 0.0, "contract notional metadata invalid"
        lot = Decimal(str(meta["lotSz"]))
        minimum = Decimal(str(meta["minSz"]))
        raw = Decimal(str(notional_usd)) / unit_notional
        contracts = self._decimal_to_step(raw, lot, ROUND_DOWN)
        if contracts < minimum:
            return None, 0.0, "minimum contract size exceeds the configured risk/margin cap"
        actual_notional = float(contracts * unit_notional)
        return contracts, actual_notional, ""

    def _demo_stop_price(self, price, side):
        tick = Decimal(str(self._demo_instrument["tickSz"]))
        mode = ROUND_DOWN if side == "LONG" else ROUND_UP
        return self._decimal_text(self._decimal_to_step(price, tick, mode))

    def _load_public_instrument_metadata(self, symbol="BTC-USDT-SWAP"):
        if symbol != "BTC-USDT-SWAP":
            return None
        if self._demo_instrument and self._demo_instrument.get("instId") == symbol:
            return self._demo_instrument
        try:
            url = "https://www.okx.com/api/v5/public/instruments?" + urllib.parse.urlencode({"instType": "SWAP", "instId": symbol})
            request = urllib.request.Request(url, headers={"User-Agent": "OKXStrategyScanner/3.0"})
            with urllib.request.urlopen(request, timeout=8.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            data = payload.get("data", []) if payload.get("code") == "0" else []
            if len(data) != 1 or data[0].get("state") != "live":
                raise ValueError("OKX did not return one live BTC swap instrument")
            instrument = data[0]
            for key in ("ctVal", "ctValCcy", "lotSz", "minSz", "tickSz"):
                if instrument.get(key) in (None, ""):
                    raise ValueError("OKX instrument sizing metadata is incomplete")
            if any(Decimal(str(instrument[key])) <= 0 for key in ("ctVal", "lotSz", "minSz", "tickSz")):
                raise ValueError("OKX instrument sizing metadata is invalid")
            self._demo_instrument = instrument
            return instrument
        except Exception as exc:
            self._log_once("instrument_metadata", f"OKX instrument sizing metadata unavailable ({type(exc).__name__}); entries remain blocked.")
            return None

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

    @staticmethod
    def calculate_adx(candles, period=14):
        """Wilder's ADX from OHLC candles; returns None until enough history exists."""
        if len(candles) < (2 * period + 1):
            return None
        tr_values, plus_dm, minus_dm = [], [], []
        for i in range(1, len(candles)):
            high, low = candles[i]["high"], candles[i]["low"]
            prev_high, prev_low = candles[i - 1]["high"], candles[i - 1]["low"]
            prev_close = candles[i - 1]["close"]
            up_move = high - prev_high
            down_move = prev_low - low
            tr_values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

        smooth_tr = sum(tr_values[:period])
        smooth_plus = sum(plus_dm[:period])
        smooth_minus = sum(minus_dm[:period])
        dx_values = []
        for i in range(period - 1, len(tr_values)):
            if i > period - 1:
                smooth_tr = smooth_tr - smooth_tr / period + tr_values[i]
                smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
                smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]
            if smooth_tr <= 0:
                dx_values.append(0.0)
                continue
            plus_di = 100.0 * smooth_plus / smooth_tr
            minus_di = 100.0 * smooth_minus / smooth_tr
            denominator = plus_di + minus_di
            dx_values.append(100.0 * abs(plus_di - minus_di) / denominator if denominator else 0.0)

        if len(dx_values) < period:
            return None
        adx = sum(dx_values[:period]) / period
        for dx in dx_values[period:]:
            adx = ((adx * (period - 1)) + dx) / period
        return max(0.0, min(100.0, adx))

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
        adx = self.calculate_adx(candles, period=14)

        if adx is None:
            self.market_regime = "↔ ADX WARMING UP (need at least 29 candles)"
        elif adx < 20:
            self.market_regime = f"↔ RANGING (ADX {adx:.1f} < 20)"
        else:
            self.market_regime = f"↗ TRENDING (ADX {adx:.1f} ≥ 20)"

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

    def _confluence_components(self, ind=None, symbol=None):
        """Return the original three directional pillars: trigger, VWAP location, and RSI."""
        if not ind:
            return {"LONG": [], "SHORT": []}
        close = ind["current_close"]
        rsi = ind["rsi"]
        long_checks, short_checks = [], []

        long_sweep = (
            ind["current_low"] <= min(ind["recent_low"], ind["vwap_lower"])
            and close > ind["recent_low"]
        )
        short_sweep = (
            ind["current_high"] >= max(ind["recent_high"], ind["vwap_upper"])
            and close < ind["recent_high"]
        )
        long_ema = (
            ind["ema8"] > ind["ema20"] > ind["ema50"]
            and close >= ind["ema50"]
            and close <= ind["ema20"] * 1.002
        )
        short_ema = (
            ind["ema8"] < ind["ema20"] < ind["ema50"]
            and close <= ind["ema50"]
            and close >= ind["ema20"] * 0.998
        )

        # Pillar 1: liquidity-sweep rejection OR EMA-ribbon pullback/rally; counts once.
        if long_sweep:
            long_checks.append("Pillar 1 — liquidity-sweep rejection")
        elif long_ema:
            long_checks.append("Pillar 1 — bullish EMA-ribbon pullback")
        if short_sweep:
            short_checks.append("Pillar 1 — liquidity-sweep rejection")
        elif short_ema:
            short_checks.append("Pillar 1 — bearish EMA-ribbon rally")

        # Pillar 2: location at the appropriate outer VWAP band.
        if close <= ind["vwap_lower"]:
            long_checks.append("Pillar 2 — price at/below lower VWAP band")
        elif close >= ind["vwap_upper"]:
            short_checks.append("Pillar 2 — price at/above upper VWAP band")

        # Pillar 3: directional momentum thresholds from the original playbook.
        if rsi < 42:
            long_checks.append(f"Pillar 3 — RSI momentum low ({rsi:.1f} < 42)")
        elif rsi > 58:
            short_checks.append(f"Pillar 3 — RSI momentum high ({rsi:.1f} > 58)")

        return {"LONG": long_checks, "SHORT": short_checks}

    def _required_confluence(self, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        asian = now_utc.hour >= 22 or now_utc.hour < 6
        # The 3/3 threshold applies in regular hours as well as the Asian window.
        return 3, asian

    def _candidate_block_reasons(self, ind, symbol, side, score, required, now=None):
        reasons = []
        if score < required:
            reasons.append(f"session/config gate needs {required}/3")
        h1_trend = self.multi_1h_trend.get(symbol, "NEUTRAL")
        funding_rate = self.multi_funding.get(symbol, 0.0)
        if self.enable_mtf_filter:
            if side == "LONG" and "BEARISH" in h1_trend:
                reasons.append("opposes 1H bearish flow")
            elif side == "SHORT" and "BULLISH" in h1_trend:
                reasons.append("opposes 1H bullish flow")
        if self.enable_funding_shield:
            if side == "LONG" and funding_rate > 0.00025:
                reasons.append("crowded-long funding shield")
            elif side == "SHORT" and funding_rate < -0.00025:
                reasons.append("crowded-short funding shield")
        if self.enable_circuit_breaker and ind.get("atr14", 0) > 0:
            if ind.get("latest_range", 0) > 3.5 * ind["atr14"]:
                reasons.append("volatility circuit breaker")
            if time.time() < self.circuit_breaker_until.get(symbol, 0):
                reasons.append("15-minute volatility cooldown")
        if self.daily_loss_pause:
            reasons.append(self.daily_pause_reason or "daily loss guard paused entries")
        if self.open_position is not None:
            reasons.append("another position is open")
        return reasons

    def get_confluence_candidates(self, now=None):
        """Build read-only 2/3 watch candidates and 3/3 entry-eligible setups."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._refresh_daily_guard(now=now)
        required, _ = self._required_confluence(now)
        candidates = []
        with self.lock:
            for symbol in self.supported_symbols:
                ind = self.multi_indicators.get(symbol)
                if not ind:
                    continue
                components = self._confluence_components(ind, symbol)
                for side in ("LONG", "SHORT"):
                    confirmations = components[side]
                    score = len(confirmations)
                    if score < 2:
                        continue
                    reasons = self._candidate_block_reasons(ind, symbol, side, score, required, now)
                    candidates.append({
                        "symbol": symbol,
                        "side": side,
                        "score": score,
                        "tier": f"{score}/3",
                        "confirmations": confirmations,
                        "eligible": len(reasons) == 0,
                        "block_reasons": reasons,
                        "required": required,
                    })
        return sorted(candidates, key=lambda c: (not c["eligible"], -c["score"], c["symbol"]))

    def evaluate_strategy_signals(self, ind, symbol="BTC-USDT-SWAP", now=None, vote_data=None,
                                  candles_1m=None, candles_5m=None, candles_15m=None):
        """Evaluate the original three-pillar rules on a confirmed 5m candle.

        The legacy vote arguments remain accepted for compatibility, but are ignored;
        no four-vote or global ADX gate participates in this strategy.
        """
        if not ind:
            return None
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if not self._refresh_daily_guard(now=now):
            return None

        if self.enable_circuit_breaker:
            cb_until = self.circuit_breaker_until.get(symbol, 0)
            if time.time() < cb_until:
                return None
            atr = ind.get("atr14", 0.0)
            if atr > 0 and ind.get("latest_range", 0.0) > (3.5 * atr):
                self.circuit_breaker_until[symbol] = time.time() + 900
                self.add_log(f"VOLATILITY CIRCUIT BREAKER for {symbol}; entries paused for 15 minutes.")
                return None

        required, is_asian_session = self._required_confluence(now)
        components = self._confluence_components(ind, symbol)
        candidate_sides = []
        for side in ("LONG", "SHORT"):
            confirmations = components[side]
            score = len(confirmations)
            if score < 2:
                continue
            blockers = self._candidate_block_reasons(ind, symbol, side, score, required, now)
            if not blockers:
                candidate_sides.append((side, confirmations, score))

        # Contradictory simultaneous directions are not a tradable setup.
        if len(candidate_sides) != 1:
            return None

        side, confirmations, score = candidate_sides[0]
        close = float(ind["current_close"])
        atr14 = float(ind["atr14"])
        if close <= 0 or atr14 <= 0:
            return None
        sl_dist = max(1.8 * atr14, close * 0.006)
        tp1_dist = max(2.2 * atr14, close * 0.009)
        tp2_dist = max(3.8 * atr14, close * 0.016)
        if side == "LONG":
            sl_price = close - sl_dist
            tp1_price = close + tp1_dist
            tp2_price = close + tp2_dist
        else:
            sl_price = close + sl_dist
            tp1_price = close - tp1_dist
            tp2_price = close - tp2_dist

        funding_rate = self.multi_funding.get(symbol, 0.0)
        h1_trend = self.multi_1h_trend.get(symbol, "NEUTRAL")
        bar_close_ms = (int(candles_5m[-1]["ts"]) + 5 * 60_000) if candles_5m else None
        return {
            "symbol": symbol,
            "side": side,
            "reason": f"{score}/3 confluence",
            "confirmations": confirmations,
            "confluence_score": score,
            "entry": close,
            "sl": sl_price,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "rrr": abs(tp2_price - close) / (sl_dist + 1e-9),
            "mtf_status": h1_trend,
            "funding_status": f"Funding {funding_rate * 100:+.4f}% (within configured shield)",
            "session_status": f"{'Asian' if is_asian_session else 'Regular'} session (3/3 required)",
            "adx": ind.get("adx"),
            "bar_close_ms": bar_close_ms,
        }

    def _submit_demo_market_order(self, side, contracts, client_order_id, reduce_only=False, stop_px=None):
        """Submit once, then reconcile by client id on uncertainty; never blindly retry."""
        client = self.okx_demo_client
        try:
            detail = client.place_market_order(
                "BTC-USDT-SWAP", side, str(contracts), client_order_id,
                reduce_only=reduce_only, stop_px=stop_px,
            )
        except Exception:
            try:
                detail = client.order_by_client_id("BTC-USDT-SWAP", client_order_id)
            except Exception:
                return None, [], "order outcome is ambiguous; client-id reconciliation failed"
            if not detail:
                return None, [], "order outcome is ambiguous; no safe retry will be attempted"
        order_id = str(detail.get("ordId", ""))
        if order_id:
            try:
                detail = client.order("BTC-USDT-SWAP", order_id)
            except Exception:
                # A successful POST response remains usable, but the fill must still be confirmed below.
                pass
        state = str(detail.get("state", "")).lower()
        if state in {"live", "partially_filled"}:
            try:
                client.cancel_order("BTC-USDT-SWAP", order_id, client_order_id if not order_id else None)
            except Exception:
                pass
            try:
                refreshed = client.order("BTC-USDT-SWAP", order_id) if order_id else client.order_by_client_id("BTC-USDT-SWAP", client_order_id)
                if refreshed:
                    detail = refreshed
            except Exception:
                return detail, [], "order fill/cancel state is ambiguous"
        fills = []
        if order_id:
            try:
                fills = client.fills("BTC-USDT-SWAP", order_id)
            except Exception:
                fills = []
        return detail, fills, ""

    def _demo_fill_summary(self, detail, fills, reference_price):
        filled_size = sum(float(f.get("fillSz", 0.0) or 0.0) for f in fills)
        weighted_value = sum(float(f.get("fillSz", 0.0) or 0.0) * float(f.get("fillPx", 0.0) or 0.0) for f in fills)
        average_price = weighted_value / filled_size if filled_size > 0 else float(detail.get("avgPx", 0.0) or 0.0)
        if filled_size <= 0:
            filled_size = float(detail.get("accFillSz", 0.0) or 0.0)
        if average_price <= 0:
            average_price = float(reference_price or 0.0)
        fees = 0.0
        fees_complete = bool(fills)
        for fill in fills:
            if "fee" not in fill or not fill.get("feeCcy"):
                fees_complete = False
                break
            amount = abs(float(fill.get("fee", 0.0) or 0.0))
            fee_ccy = str(fill.get("feeCcy", "")).upper()
            if fee_ccy in {"USDT", "USD", "USDC"}:
                fees += amount
            elif fee_ccy == "BTC":
                fees += amount * float(fill.get("fillPx", average_price) or average_price)
            else:
                fees_complete = False
                break
        return {"filled_size": filled_size, "average_price": average_price,
                "fees_usd": fees if fees_complete else None,
                "fees_source": "OKX fills" if fees_complete else "fee estimate; fill fee unavailable",
                "fills": fills}

    def _demo_unit_notional(self, price):
        meta = self._demo_instrument or {}
        ct_val = float(meta.get("ctVal", 0.0) or 0.0)
        ccy = str(meta.get("ctValCcy", "")).upper()
        if ccy == "BTC":
            return ct_val * float(price)
        if ccy in {"USDT", "USD"}:
            return ct_val
        return 0.0

    def _validate_signal_confluence(self, signal):
        try:
            score = int(signal.get("confluence_score", 0))
        except (TypeError, ValueError):
            return False, "Entry rejected: invalid three-pillar score."
        confirmations = signal.get("confirmations")
        required, _ = self._required_confluence()
        if score not in (2, 3) or score < required:
            return False, f"Entry rejected: the current session requires at least {required}/3 pillars."
        if not isinstance(confirmations, list) or len(confirmations) != score:
            return False, "Entry rejected: pillar confirmations do not match the stated score."
        return True, ""

    def _execute_demo_trade_signal(self, signal, symbol):
        if symbol != "BTC-USDT-SWAP":
            return False, "Demo entry rejected: only BTC-USDT-SWAP is configured."
        confluence_ok, confluence_error = self._validate_signal_confluence(signal)
        if not confluence_ok:
            return False, "Demo " + confluence_error
        if signal.get("side") not in {"LONG", "SHORT"}:
            return False, "Demo entry rejected: invalid trade side."
        if not self.demo_orders_armed:
            self.demo_preflight_status = "Demo order arm is off; no private order request was sent."
            return False, self.demo_preflight_status
        if not self._refresh_daily_guard():
            return False, "Daily risk guard is paused; no demo entry opened."
        if not self._ensure_demo_ready():
            return False, self.demo_preflight_status

        with self.lock:
            if self.demo_halted or self._pending_demo_entry is not None:
                return False, "Demo execution is halted or has an unresolved order intent."
            if self.open_position is not None:
                return False, "One-position-at-a-time guard blocked the demo entry."

        try:
            remote_positions = self.okx_demo_client.positions("BTC-USDT-SWAP")
        except Exception as exc:
            self.demo_halted = True
            self.demo_preflight_status = f"Could not reconcile demo positions ({type(exc).__name__}); entries halted."
            self._save_state()
            return False, self.demo_preflight_status
        if remote_positions:
            self.demo_halted = True
            self.demo_external_position = remote_positions[0]
            self.demo_preflight_status = "An exchange position appeared before entry; manual reconciliation required."
            self._save_state()
            return False, self.demo_preflight_status

        try:
            equity = float(self.okx_demo_client.usdt_equity())
            quote = float(signal.get("execution_price", self.ticker_data.get("last", 0.0)))
            signal_price = float(signal.get("signal_bar_close_price", signal.get("entry", 0.0)))
            side = signal["side"]
            stop = float(signal["sl"])
            tp1 = float(signal["tp1"])
            tp2 = float(signal["tp2"])
            if equity <= 0 or quote <= 0:
                return False, "Demo entry rejected: account equity or fresh quote is unavailable."
            slip = max(0.0, float(self.slippage_bps)) / 10_000.0
            estimated_entry = quote * (1.0 + slip if side == "LONG" else 1.0 - slip)
            if (side == "LONG" and not stop < estimated_entry < tp1) or (side == "SHORT" and not tp1 < estimated_entry < stop):
                return False, "Demo entry rejected: quote has moved through a stop/TP1 level."
            risk_pct = min(max(float(self.risk_pct), 0.0), 1.0)
            risk_budget = equity * risk_pct / 100.0
            fee_reserve = 2.0 * float(self.fee_rate)
            slippage_reserve = slip  # adverse entry is already embedded in estimated_entry
            loss_fraction = abs(estimated_entry - stop) / estimated_entry + fee_reserve + slippage_reserve
            if loss_fraction <= 0 or risk_budget <= 0:
                return False, "Demo entry rejected: risk sizing is non-positive."
            desired_notional = min(risk_budget / loss_fraction, self.margin_cap_usd * int(self.leverage))
            quantity, actual_notional, quantity_error = self._demo_contract_quantity(desired_notional, estimated_entry)
            if quantity is None:
                self.demo_preflight_status = quantity_error
                self._log_once("demo_min_contract", f"Demo setup skipped: {quantity_error}.")
                return False, quantity_error
            actual_risk = actual_notional * loss_fraction
            margin = actual_notional / max(1, int(self.leverage))
            if actual_risk > risk_budget + 1e-8 or margin > self.margin_cap_usd + 1e-8:
                return False, "Demo entry rejected: rounded contract size breaches risk or $3 margin cap."

            lot = Decimal(str(self._demo_instrument["lotSz"]))
            minimum = Decimal(str(self._demo_instrument["minSz"]))
            half_quantity = self._decimal_to_step(quantity / Decimal("2"), lot, ROUND_DOWN)
            if half_quantity < minimum or half_quantity >= quantity:
                return False, "Demo entry skipped: minimum contract sizing cannot support the approved 50% TP1 partial exit."
            stop_px = self._demo_stop_price(stop, side)
            client_order_id = uuid.uuid4().hex[:30]
            stop_client_id = (client_order_id + "S")[:32]
            entry_time = datetime.now(LAGOS_TZ).strftime("%Y-%m-%d %H:%M:%S")
            intent = {
                "client_order_id": client_order_id,
                "stop_client_id": stop_client_id,
                "symbol": symbol,
                "side": side,
                "contracts": self._decimal_text(quantity),
                "stop_px": stop_px,
                "created_at_epoch": time.time(),
                "signal": signal,
                "risk_budget_usd": risk_budget,
            }
            with self.lock:
                self._pending_demo_entry = intent
                self._save_state()

            detail, fills, order_error = self._submit_demo_market_order(
                "buy" if side == "LONG" else "sell", self._decimal_text(quantity),
                client_order_id, reduce_only=False, stop_px=stop_px,
            )
            if not detail or order_error:
                self.demo_halted = True
                self.demo_preflight_status = f"Demo entry order unresolved: {order_error or 'no order response'}. No retry will be sent."
                self._save_state()
                return False, self.demo_preflight_status

            fill = self._demo_fill_summary(detail, fills, estimated_entry)
            fill_size = float(fill["filled_size"])
            if fill_size <= 0:
                state = str(detail.get("state", "")).lower()
                if state in {"canceled", "cancelled", "order_failed"}:
                    self._pending_demo_entry = None
                    self._save_state()
                    return False, f"Demo entry was not filled (state={state}); no position opened."
                self.demo_halted = True
                self.demo_preflight_status = "Demo entry fill is unconfirmed; client-id reconciliation required."
                self._save_state()
                return False, self.demo_preflight_status

            try:
                current_positions = self.okx_demo_client.positions("BTC-USDT-SWAP")
            except Exception:
                current_positions = []
            if not current_positions:
                self.demo_halted = True
                self.demo_preflight_status = "Entry fill reported but position is not yet visible; order intent retained and entries halted."
                self._save_state()
                return False, self.demo_preflight_status
            remote = current_positions[0]
            actual_side = "LONG" if float(remote.get("pos", 0.0)) > 0 else "SHORT"
            actual_contracts = abs(float(remote.get("pos", 0.0)))
            entry_price = float(fill["average_price"] or remote.get("avgPx", 0.0) or 0.0)
            if actual_side != side or actual_contracts <= 0 or entry_price <= 0:
                self.demo_halted = True
                self.demo_external_position = remote
                self.demo_preflight_status = "Exchange fill/position mismatch; entries halted for manual reconciliation."
                self._save_state()
                return False, self.demo_preflight_status

            actual_notional = actual_contracts * self._demo_unit_notional(entry_price)
            if actual_notional <= 0:
                self.demo_halted = True
                self.demo_preflight_status = "Could not value the demo position from runtime contract metadata."
                self._save_state()
                return False, self.demo_preflight_status
            fees = fill["fees_usd"]
            fees_are_estimated = fees is None
            if fees_are_estimated:
                fees = actual_notional * self.fee_rate
            entry_slip = max(0.0, ((entry_price / quote - 1.0) if side == "LONG" else (1.0 - entry_price / quote)))
            stop_value = float(stop_px)
            actual_loss_fraction = abs(entry_price - stop_value) / entry_price + 2.0 * self.fee_rate + slip
            actual_initial_risk = actual_notional * actual_loss_fraction
            pos = {
                "id": int(time.time() * 1000), "symbol": symbol, "side": side,
                "strategy": self.active_strategy, "execution_mode": "okx_demo",
                "entry_price": entry_price, "signal_bar_close_price": signal_price,
                "entry_quote_price": quote, "entry_time": entry_time,
                "opened_at_epoch": time.time(), "entry_bar_close_ms": signal.get("bar_close_ms"),
                "entry_order_id": str(detail.get("ordId", "")), "client_order_id": client_order_id,
                "contracts": actual_contracts, "initial_contracts": actual_contracts,
                "remaining_contracts": actual_contracts, "ct_val": self._demo_instrument["ctVal"],
                "ct_val_ccy": self._demo_instrument["ctValCcy"], "position_notional": actual_notional,
                "margin": actual_notional / max(1, int(self.leverage)), "leverage": int(self.leverage),
                "sl_price": stop_value, "initial_sl_price": stop_value,
                "tp1_price": tp1, "tp2_price": tp2, "tp1_hit": False,
                "remaining_size_pct": 1.0, "total_fees": float(fees),
                "entry_fee_source": fill["fees_source"], "fees_are_estimated": fees_are_estimated,
                "realized_gross_pnl": 0.0, "funding_cashflow_usd": 0.0,
                "funding_source": "no settled funding bill observed", "funding_bill_ids": [],
                "last_funding_ts": 0, "last_funding_bill_poll_epoch": 0.0,
                "slippage_cost_est_usd": actual_notional * entry_slip,
                "slippage_bps": self.slippage_bps, "fee_rate": self.fee_rate,
                "risk_pct": risk_pct, "risk_budget_usd": risk_budget,
                "planned_initial_risk_usd": actual_initial_risk, "adx_5m": signal.get("adx"),
                "confluence_score": int(signal.get("confluence_score", 0)),
                "strategy_votes": dict(signal.get("strategy_votes", {})),
                "confirmations": list(signal.get("confirmations", [])),
                "stop_client_id": stop_client_id, "stop_algo_id": "",
                "exit_order_ids": [],
                "last_exit_mark_price": quote,
            }
            self.open_position = pos
            self._pending_demo_entry = None
            self.demo_equity = float(self.okx_demo_client.usdt_equity())
            self._demo_equity_updated = time.time()
            signal["entry"] = entry_price
            self.signals.append({
                "time": entry_time, "symbol": symbol, "side": side, "strategy": self.active_strategy,
                "confluence_score": pos["confluence_score"], "entry": entry_price,
                "sl": stop_value, "tp1": tp1, "tp2": tp2,
                "reason": signal.get("reason", f"{score}/3 confluence"),
                "strategy_votes": pos["strategy_votes"], "entry_order_id": pos["entry_order_id"],
            })
            self._append_trade_log_event("ENTRY", pos, {
                "signal": signal, "entry_order": detail, "entry_fills": fill["fills"],
                "fees_source": fill["fees_source"], "fees_are_estimated": fees_are_estimated,
                "risk_budget_usd": risk_budget, "planned_initial_risk_usd": actual_initial_risk,
                "contract_metadata": {k: self._demo_instrument.get(k) for k in ("ctVal", "ctValCcy", "lotSz", "minSz", "tickSz")},
            })
            for fill_row in fill["fills"]:
                self._append_trade_log_event("FILL", pos, {
                    "order_id": pos["entry_order_id"], "fill": fill_row, "leg": "ENTRY",
                })
            self._save_state()

            try:
                stop_algo = self.okx_demo_client.find_algo(symbol, stop_client_id)
            except Exception:
                stop_algo = None
            if stop_algo is None:
                attached = detail.get("attachAlgoOrds", [])
                if attached:
                    stop_algo = next((x for x in attached if x.get("attachAlgoClOrdId") == stop_client_id), None)
            if not stop_algo or not stop_algo.get("algoId"):
                self.demo_halted = True
                self.demo_preflight_status = "Demo position opened but attached stop was not confirmed; emergency reduce-only close initiated."
                self._save_state()
                self._demo_exit_position("PROTECTIVE STOP UNCONFIRMED", full_close=True, current_price=quote)
                return False, self.demo_preflight_status

            try:
                attached_stop = float(stop_algo.get("slTriggerPx", stop_value))
                tick = float(self._demo_instrument["tickSz"])
                if abs(attached_stop - stop_value) > tick + 1e-9 or str(stop_algo.get("state", "live")).lower() in {"canceled", "order_failed"}:
                    raise OKXDemoError("Attached stop is not live at the approved price.")
                pos["stop_algo_id"] = str(stop_algo["algoId"])
            except Exception:
                self.demo_halted = True
                self.demo_preflight_status = "Attached protective stop price/state mismatch; emergency reduce-only close initiated."
                self._save_state()
                self._demo_exit_position("PROTECTIVE STOP INVALID", full_close=True, current_price=quote)
                return False, self.demo_preflight_status

            self.demo_preflight_status = "Demo entry filled; attached protective stop verified."
            self._save_state()
            if actual_initial_risk > risk_budget + 1e-8:
                self.demo_halted = True
                self.demo_preflight_status = "Actual fill exceeded the 1% planned risk cap; emergency reduce-only close initiated."
                self._save_state()
                self._demo_exit_position("RISK CAP BREACH AFTER FILL", full_close=True, current_price=quote)
                return False, self.demo_preflight_status
        except Exception as exc:
            self.demo_halted = True
            self.demo_preflight_status = f"Demo order lifecycle error ({type(exc).__name__}); entries halted for reconciliation."
            self._save_state()
            return False, self.demo_preflight_status

        return True, "OKX demo position opened; attached protective stop verified. No live endpoint is available."

    def _apply_demo_funding(self, pos, now_ms):
        """Reconcile settled funding from private account bills, not a public-rate proxy."""
        now_epoch = now_ms / 1000.0
        if now_epoch - float(pos.get("last_funding_bill_poll_epoch", 0.0)) < 60.0:
            return
        begin_ms = int(float(pos.get("opened_at_epoch", 0.0)) * 1000)
        try:
            bills = self.okx_demo_client.account_bills("BTC-USDT-SWAP", begin_ms=begin_ms, end_ms=now_ms)
            if now_ms - begin_ms > 6 * 24 * 60 * 60_000:
                bills += self.okx_demo_client.account_bills_archive("BTC-USDT-SWAP", begin_ms=begin_ms, end_ms=now_ms)
        except Exception as exc:
            self._log_once("demo_funding_bills", f"OKX demo funding bills unavailable ({type(exc).__name__}); funding PnL is marked unverified.")
            pos["funding_source"] = "unverified; account bills unavailable"
            return
        seen = set(str(x) for x in pos.get("funding_bill_ids", []))
        changed = False
        for bill in bills:
            subtype = str(bill.get("subType", ""))
            bill_id = str(bill.get("billId", ""))
            ts = int(bill.get("ts", 0) or 0)
            if subtype not in {"173", "174"} or not bill_id or bill_id in seen or ts < begin_ms:
                continue
            amount = float(bill.get("balChg", 0.0) or 0.0)
            currency = str(bill.get("ccy", "USDT")).upper()
            if currency == "BTC":
                amount *= float(bill.get("px", 0.0) or pos.get("current_price", pos.get("entry_price", 0.0)))
            elif currency not in {"USDT", "USD", "USDC"}:
                pos["funding_source"] = f"unconverted funding currency {currency}"
                continue
            pos["funding_cashflow_usd"] = float(pos.get("funding_cashflow_usd", 0.0)) + amount
            pos.setdefault("funding_bill_ids", []).append(bill_id)
            pos["last_funding_ts"] = max(int(pos.get("last_funding_ts", 0)), ts)
            seen.add(bill_id)
            changed = True
            self._append_trade_log_event("FUNDING_BILL", pos, {
                "bill_id": bill_id, "funding_ts_ms": ts, "sub_type": subtype,
                "cashflow_usd": amount, "currency": currency, "source": "OKX demo account bills",
            })
        pos["last_funding_bill_poll_epoch"] = now_epoch
        pos["funding_source"] = "OKX demo account bills" if changed or seen else pos.get("funding_source", "no settled funding bill observed")
        if changed or pos.get("last_funding_bill_poll_epoch"):
            self._save_state()

    def _finalize_demo_trade(self, reason, exit_price, exit_source="exchange fill"):
        pos = self.open_position
        if not pos or pos.get("execution_mode") != "okx_demo":
            return False
        net = float(pos.get("realized_gross_pnl", 0.0)) - float(pos.get("total_fees", 0.0)) + float(pos.get("funding_cashflow_usd", 0.0))
        planned_risk = max(float(pos.get("planned_initial_risk_usd", 0.0)), 1e-12)
        exit_time = datetime.now(LAGOS_TZ).strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": pos.get("id"), "symbol": pos.get("symbol"), "side": pos.get("side"),
            "strategy": pos.get("strategy"), "execution_mode": "okx_demo",
            "entry_price": pos.get("entry_price"), "exit_price": exit_price,
            "position_notional": pos.get("position_notional"), "contracts": pos.get("initial_contracts"),
            "leverage": pos.get("leverage"), "risk_pct": pos.get("risk_pct"),
            "risk_budget_usd": pos.get("risk_budget_usd"), "planned_initial_risk_usd": planned_risk,
            "gross_pnl": round(float(pos.get("realized_gross_pnl", 0.0)), 6),
            "net_pnl": round(net, 6), "R_net": round(net / planned_risk, 6),
            "fees": round(float(pos.get("total_fees", 0.0)), 6),
            "funding_cashflow_usd": round(float(pos.get("funding_cashflow_usd", 0.0)), 6),
            "funding_source": pos.get("funding_source", "unavailable"),
            "slippage_est_usd": round(float(pos.get("slippage_cost_est_usd", 0.0)), 6),
            "entry_time": pos.get("entry_time"), "exit_time": exit_time,
            "close_reason": reason, "exit_price_source": exit_source, "win": net > 0,
            "confluence_score": pos.get("confluence_score", 0), "adx_5m": pos.get("adx_5m"),
            "entry_bar_close_ms": pos.get("entry_bar_close_ms"), "tp1_hit": pos.get("tp1_hit", False),
            "initial_stop": pos.get("initial_sl_price"), "final_stop": pos.get("sl_price"),
            "tp1_price": pos.get("tp1_price"), "tp2_price": pos.get("tp2_price"),
            "strategy_votes": pos.get("strategy_votes", {}), "confirmations": pos.get("confirmations", []),
            "entry_order_id": pos.get("entry_order_id"), "exit_order_ids": pos.get("exit_order_ids", []),
            "stop_algo_id": pos.get("stop_algo_id"),
        }
        self.closed_trades.append(record)
        self._append_trade_log_event("EXIT", pos, {
            "exit_price": exit_price, "exit_time": exit_time, "close_reason": reason,
            "exit_source": exit_source, "gross_pnl_usd": record["gross_pnl"],
            "net_pnl_usd": net, "R_net": record["R_net"], "fees_usd": record["fees"],
            "funding_cashflow_usd": record["funding_cashflow_usd"],
            "funding_source": record["funding_source"],
            "slippage_est_usd": record["slippage_est_usd"],
        })
        self.open_position = None
        self._pending_demo_entry = None
        self._record_trade_outcome(net)
        try:
            self.demo_equity = float(self.okx_demo_client.usdt_equity())
            self._demo_equity_updated = time.time()
        except Exception:
            pass
        self._refresh_daily_guard()
        self._save_state()
        self.add_log(f"OKX DEMO CLOSED {record['side']} ({reason}) @ {exit_price}; net ${net:+.4f}, R={record['R_net']:+.3f}.")
        return True

    def _demo_exit_position(self, reason, full_close=False, current_price=None):
        pos = self.open_position
        if not pos or pos.get("execution_mode") != "okx_demo":
            return False
        client = self.okx_demo_client
        try:
            positions = client.positions("BTC-USDT-SWAP")
        except Exception as exc:
            self.demo_halted = True
            self.demo_preflight_status = f"Demo exit position check failed ({type(exc).__name__}); entries halted."
            self._save_state()
            return False
        if not positions:
            return self._reconcile_demo_closed_position(current_price=current_price)
        remote = positions[0]
        remote_qty = abs(float(remote.get("pos", 0.0)))
        if remote_qty <= 0:
            return False
        lot = Decimal(str(self._demo_instrument["lotSz"]))
        minimum = Decimal(str(self._demo_instrument["minSz"]))
        if full_close:
            close_qty = Decimal(str(remote_qty))
        else:
            close_qty = self._decimal_to_step(Decimal(str(float(pos.get("initial_contracts", remote_qty)) / 2.0)), lot, ROUND_DOWN)
            if close_qty < minimum or close_qty >= Decimal(str(remote_qty)):
                self.demo_preflight_status = "TP1 partial size is below exchange lot/minimum; protective stop remains active."
                return False
        close_qty = min(close_qty, Decimal(str(remote_qty)))
        if close_qty < minimum:
            return False
        client_order_id = uuid.uuid4().hex[:30]
        pos["pending_exit_intent"] = {"client_order_id": client_order_id, "reason": reason, "contracts": self._decimal_text(close_qty)}
        self._save_state()
        close_side = "sell" if pos["side"] == "LONG" else "buy"
        detail, fills, error = self._submit_demo_market_order(
            close_side, self._decimal_text(close_qty), client_order_id, reduce_only=True
        )
        if not detail or error:
            self.demo_halted = True
            self.demo_preflight_status = f"Demo reduce-only exit unresolved ({error or 'no order response'}); no retry will be sent."
            self._save_state()
            return False
        fill = self._demo_fill_summary(detail, fills, current_price or pos["entry_price"])
        try:
            after_positions = client.positions("BTC-USDT-SWAP")
        except Exception:
            self.demo_halted = True
            self.demo_preflight_status = "Demo exit submitted but position reconciliation failed; entries halted."
            self._save_state()
            return False
        after_qty = abs(float(after_positions[0].get("pos", 0.0))) if after_positions else 0.0
        before_qty = remote_qty
        filled_qty = float(fill["filled_size"])
        if filled_qty <= 0 and before_qty > after_qty:
            filled_qty = before_qty - after_qty
        if filled_qty <= 0:
            self.demo_halted = True
            self.demo_preflight_status = "Demo exit fill is unconfirmed; no retry will be sent."
            self._save_state()
            return False
        exit_price = float(fill["average_price"] or current_price or pos["entry_price"])
        entry_price = float(pos["entry_price"])
        side = pos["side"]
        closed_notional = filled_qty * self._demo_unit_notional(entry_price)
        signed = (exit_price - entry_price) / entry_price if side == "LONG" else (entry_price - exit_price) / entry_price
        gross = closed_notional * signed
        exit_fee = fill["fees_usd"]
        if exit_fee is None:
            exit_fee = filled_qty * self._demo_unit_notional(exit_price) * self.fee_rate
        pos["realized_gross_pnl"] = float(pos.get("realized_gross_pnl", 0.0)) + gross
        pos["total_fees"] = float(pos.get("total_fees", 0.0)) + float(exit_fee)
        pos.setdefault("exit_order_ids", []).append(str(detail.get("ordId", "")))
        pos["pending_exit_intent"] = None
        reference = float(current_price or exit_price)
        adverse = max(0.0, (reference - exit_price) / reference if side == "LONG" else (exit_price - reference) / reference)
        pos["slippage_cost_est_usd"] = float(pos.get("slippage_cost_est_usd", 0.0)) + closed_notional * adverse
        if after_qty > 0:
            pos["remaining_contracts"] = after_qty
            pos["contracts"] = after_qty
            pos["remaining_size_pct"] = after_qty / max(float(pos.get("initial_contracts", before_qty)), 1e-12)
        self._append_trade_log_event("PARTIAL_EXIT" if after_qty > 0 else "FINAL_EXIT_FILL", pos, {
            "exit_order": detail, "exit_fills": fill["fills"], "exit_price": exit_price,
            "mark_price": current_price, "closed_contracts": filled_qty,
            "gross_pnl_usd": gross, "fees_usd": exit_fee, "fees_source": fill["fees_source"],
            "close_reason": reason,
        })
        for fill_row in fill["fills"]:
            self._append_trade_log_event("FILL", pos, {
                "order_id": str(detail.get("ordId", "")), "fill": fill_row, "leg": reason,
            })
        if after_qty <= 0:
            try:
                if pos.get("stop_algo_id"):
                    client.cancel_algo("BTC-USDT-SWAP", str(pos["stop_algo_id"]))
            except Exception:
                pass
            self.demo_halted = self.demo_halted or reason.startswith("PROTECTIVE STOP") or "RISK CAP" in reason
            return self._finalize_demo_trade(reason, exit_price, fill["fees_source"])

        if reason == "TP1 PARTIAL CLOSE":
            pos["tp1_hit"] = True
            pos["sl_price"] = entry_price * (1.0005 if side == "LONG" else 0.9995)
            try:
                stop_px = self._demo_stop_price(pos["sl_price"], side)
                client.amend_algo_stop("BTC-USDT-SWAP", str(pos["stop_algo_id"]), stop_px)
                pos["sl_price"] = float(stop_px)
                stop_updated = True
            except Exception:
                stop_updated = False
                self.demo_halted = True
                self.demo_preflight_status = "TP1 filled but stop amendment was not confirmed; old exchange stop remains; entries halted."
            self._append_trade_log_event("TP1_PARTIAL_CLOSE", pos, {
                "exit_price": exit_price, "gross_pnl_usd": gross, "net_pnl_usd": gross - float(exit_fee),
                "fees_usd": exit_fee, "stop_after_tp1": pos["sl_price"], "stop_amended": stop_updated,
            })
        elif full_close:
            self.demo_halted = True
            self.demo_preflight_status = "Demo close order partially filled; exchange position remains; entries halted."
        self._save_state()
        if after_qty > 0 and current_price is not None:
            pos["current_price"] = float(current_price)
            signed_remaining = (float(current_price) - entry_price) / entry_price if side == "LONG" else (entry_price - float(current_price)) / entry_price
            pos["unrealized_pnl"] = after_qty * self._demo_unit_notional(entry_price) * signed_remaining
        return after_qty <= 0

    def _reconcile_demo_closed_position(self, current_price=None):
        pos = self.open_position
        if not pos or pos.get("execution_mode") != "okx_demo":
            return False
        client = self.okx_demo_client
        algo = None
        try:
            history = client.algo_history("BTC-USDT-SWAP", pos.get("stop_client_id"))
            algo = history[0] if history else None
        except Exception:
            algo = None
        exit_price = float(algo.get("actualPx", 0.0) or 0.0) if algo else 0.0
        if exit_price <= 0:
            exit_price = float(current_price or pos.get("current_price", pos.get("entry_price", 0.0)))
        remaining = float(pos.get("remaining_contracts", pos.get("contracts", 0.0)))
        entry = float(pos.get("entry_price", 0.0))
        fill_rows = []
        if algo:
            order_ids = list(algo.get("ordIdList", []) or [])
            if algo.get("ordId"):
                order_ids.append(str(algo["ordId"]))
            for order_id in set(str(x) for x in order_ids if x):
                try:
                    fill_rows.extend(client.fills("BTC-USDT-SWAP", order_id))
                except Exception:
                    pass
        summary = self._demo_fill_summary(
            {"avgPx": exit_price, "accFillSz": (algo or {}).get("actualSz", remaining)},
            fill_rows, exit_price,
        )
        closed_qty = float(summary["filled_size"] or remaining)
        exit_price = float(summary["average_price"] or exit_price)
        notional = closed_qty * self._demo_unit_notional(entry)
        signed = (exit_price - entry) / entry if pos.get("side") == "LONG" else (entry - exit_price) / entry
        gross = notional * signed
        pos["realized_gross_pnl"] = float(pos.get("realized_gross_pnl", 0.0)) + gross
        estimated_fee = summary["fees_usd"]
        fees_source = summary["fees_source"]
        if estimated_fee is None:
            estimated_fee = closed_qty * self._demo_unit_notional(exit_price) * self.fee_rate
            fees_source = "estimated; exchange fill fee unavailable"
        pos["total_fees"] = float(pos.get("total_fees", 0.0)) + estimated_fee
        exit_source = "OKX algo/fill history" if algo and (fill_rows or float(algo.get("actualPx", 0.0) or 0.0) > 0) else "mark-price estimate; exchange fill unavailable"
        if algo and float(algo.get("actualSz", 0.0) or 0.0) > 0:
            reason = "STOP LOSS (exchange algo)"
        else:
            reason = "EXCHANGE POSITION CLOSED / RECONCILED"
            self.demo_halted = True
            self.demo_preflight_status = "Demo position closed outside the local manager; reconciliation is estimated and entries halted."
        self._append_trade_log_event("RECONCILED_EXIT", pos, {
            "exit_price": exit_price, "gross_pnl_usd": gross, "fees_usd": estimated_fee,
            "close_reason": reason, "exit_source": exit_source, "fees_source": fees_source,
            "exit_fills": fill_rows,
        })
        for fill_row in fill_rows:
            self._append_trade_log_event("FILL", pos, {
                "order_id": fill_row.get("ordId", ""), "fill": fill_row, "leg": "STOP/RECONCILED EXIT",
            })
        return self._finalize_demo_trade(reason, exit_price, exit_source)

    def _monitor_demo_position(self, current_price=None, now_ts=None):
        now_ts = time.time() if now_ts is None else float(now_ts)
        if self.execution_mode != "okx_demo" or self.okx_demo_client is None:
            if self.open_position and self.open_position.get("execution_mode") == "okx_demo":
                self.demo_halted = True
                self.demo_preflight_status = "Stored demo position exists but demo credentials are unavailable; reconcile manually."
            return
        if not self.demo_ready and not self._ensure_demo_ready(require_armed=False):
            return
        if now_ts - self._demo_last_position_check < 5.0:
            return
        self._demo_last_position_check = now_ts
        try:
            positions = self.okx_demo_client.positions("BTC-USDT-SWAP")
        except Exception as exc:
            self.demo_halted = True
            self.demo_preflight_status = f"Demo position polling failed ({type(exc).__name__}); entries halted."
            self._save_state()
            return
        pos = self.open_position if self.open_position and self.open_position.get("execution_mode") == "okx_demo" else None
        if not positions:
            if pos:
                self._reconcile_demo_closed_position(current_price=current_price)
            return
        remote = positions[0]
        if not pos:
            self.demo_halted = True
            self.demo_external_position = remote
            self.demo_preflight_status = "Untracked OKX demo position detected; entries halted for manual reconciliation."
            self._save_state()
            return
        remote_side = "LONG" if float(remote.get("pos", 0.0)) > 0 else "SHORT"
        remote_qty = abs(float(remote.get("pos", 0.0)))
        if remote_side != pos.get("side") or remote_qty <= 0:
            self.demo_halted = True
            self.demo_preflight_status = "Exchange/local demo position mismatch; entries halted."
            self._save_state()
            return
        pos["remaining_contracts"] = remote_qty
        pos["contracts"] = remote_qty
        pos["remaining_size_pct"] = remote_qty / max(float(pos.get("initial_contracts", remote_qty)), 1e-12)
        if now_ts - float(pos.get("last_stop_check_epoch", 0.0)) >= 30.0:
            pos["last_stop_check_epoch"] = now_ts
            try:
                protective = self.okx_demo_client.find_algo("BTC-USDT-SWAP", pos.get("stop_client_id", ""))
            except Exception:
                protective = None
            if not protective or not protective.get("algoId"):
                self.demo_halted = True
                self.demo_preflight_status = "Protective stop is not visible as live; emergency reduce-only close initiated."
                self._save_state()
                self._demo_exit_position("PROTECTIVE STOP MISSING", full_close=True, current_price=current_price)
                return
            pos["stop_algo_id"] = str(protective["algoId"])
        if current_price is not None and float(current_price) > 0:
            mark = float(current_price)
            pos["current_price"] = mark
            signed = (mark - float(pos["entry_price"])) / float(pos["entry_price"]) if remote_side == "LONG" else (float(pos["entry_price"]) - mark) / float(pos["entry_price"])
            pos["unrealized_pnl"] = remote_qty * self._demo_unit_notional(float(pos["entry_price"])) * signed
            pos["last_exit_mark_price"] = mark
            if not pos.get("tp1_hit") and ((remote_side == "LONG" and mark >= float(pos["tp1_price"])) or (remote_side == "SHORT" and mark <= float(pos["tp1_price"]))):
                self._demo_exit_position("TP1 PARTIAL CLOSE", full_close=False, current_price=mark)
            elif (remote_side == "LONG" and mark >= float(pos["tp2_price"])) or (remote_side == "SHORT" and mark <= float(pos["tp2_price"])):
                self._demo_exit_position("TP2 TARGET", full_close=True, current_price=mark)
            elif not pos.get("tp1_hit") and now_ts - float(pos.get("opened_at_epoch", now_ts)) >= self.stale_trade_seconds:
                self._demo_exit_position("STALE TIME EXIT", full_close=True, current_price=mark)
        if self.open_position is pos:
            self._apply_demo_funding(pos, int(now_ts * 1000))
        if now_ts - self._demo_equity_updated >= 60.0:
            try:
                self.demo_equity = float(self.okx_demo_client.usdt_equity())
                self._demo_equity_updated = now_ts
                self._refresh_daily_guard()
            except Exception:
                self.demo_halted = True
                self.demo_preflight_status = "Demo equity polling failed; new entries halted."

    def execute_trade_signal(self, signal, symbol):
        """Route only to simulated paper or the hard-pinned, preflighted OKX demo path."""
        if self.execution_mode == "okx_demo":
            return self._execute_demo_trade_signal(signal, symbol)
        with self.lock:
            if symbol != "BTC-USDT-SWAP":
                return False, "Entry rejected: only BTC-USDT-SWAP is configured."
            if self.execution_mode != "paper":
                msg = "Execution mode is unsupported; no order was sent."
                self.add_log(msg)
                return False, msg
            if self.demo_halted or self._pending_demo_entry is not None:
                return False, "Unresolved demo state blocks all new entries; reconcile before trading."
            if self.open_position and self.open_position.get("execution_mode") == "okx_demo":
                return False, "An OKX demo position is still tracked; no paper entry may overlap it."
            if not self._refresh_daily_guard():
                return False, "Daily risk guard is paused; no entry opened."
            if self.open_position is not None:
                return False, "One-position-at-a-time guard blocked the entry."

            confluence_ok, confluence_error = self._validate_signal_confluence(signal)
            if not confluence_ok:
                return False, confluence_error
            score = int(signal.get("confluence_score", 0))
            signal_price = float(signal.get("signal_bar_close_price", signal["entry"]))
            quote_price = float(signal.get("execution_price", signal["entry"]))
            sl = float(signal["sl"])
            tp1 = float(signal["tp1"])
            tp2 = float(signal["tp2"])
            side = signal["side"]
            if side not in ("LONG", "SHORT") or quote_price <= 0 or signal_price <= 0:
                return False, "Entry rejected: invalid side or non-positive market price."
            slip_fraction = max(0.0, float(self.slippage_bps)) / 10_000.0
            entry = quote_price * (1.0 + slip_fraction if side == "LONG" else 1.0 - slip_fraction)
            if entry <= 0 or (side == "LONG" and not sl < entry < tp1) or (side == "SHORT" and not tp1 < entry < sl):
                return False, "Entry rejected: market moved through a stop/TP1 level or has invalid stop geometry."
            signal["signal_bar_close_price"] = signal_price
            signal["entry_quote_price"] = quote_price
            signal["entry"] = entry  # modeled market fill after the signal bar closed
            if self.balance <= 0:
                return False, "Entry rejected: non-positive account balance."

            equity_now = self._current_equity()
            sl_dist_pct = abs(entry - sl) / entry
            risk_pct = min(max(float(self.risk_pct), 0.0), 1.0)
            max_risk_amount = equity_now * (risk_pct / 100.0)
            estimated_round_trip_fees_pct = 2.0 * self.fee_rate
            slippage_reserve_pct = self.slippage_bps / 10_000.0  # entry slip is already embedded in the adverse entry price
            effective_loss_pct = sl_dist_pct + estimated_round_trip_fees_pct + slippage_reserve_pct
            if effective_loss_pct <= 0 or max_risk_amount <= 0:
                return False, "Entry rejected: invalid risk sizing."
            if not self._load_public_instrument_metadata(symbol):
                return False, "Entry rejected: runtime OKX contract sizing metadata is unavailable."
            margin_cap = min(float(self.margin_cap_usd), max(0.0, self.balance))
            desired_notional = min(max_risk_amount / effective_loss_pct, margin_cap * max(1, int(self.leverage)))
            quantity, position_notional, quantity_error = self._demo_contract_quantity(desired_notional, entry)
            if quantity is None:
                self.demo_preflight_status = quantity_error
                return False, f"Entry skipped: {quantity_error}."
            lot = Decimal(str(self._demo_instrument["lotSz"]))
            minimum = Decimal(str(self._demo_instrument["minSz"]))
            half_quantity = self._decimal_to_step(quantity / Decimal("2"), lot, ROUND_DOWN)
            if half_quantity < minimum or half_quantity >= quantity:
                return False, "Entry skipped: minimum contract sizing cannot support the approved 50% TP1 partial exit."
            margin_required = position_notional / max(1, int(self.leverage))
            planned_initial_risk = position_notional * effective_loss_pct
            if planned_initial_risk > max_risk_amount + 1e-8:
                return False, "Entry rejected: rounded contract size exceeds the 1% risk cap."

            entry_fee = position_notional * self.fee_rate
            entry_slippage_cost = position_notional * slip_fraction
            if entry_fee >= self.balance:
                return False, "Entry rejected: estimated entry fee exceeds available balance."
            self.balance -= entry_fee
            now = datetime.now(LAGOS_TZ)
            self.open_position = {
                "id": int(time.time() * 1000),
                "symbol": symbol,
                "side": side,
                "strategy": self.active_strategy,
                "entry_price": entry,
                "signal_bar_close_price": signal_price,
                "entry_quote_price": quote_price,
                "entry_slippage_cost_est": entry_slippage_cost,
                "sl_price": float(sl),
                "tp1_price": tp1,
                "tp2_price": tp2,
                "position_notional": position_notional,
                "contracts": float(quantity),
                "margin": margin_required,
                "leverage": int(self.leverage),
                "tp1_hit": False,
                "current_price": entry,
                "unrealized_pnl": 0.0,
                "entry_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "opened_at_epoch": time.time(),
                "candle_count": 0,
                "total_fees": entry_fee,
                "realized_gross_pnl": 0.0,
                "funding_cashflow_usd": 0.0,
                "funding_source": "estimated from OKX settled public rate",
                "last_funding_ts": 0,
                "remaining_size_pct": 1.0,
                "confirmations": list(signal.get("confirmations", [])),
                "strategy_votes": dict(signal.get("strategy_votes", {})),
                "confluence_score": score,
                "adx_5m": signal.get("adx"),
                "entry_bar_close_ms": signal.get("bar_close_ms"),
                "initial_sl_price": float(sl),
                "risk_pct": risk_pct,
                "risk_budget_usd": max_risk_amount,
                "planned_initial_risk_usd": position_notional * effective_loss_pct,
                "fee_rate": self.fee_rate,
                "slippage_bps": self.slippage_bps,
                "slippage_cost_est_usd": entry_slippage_cost,
                "execution_mode": "paper",
                "entry_order_id": "",
                "exit_order_ids": [],
            }
            self.signals.append({
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": symbol,
                "side": side,
                "strategy": self.active_strategy,
                "confluence_score": score,
                "entry": entry,
                "sl": float(sl),
                "tp1": float(signal["tp1"]),
                "tp2": float(signal["tp2"]),
                "reason": signal.get("reason", f"{score}/3 confluence"),
                "strategy_votes": dict(signal.get("strategy_votes", {})),
            })
            self._append_trade_log_event("ENTRY", self.open_position, {
                "entry_signal": signal,
                "risk_sizing": {
                    "risk_pct": risk_pct,
                    "risk_budget_usd": max_risk_amount,
                    "position_notional_usd": position_notional,
                    "margin_usd": margin_required,
                    "estimated_round_trip_fees_pct": estimated_round_trip_fees_pct,
                    "slippage_reserve_pct": slippage_reserve_pct,
                    "equity_at_entry_usd": equity_now,
                },
            })
            self.add_log(
                f"PAPER OPEN {score}/3 {side} {symbol} @ ${self.format_price(entry)}; "
                f"risk budget {risk_pct:.2f}% includes estimated fees and 5 bps/fill slippage reserve; actual fills can differ."
            )
            self._save_state()

        return True, "Paper position opened. No exchange order was sent."

    def _apply_paper_funding(self, pos, now_ms):
        entry_ms = int(float(pos.get("opened_at_epoch", 0.0)) * 1000)
        last_ts = int(pos.get("last_funding_ts", 0) or 0)
        side_sign = 1.0 if pos.get("side") == "LONG" else -1.0
        notional = float(pos.get("position_notional", 0.0)) * float(pos.get("remaining_size_pct", 1.0))
        changed = False
        for event in sorted(self.funding_history, key=lambda x: int(x.get("ts", 0))):
            ts = int(event.get("ts", 0))
            if ts <= max(last_ts, entry_ms) or ts > now_ms:
                continue
            cashflow = -side_sign * notional * float(event.get("rate", 0.0))
            self.balance += cashflow
            pos["funding_cashflow_usd"] = float(pos.get("funding_cashflow_usd", 0.0)) + cashflow
            pos["last_funding_ts"] = ts
            pos["funding_source"] = "estimated from OKX settled public rate"
            last_ts = ts
            changed = True
            self._append_trade_log_event("FUNDING_ESTIMATE", pos, {
                "funding_ts_ms": ts, "settled_rate": event.get("rate"),
                "estimated_cashflow_usd": cashflow,
                "source": "OKX public realizedRate; simulated cashflow, not account bill",
            })
        if changed:
            self._refresh_daily_guard()
            self._save_state()

    def update_open_position(self, current_price, now_ts=None, force_close=False):
        now_ts = time.time() if now_ts is None else float(now_ts)
        with self.lock:
            if self.open_position is None:
                return

            pos = self.open_position
            if pos.get("execution_mode", "paper") != "okx_demo":
                self._apply_paper_funding(pos, int(now_ts * 1000))
            current_price = float(current_price)
            pos["current_price"] = current_price
            pos["candle_count"] = int(pos.get("candle_count", 0)) + 1
            side = pos["side"]
            entry = float(pos["entry_price"])
            full_notional = float(pos["position_notional"])
            remaining_pct = float(pos.get("remaining_size_pct", 1.0))
            remaining_notional = full_notional * remaining_pct
            signed_return = (current_price - entry) / entry if side == "LONG" else (entry - current_price) / entry
            pos["unrealized_pnl"] = remaining_notional * signed_return
            self._refresh_daily_guard()

            # TP1 closes half and records actual net cash flow, including the exit fee.
            if not pos.get("tp1_hit", False):
                tp1_hit = (side == "LONG" and current_price >= pos["tp1_price"]) or \
                          (side == "SHORT" and current_price <= pos["tp1_price"])
                if tp1_hit:
                    half_notional = full_notional * 0.5
                    slip_fraction = max(0.0, float(pos.get("slippage_bps", self.slippage_bps))) / 10_000.0
                    tp1_exit_price = current_price * (1.0 - slip_fraction if side == "LONG" else 1.0 + slip_fraction)
                    tp1_signed_return = (tp1_exit_price - entry) / entry if side == "LONG" else (entry - tp1_exit_price) / entry
                    gross_half_pnl = half_notional * tp1_signed_return
                    exit_fee = half_notional * self.fee_rate
                    pos["slippage_cost_est_usd"] = float(pos.get("slippage_cost_est_usd", 0.0)) + half_notional * slip_fraction
                    self.balance += gross_half_pnl - exit_fee
                    pos["realized_gross_pnl"] = float(pos.get("realized_gross_pnl", 0.0)) + gross_half_pnl
                    pos["total_fees"] = float(pos.get("total_fees", 0.0)) + exit_fee
                    pos["remaining_size_pct"] = 0.5
                    pos["tp1_hit"] = True
                    pos["sl_price"] = entry * (1.0005 if side == "LONG" else 0.9995)
                    pos["unrealized_pnl"] = half_notional * signed_return
                    self.add_log(
                        f"TP1 paper partial close {pos['symbol']} @ ${self.format_price(tp1_exit_price)}; "
                        f"net partial PnL ${gross_half_pnl - exit_fee:.2f}; stop moved to fee-buffered breakeven."
                    )
                    self._append_trade_log_event("TP1_PARTIAL_CLOSE", pos, {
                        "exit_price": tp1_exit_price,
                        "mark_price": current_price,
                        "gross_pnl_usd": gross_half_pnl,
                        "net_pnl_usd": gross_half_pnl - exit_fee,
                        "fees_usd": pos["total_fees"],
                        "closed_fraction": 0.5,
                        "stop_after_tp1": pos["sl_price"],
                    })
                    self._refresh_daily_guard()
                    self._save_state()

            opened_at = float(pos.get("opened_at_epoch", now_ts))
            stale_hit = (not pos.get("tp1_hit", False) and
                         now_ts - opened_at >= self.stale_trade_seconds)
            sl_hit = (side == "LONG" and current_price <= pos["sl_price"]) or \
                     (side == "SHORT" and current_price >= pos["sl_price"])
            tp2_hit = (side == "LONG" and current_price >= pos["tp2_price"]) or \
                      (side == "SHORT" and current_price <= pos["tp2_price"])

            if force_close or sl_hit or tp2_hit or stale_hit:
                if force_close:
                    close_reason = "MANUAL PAPER CLOSE"
                elif sl_hit:
                    close_reason = "STOP LOSS"
                elif tp2_hit:
                    close_reason = "TP2 TARGET"
                else:
                    close_reason = "STALE TIME EXIT"

                remaining_pct = float(pos.get("remaining_size_pct", 1.0))
                remaining_notional = full_notional * remaining_pct
                slip_fraction = max(0.0, float(pos.get("slippage_bps", self.slippage_bps))) / 10_000.0
                exit_fill_price = current_price * (1.0 - slip_fraction if side == "LONG" else 1.0 + slip_fraction)
                final_signed_return = (exit_fill_price - entry) / entry if side == "LONG" else (entry - exit_fill_price) / entry
                gross_final_pnl = remaining_notional * final_signed_return
                exit_fee = remaining_notional * self.fee_rate
                pos["slippage_cost_est_usd"] = float(pos.get("slippage_cost_est_usd", 0.0)) + remaining_notional * slip_fraction
                pos["total_fees"] = float(pos.get("total_fees", 0.0)) + exit_fee
                pos["realized_gross_pnl"] = float(pos.get("realized_gross_pnl", 0.0)) + gross_final_pnl
                self.balance += gross_final_pnl - exit_fee
                total_net_pnl = (
                    float(pos["realized_gross_pnl"]) - float(pos["total_fees"])
                    + float(pos.get("funding_cashflow_usd", 0.0))
                )

                exit_time = datetime.now(LAGOS_TZ).strftime("%Y-%m-%d %H:%M:%S")
                trade_record = {
                    "id": pos["id"],
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "strategy": pos["strategy"],
                    "entry_price": pos["entry_price"],
                    "signal_bar_close_price": pos.get("signal_bar_close_price"),
                    "entry_quote_price": pos.get("entry_quote_price"),
                    "exit_price": exit_fill_price,
                    "position_notional": pos.get("position_notional"),
                    "margin": pos.get("margin"),
                    "leverage": pos.get("leverage"),
                    "risk_pct": pos.get("risk_pct"),
                    "risk_budget_usd": pos.get("risk_budget_usd"),
                    "planned_initial_risk_usd": pos.get("planned_initial_risk_usd"),
                    "R_net": round(total_net_pnl / max(float(pos.get("planned_initial_risk_usd", 0.0)), 1e-12), 6),
                    "slippage_est_usd": round(float(pos.get("slippage_cost_est_usd", 0.0)), 4),
                    "gross_pnl": round(pos["realized_gross_pnl"], 4),
                    "net_pnl": round(total_net_pnl, 2),
                    "net_pnl_pct": round((total_net_pnl / self.initial_balance) * 100, 3),
                    "fees": round(pos["total_fees"], 4),
                    "funding_cashflow_usd": round(float(pos.get("funding_cashflow_usd", 0.0)), 6),
                    "funding_source": pos.get("funding_source", "unavailable"),
                    "slippage_est_usd": round(float(pos.get("slippage_cost_est_usd", 0.0)), 4),
                    "entry_time": pos["entry_time"],
                    "exit_time": exit_time,
                    "close_reason": close_reason,
                    "win": total_net_pnl > 0,
                    "confluence_score": pos.get("confluence_score", 0),
                    "adx_5m": pos.get("adx_5m"),
                    "entry_bar_close_ms": pos.get("entry_bar_close_ms"),
                    "tp1_hit": pos.get("tp1_hit", False),
                    "initial_stop": pos.get("initial_sl_price", pos.get("sl_price")),
                    "final_stop": pos.get("sl_price"),
                    "tp1_price": pos.get("tp1_price"),
                    "tp2_price": pos.get("tp2_price"),
                    "strategy_votes": pos.get("strategy_votes", {}),
                    "confirmations": pos.get("confirmations", []),
                    "hold_seconds": max(0.0, now_ts - float(pos.get("opened_at_epoch", now_ts))),
                    "execution_mode": pos.get("execution_mode", "paper"),
                }
                self.closed_trades.append(trade_record)
                self._append_trade_log_event("EXIT", pos, {
                    "exit_price": exit_fill_price,
                    "mark_price": current_price,
                    "exit_time": exit_time,
                    "gross_pnl_usd": pos["realized_gross_pnl"],
                    "net_pnl_usd": total_net_pnl,
                    "R_net": trade_record["R_net"],
                    "fees_usd": pos["total_fees"],
                    "slippage_est_usd": pos.get("slippage_cost_est_usd", 0.0),
                    "close_reason": close_reason,
                    "hold_seconds": trade_record["hold_seconds"],
                    "win": total_net_pnl > 0,
                })
                self.open_position = None
                self.equity_curve.append({
                    "time": datetime.now(LAGOS_TZ).strftime("%H:%M:%S"),
                    "equity": round(self._current_equity(), 2),
                })
                self.add_log(
                    f"PAPER CLOSED {side} {pos['symbol']} ({close_reason}) @ ${self.format_price(exit_fill_price)} | "
                    f"Net PnL incl. all fees: {total_net_pnl:+.2f}"
                )
                self._record_trade_outcome(total_net_pnl)
                self._save_state()

    def close_position_market(self):
        """Close the tracked position through its actual execution path; never paper-close a demo trade."""
        with self.lock:
            pos = self.open_position
            if not pos:
                return False, "No open position."
            mode = pos.get("execution_mode", "paper")
            if mode == "okx_demo":
                if self.execution_mode != "okx_demo" or self.okx_demo_client is None:
                    self.demo_halted = True
                    self.demo_preflight_status = "Cannot close stored OKX demo position: demo credentials are unavailable; reconcile manually."
                    self._save_state()
                    return False, self.demo_preflight_status
                if pos.get("pending_exit_intent"):
                    return False, "A demo exit order is unresolved; no duplicate close request was sent. Reconcile the order first."
                if not self._demo_instrument:
                    self.demo_ready = False
                if not self._ensure_demo_ready(require_armed=False):
                    return False, self.demo_preflight_status
                mark = float(pos.get("current_price") or self.ticker_data.get("last") or pos.get("entry_price") or 0.0)
                closed = self._demo_exit_position("MANUAL DEMO CLOSE", full_close=True, current_price=mark)
                if closed or self.open_position is None:
                    return True, "OKX demo reduce-only close was filled and reconciled."
                return False, self.demo_preflight_status or "Demo close did not fully reconcile; no automatic retry was sent."
            if mode != "paper":
                return False, "Unknown execution mode; refusing to change local accounting."
            mark = float(pos.get("current_price") or self.ticker_data.get("last") or 0.0)
            if mark <= 0:
                return False, "No valid market price is available for the paper close."
            self.update_open_position(mark, force_close=True)
            if self.open_position is None:
                return True, "Paper position closed using the simulated market-fill model. No exchange order was sent."
            return False, "Paper close did not complete; position remains open."

    def manual_trigger(self, side="LONG"):
        return False, "Manual orders are disabled; only scanner-verified setups may open paper positions. No order was placed."

    def bot_loop(self):
        self.add_log("OKX BTC-USDT-SWAP three-pillar scanner started; only confirmed 5m candles are evaluated.")
        last_macro_poll = 0.0
        last_market_scan = 0.0
        while self.is_running:
            try:
                now_ts = time.time()
                symbol = self.active_symbol

                ticker = self.fetch_ticker(symbol)
                if ticker:
                    with self.lock:
                        self.ticker_data = ticker
                        self.last_ticker_update_epoch = now_ts
                    if self.open_position and self.open_position.get("symbol") == symbol:
                        if self.open_position.get("execution_mode") == "okx_demo":
                            self._monitor_demo_position(ticker["last"], now_ts=now_ts)
                        else:
                            self.update_open_position(ticker["last"], now_ts=now_ts)

                # Settled funding history supports paper PnL accounting only.
                self.refresh_funding_history(now_epoch=now_ts, symbol=symbol)

                if now_ts - last_macro_poll >= 60.0:
                    last_macro_poll = now_ts
                    self.multi_1h_trend[symbol] = self.calculate_1h_trend(symbol)
                    self.multi_funding[symbol] = self.fetch_funding_rate(symbol)

                # Price history is refreshed every 20 seconds; position monitoring stays faster.
                if now_ts - last_market_scan >= 20.0:
                    last_market_scan = now_ts
                    candles_5m = self.fetch_klines(symbol, bar="5m", limit=60)
                    if not candles_5m:
                        self._log_once("strategy_candles", "Confirmed 5m candles unavailable; entries remain blocked.")
                        self.maybe_send_daily_noon_summary(datetime.now(LAGOS_TZ))
                        time.sleep(2)
                        continue

                    ind = self.calculate_indicators(candles_5m)
                    if not ind:
                        self._log_once("indicator_warmup", "5m indicator warm-up incomplete; entries remain blocked.")
                        self.maybe_send_daily_noon_summary(datetime.now(LAGOS_TZ))
                        time.sleep(2)
                        continue

                    with self.lock:
                        self.multi_indicators[symbol] = ind
                        self.last_indicator_update_epoch = now_ts
                        if symbol == self.active_symbol:
                            self.indicators = ind

                    if self.open_position and self.open_position.get("symbol") == symbol:
                        if self.open_position.get("execution_mode") == "okx_demo":
                            self._monitor_demo_position(self.ticker_data.get("last", ind["current_close"]), now_ts=now_ts)
                        else:
                            self.update_open_position(ind["current_close"], now_ts=now_ts)

                    signal = self.evaluate_strategy_signals(
                        ind, symbol=symbol, now=datetime.now(timezone.utc), candles_5m=candles_5m,
                    )
                    if signal:
                        close_ms = int(signal.get("bar_close_ms") or (int(candles_5m[-1]["ts"]) + 5 * 60_000))
                        last_close_ms = self.last_processed_signal_close.get(symbol, 0)
                        if close_ms > last_close_ms:
                            self.last_processed_signal_close[symbol] = close_ms
                            self.last_signal_time[symbol] = now_ts
                            self.add_log(
                                f"CONFIRMED {signal['confluence_score']}/3 {signal['side']} three-pillar setup "
                                f"for {symbol}; entry ${self.format_price(signal['entry'])}."
                            )
                            signal_record = {
                                "time": datetime.now(LAGOS_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                                "symbol": symbol,
                                "side": signal["side"],
                                "strategy": self.active_strategy,
                                "confluence_score": signal["confluence_score"],
                                "confirmations": signal.get("confirmations", []),
                                "entry": signal["entry"],
                                "sl": signal["sl"],
                                "tp1": signal["tp1"],
                                "tp2": signal["tp2"],
                                "reason": signal["reason"],
                            }
                            # A signal alert is separate from execution and still goes out if
                            # safety checks, demo arming, or sizing later block an order.
                            self.dispatch_signal_notifications(signal, symbol=symbol)
                            if self.open_position is None:
                                signal["signal_bar_close_price"] = signal["entry"]
                                next_quote = self.fetch_ticker(symbol)
                                if not next_quote:
                                    self._log_once("entry_quote", "Could not obtain a post-signal market quote; entry skipped.")
                                    signal_record["execution_status"] = "No fresh post-signal quote; no entry attempted."
                                    self.signals.append(signal_record)
                                else:
                                    signal["execution_price"] = next_quote["last"]
                                    opened, execution_message = self.execute_trade_signal(signal, symbol)
                                    if not opened:
                                        signal_record["execution_status"] = execution_message
                                        self.signals.append(signal_record)
                            else:
                                signal_record["execution_status"] = "Blocked: one position is already open."
                                self.signals.append(signal_record)

                # Send the scheduled noon status after a fresh scan when possible.
                self.maybe_send_daily_noon_summary(datetime.now(LAGOS_TZ))
            except Exception as exc:
                self._log_once(f"loop_{type(exc).__name__}", f"Bot loop encountered {type(exc).__name__}; entries fail closed.")

            time.sleep(2)

    def start(self):
        """Start/reuse one scanner and one Telegram poller; avoid duplicate getUpdates loops on quick restarts."""
        with self.lock:
            was_running = self.is_running
            self.is_running = True
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.bot_loop, daemon=True)
                self.thread.start()
            if self.tg_thread is None or not self.tg_thread.is_alive():
                self.tg_thread = threading.Thread(target=self.telegram_polling_loop, daemon=True)
                self.tg_thread.start()
            if was_running:
                return
            if self.execution_mode == "okx_demo":
                arm_state = "armed for OKX DEMO only" if self.demo_orders_armed else "disarmed; no entry orders will be sent"
                self.add_log(f"▶ BTC three-pillar scanner started in OKX demo mode ({arm_state}); live execution is unsupported.")
            else:
                self.add_log("▶ BTC three-pillar scanner started in paper-simulation mode; no exchange order will be sent.")

    def stop(self):
        with self.lock:
            if self.is_running:
                self.is_running = False
                self.telegram_polling_status = "stopped"
                self.add_log("⏹ Strategy scanner and Telegram command polling paused.")

    def reset_account(self, new_balance=None):
        with self.lock:
            if self.execution_mode != "paper":
                raise ValueError("The paper-ledger reset is unavailable while OKX demo mode is configured.")
            if self.open_position is not None:
                raise ValueError("Cannot reset the ledger while a position is open; close it first.")
            if new_balance is not None:
                value = float(new_balance)
                if value <= 0:
                    raise ValueError("Balance must be positive.")
                self.initial_balance = value
            self.balance = self.initial_balance
            self.closed_trades = []
            self.signals = []
            self.equity_curve = [{"time": datetime.now(LAGOS_TZ).strftime("%H:%M:%S"), "equity": self.initial_balance}]
            self.consecutive_losses = 0
            self.daily_start_equity = self.initial_balance
            self.daily_date = datetime.now(LAGOS_TZ).date().isoformat()
            self.daily_loss_pause = False
            self.daily_pause_reason = ""
            self.current_daily_drawdown_pct = 0.0
            self.add_log("🔄 Paper account reset to $%.2f; daily risk counters reset." % self.initial_balance)
            self._save_state()

    def get_status(self):
        self._refresh_daily_guard()
        with self.lock:
            wins = sum(1 for t in self.closed_trades if t["win"])
            total_trades = len(self.closed_trades)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
            account_equity = self._current_equity()
            baseline_equity = (self.demo_initial_equity or account_equity) if self.execution_mode == "okx_demo" else self.initial_balance
            total_pnl = account_equity - baseline_equity
            daily_candidates = self.get_confluence_candidates()
            current_ind = self.multi_indicators.get(self.active_symbol) or {}
            current_components = self._confluence_components(current_ind, self.active_symbol)
            required_confluence, asian_session = self._required_confluence()
            directional_scores = {side: len(current_components[side]) for side in ("LONG", "SHORT")}
            summary_side = max(directional_scores, key=directional_scores.get)
            tied_directions = directional_scores["LONG"] == directional_scores["SHORT"]
            if directional_scores[summary_side] == 0 or tied_directions:
                summary_side = "NEUTRAL"
                summary_confirmations = []
                summary_score = max(directional_scores.values()) if tied_directions else 0
            else:
                summary_confirmations = current_components[summary_side]
                summary_score = directional_scores[summary_side]
            displayed_balance = self.demo_equity if self.execution_mode == "okx_demo" and self.demo_equity is not None else self.balance
            if not self.enable_telegram:
                telegram_status = "disabled in server configuration"
            elif not self.telegram_token:
                telegram_status = "not configured: set TELEGRAM_BOT_TOKEN on the server"
            elif self.telegram_last_error:
                telegram_status = self.telegram_last_error
            elif not self.telegram_chat_id:
                telegram_status = "setup-only mode: start the scanner and send /start for your numeric chat id; then set TELEGRAM_CHAT_ID and restart"
            elif not self.is_running:
                telegram_status = "configured; command listener is stopped until the scanner starts"
            else:
                telegram_status = self.telegram_polling_status
            return {
                "is_running": self.is_running,
                "balance": round(displayed_balance, 2),
                "equity": round(account_equity, 2),
                "initial_balance": baseline_equity,
                "total_pnl": round(total_pnl, 2),
                "pnl_pct": round((total_pnl / baseline_equity) * 100, 2) if baseline_equity else 0.0,
                "active_symbol": self.active_symbol,
                "active_strategy": self.active_strategy,
                "min_confluence_score": self.min_confluence_score,
                "execution_mode": self.execution_mode,
                "exchange_execution_locked": not self.live_execution_enabled,
                "demo_orders_armed": self.demo_orders_armed,
                "demo_preflight_status": self.demo_preflight_status,
                "demo_halted": self.demo_halted,
                "demo_external_position": self.demo_external_position,
                "demo_equity_updated_epoch": self._demo_equity_updated,
                "market_regime": self.market_regime,
                "risk_pct": self.risk_pct,
                "leverage": self.leverage,
                "margin_cap_usd": self.margin_cap_usd,
                "slippage_bps": self.slippage_bps,
                "required_confluence": required_confluence,
                "asian_session": asian_session,
                "current_confluence_summary": {
                    "direction": summary_side,
                    "confluence_score": summary_score,
                    "required": required_confluence,
                    "confirmations": summary_confirmations,
                    "rsi": current_ind.get("rsi"),
                    "adx": current_ind.get("adx"),
                },
                "daily_date": self.daily_date,
                "daily_start_equity": round(self.daily_start_equity, 2),
                "daily_drawdown_pct": round(self.current_daily_drawdown_pct, 3),
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                "consecutive_losses": self.consecutive_losses,
                "max_consecutive_losses": self.max_consecutive_losses,
                "daily_loss_pause": self.daily_loss_pause,
                "daily_pause_reason": self.daily_pause_reason,
                "telegram_configured": bool(self.telegram_token and self.telegram_chat_id),
                "enable_telegram": self.enable_telegram,
                "telegram_status": telegram_status,
                "telegram_polling_status": self.telegram_polling_status,
                "telegram_last_poll_epoch": self.telegram_last_poll_epoch,
                "telegram_last_success_epoch": self.telegram_last_success_epoch,
                "telegram_send_failures": self.telegram_send_failures,
                "telegram_daily_noon_enabled": self.telegram_daily_noon_enabled,
                "telegram_last_noon_summary_date": self.last_noon_summary_date,
                "enable_discord": self.enable_discord,
                "supported_symbols": self.supported_symbols,
                "ticker": self.ticker_data,
                "indicators": self.indicators,
                "multi_indicators": self.multi_indicators,
                "multi_1h_trend": self.multi_1h_trend,
                "multi_funding": self.multi_funding,
                "confluence_candidates": daily_candidates,
                "open_position": self.open_position,
                "signals": self.signals[::-1][:20],
                "closed_trades": self.closed_trades[::-1],
                "win_rate": round(win_rate, 1),
                "total_trades": total_trades,
                "equity_curve": self.equity_curve,
                "logs": self.logs[::-1][:50]
            }
