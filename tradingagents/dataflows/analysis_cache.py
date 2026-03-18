"""Persistent per-ticker analysis state for iterative reasoning.

Stored at:  {data_cache_dir}/analysis_cache/{TICKER}/analysis_state.json

Responsibilities:
  1. Record every completed recommendation (signal, TP, SL, validity, entry price).
  2. Score past recommendations using Binance 4h kline data once their validity
     window has elapsed.
  3. Provide a formatted "past context" block that agents inject into their prompts
     so each new run builds on prior conclusions.
  4. Save a brief reasoning summary extracted from the last final_state.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_validity_days(validity: str) -> int:
    """Convert a validity string like '3 days', '1 week', '2 weeks' to an int."""
    if not validity or validity.lower() in ("unspecified", "—", "n/a"):
        return 7
    v = validity.lower().strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(hour|day|week|month)", v)
    if not m:
        return 7
    n, unit = float(m.group(1)), m.group(2)
    if "hour"  in unit: return max(1, round(n / 24) + 1)
    if "week"  in unit: return round(n * 7)
    if "month" in unit: return round(n * 30)
    return round(n)


def _extract_signal(text: str) -> str:
    t = (text or "").upper()
    if "BUY"  in t: return "BUY"
    if "SELL" in t: return "SELL"
    return "HOLD"


def _truncate(text: str, max_chars: int = 800) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " …"


# ── Main class ────────────────────────────────────────────────────────────────

class AnalysisCache:
    """Load, update, and persist per-ticker analysis state."""

    def __init__(self, ticker: str, cache_dir: str):
        self.ticker = ticker.upper()
        self.dir    = Path(cache_dir) / "analysis_cache" / self.ticker
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path   = self.dir / "analysis_state.json"
        self.state  = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ticker": self.ticker, "recommendations": [], "past_reasoning": ""}

    def save(self):
        self.path.write_text(
            json.dumps(self.state, indent=2, default=str), encoding="utf-8"
        )

    # ── Record & score ────────────────────────────────────────────────────────

    def record_recommendation(
        self,
        analysis_date: str,
        signal: str,
        take_profit: Optional[float],
        stop_loss: Optional[float],
        validity: str,
        entry_price: Optional[float],
        investment_plan: str = "",
        final_decision: str = "",
    ):
        """Append a new recommendation to the history."""
        rec = {
            "ticker":           self.ticker,
            "analysis_date":    analysis_date,
            "signal":           signal.upper(),
            "take_profit":      take_profit,
            "stop_loss":        stop_loss,
            "validity":         validity,
            "entry_price":      entry_price,
            "score":            None,
            "outcome":          None,
            "scored_at":        None,
            "investment_plan_summary": _truncate(investment_plan),
            "final_decision_summary":  _truncate(final_decision),
        }
        self.state.setdefault("recommendations", []).append(rec)

    def score_pending(self, curr_date: str, binance_cache_dir: str) -> int:
        """
        Score all recommendations whose validity window has elapsed.
        Returns the number of recommendations newly scored.
        """
        from tradingagents.dataflows.binance_utils import fetch_4h_klines

        scored = 0
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")

        for rec in self.state.get("recommendations", []):
            if rec.get("score") is not None:
                continue  # already scored

            analysis_dt = datetime.strptime(rec["analysis_date"], "%Y-%m-%d")
            validity_days = _parse_validity_days(rec.get("validity", ""))
            expiry_dt = analysis_dt + timedelta(days=validity_days)

            # Only score once the window is fully elapsed or we are past it
            if curr_dt < expiry_dt:
                continue

            # Fetch 4h candles from analysis_date to expiry (+1 buffer day)
            end_fetch = min(expiry_dt + timedelta(days=1), curr_dt)
            df = fetch_4h_klines(
                rec["ticker"],
                rec["analysis_date"],
                end_fetch.strftime("%Y-%m-%d"),
                binance_cache_dir,
            )
            if df is None or df.empty:
                rec["score"]   = None
                rec["outcome"] = "no_data"
                continue

            tp     = rec.get("take_profit")
            sl     = rec.get("stop_loss")
            signal = rec.get("signal", "HOLD").upper()

            # Determine entry price from first candle if not recorded
            entry = rec.get("entry_price") or float(df["close"].iloc[0])
            rec["entry_price"] = entry

            if tp and sl:
                # Walk candles and check first hit
                hit = None
                for _, row in df.iterrows():
                    h, lo = float(row["high"]), float(row["low"])
                    ts = str(row["open_time"])
                    if signal == "BUY":
                        if h >= tp:
                            hit = (1.0, "TP_HIT", ts); break
                        if lo <= sl:
                            hit = (-1.0, "SL_HIT", ts); break
                    elif signal == "SELL":
                        if lo <= tp:
                            hit = (1.0, "TP_HIT", ts); break
                        if h >= sl:
                            hit = (-1.0, "SL_HIT", ts); break
                if hit:
                    rec["score"], rec["outcome"], rec["scored_at"] = hit
                else:
                    # Validity expired without hitting either level
                    final_p = float(df["close"].iloc[-1])
                    pnl = (final_p - entry) / entry if signal == "BUY" \
                          else (entry - final_p) / entry if signal == "SELL" else 0.0
                    rec["score"]     = round(max(-1.0, min(1.0, pnl * 5)), 3)
                    rec["outcome"]   = f"EXPIRED (P&L {pnl:+.1%})"
                    rec["scored_at"] = end_fetch.strftime("%Y-%m-%d")
            else:
                # No TP/SL — score by raw P&L over validity period
                final_p = float(df["close"].iloc[-1])
                pnl = (final_p - entry) / entry if signal == "BUY" \
                      else (entry - final_p) / entry if signal == "SELL" else 0.0
                rec["score"]     = round(max(-1.0, min(1.0, pnl * 10)), 3)
                rec["outcome"]   = f"No TP/SL — P&L {pnl:+.1%}"
                rec["scored_at"] = end_fetch.strftime("%Y-%m-%d")

            scored += 1

        return scored

    # ── Context for agent injection ───────────────────────────────────────────

    def get_past_context(self, n_recent: int = 3) -> str:
        """
        Return a formatted Markdown block summarising past reasoning and
        recommendation performance.  Injected into agent prompts at run start.
        """
        parts = []

        # Previous reasoning summary
        reasoning = self.state.get("past_reasoning", "")
        if reasoning:
            parts.append(f"### Previous Analysis Summary\n{reasoning}")

        recs = self.state.get("recommendations", [])
        if recs:
            scored  = [r for r in recs if r.get("score") is not None]
            pending = [r for r in recs if r.get("score") is None]

            if scored:
                rows = [
                    "| Date | Signal | Entry | TP | SL | Validity | Score | Outcome |",
                    "|------|--------|-------|----|----|----------|-------|---------|",
                ]
                for r in scored[-n_recent:]:
                    ep_s  = f"${r['entry_price']:,.0f}" if r.get("entry_price") else "—"
                    tp_s  = f"${r['take_profit']:,.0f}" if r.get("take_profit") else "—"
                    sl_s  = f"${r['stop_loss']:,.0f}"   if r.get("stop_loss")   else "—"
                    sc_s  = f"{r['score']:+.2f}"         if r.get("score") is not None else "—"
                    rows.append(
                        f"| {r['analysis_date']} | {r.get('signal','?')} | {ep_s} "
                        f"| {tp_s} | {sl_s} | {r.get('validity','?')} "
                        f"| {sc_s} | {r.get('outcome','?')} |"
                    )
                parts.append("### Recommendation History (scored)\n" + "\n".join(rows))

            if pending:
                last = pending[-1]
                tp_s = f"${last['take_profit']:,.0f}" if last.get("take_profit") else "—"
                sl_s = f"${last['stop_loss']:,.0f}"   if last.get("stop_loss")   else "—"
                parts.append(
                    f"### Last Pending Recommendation\n"
                    f"Date: {last['analysis_date']} | Signal: {last.get('signal','?')} | "
                    f"TP: {tp_s} | SL: {sl_s} | Validity: {last.get('validity','?')}\n"
                    f"Plan summary: {last.get('investment_plan_summary','')}"
                )

        if not parts:
            return ""

        return (
            f"## Iterative Analysis Context for {self.ticker}\n\n"
            + "\n\n".join(parts)
            + "\n\n*Use these past results to improve accuracy. "
              "Learn from past mistakes and scored recommendations.*"
        )

    # ── Update reasoning after a run ─────────────────────────────────────────

    def update_from_final_state(self, final_state: dict, analysis_date: str):
        """Extract a concise summary from the completed run and persist it."""
        decision   = _truncate(final_state.get("final_trade_decision", ""), 600)
        inv_plan   = _truncate(final_state.get("investment_plan", ""), 400)
        market     = _truncate(final_state.get("market_report", ""), 300)

        summary = (
            f"[{analysis_date}] {self.ticker}\n"
            f"Decision: {decision}\n"
            f"Investment plan: {inv_plan}\n"
            f"Market snapshot: {market}"
        )
        self.state["past_reasoning"] = summary
        self.state["last_analysis_date"] = analysis_date
