"""Streamlit dashboard.

Reads exclusively from the REST API (never Postgres). One page, 10s
auto-refresh, symbol dropdown, price chart with red dots overlaid at alert
timestamps, plus a "Recent Alerts" sidebar. SPEC §8 has the full layout.

When the live feed is quiet (outside US market hours, weekends, holidays),
the price chart is replaced by a watchlist view: five quote cards across the
top and a company-news feed below. Both pull from API endpoints that proxy
Finnhub's REST API (SPEC §5).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from _shared import footer, http_client
from streamlit_autorefresh import st_autorefresh

API_URL = os.environ.get("API_URL", "http://localhost:8000")
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"]
PRICE_LIMIT = 200
SIDEBAR_ALERT_LIMIT = 10
OVERLAY_ALERT_LIMIT = 200
REFRESH_INTERVAL_MS = 10_000
# Match the cache TTL to the refresh interval so the cache actually
# deduplicates within one refresh tick instead of always missing.
CACHE_TTL_S = 10

st.set_page_config(page_title="Market Data Live", layout="wide")
st_autorefresh(interval=REFRESH_INTERVAL_MS, key="autorefresh")


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_prices(symbol: str, limit: int) -> pd.DataFrame:
    r = http_client(API_URL).get(f"/prices/{symbol}", params={"limit": limit})
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=["ts", "price"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts")


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_alerts(limit: int) -> pd.DataFrame:
    r = http_client(API_URL).get("/alerts", params={"limit": limit})
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=["symbol", "ts", "price", "z_score", "message"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_market_status() -> dict[str, Any] | None:
    """Return US market status, or None on transport error (caller falls back)."""
    try:
        r = http_client(API_URL).get("/market-status")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_quote(symbol: str) -> dict[str, Any] | None:
    """Return a quote dict, or None if Finnhub had nothing for the symbol."""
    try:
        r = http_client(API_URL).get(f"/quote/{symbol}")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_news(symbol: str) -> list[dict[str, Any]]:
    r = http_client(API_URL).get(f"/news/{symbol}")
    r.raise_for_status()
    return r.json()


def _relative_time(ts_iso: str) -> str:
    ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(UTC)
    delta = datetime.now(UTC) - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def render_live(prices: pd.DataFrame, alerts_all: pd.DataFrame, symbol: str) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=prices["ts"],
            y=prices["price"],
            mode="lines",
            name=symbol,
            line={"width": 1.5},
        )
    )
    symbol_alerts = alerts_all[alerts_all["symbol"] == symbol]
    if not symbol_alerts.empty:
        fig.add_trace(
            go.Scatter(
                x=symbol_alerts["ts"],
                y=symbol_alerts["price"],
                mode="markers",
                name="alerts",
                marker={"color": "red", "size": 10, "symbol": "circle"},
            )
        )
    fig.update_layout(
        height=520,
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        xaxis_title="time (UTC)",
        yaxis_title="price",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _market_status_banner(status: dict[str, Any] | None) -> str:
    if status is None:
        return (
            "Live feed is quiet — showing latest quote snapshots and news. "
            "The chart resumes automatically when trades start flowing."
        )
    if status.get("holiday"):
        return (
            f"US markets closed — {status['holiday']}. "
            "Showing latest quote snapshots and news."
        )
    session = (status.get("session") or "").lower()
    if session == "pre-market":
        return (
            "Pre-market session — regular hours open at 9:30 AM ET. "
            "Showing latest quote snapshots and news."
        )
    if session == "post-market":
        return (
            "Post-market session — regular hours closed at 4:00 PM ET. "
            "Showing latest quote snapshots and news."
        )
    return (
        "US markets closed — showing latest quote snapshots and news. "
        "Live chart resumes when trading reopens."
    )


def render_after_hours(selected: str, status: dict[str, Any] | None) -> None:
    st.info(_market_status_banner(status))

    cols = st.columns(len(SYMBOLS))
    for col, sym in zip(cols, SYMBOLS, strict=True):
        with col:
            container = st.container(border=(sym == selected))
            with container:
                try:
                    q = fetch_quote(sym)
                except httpx.HTTPError as e:
                    st.metric(label=sym, value="—")
                    st.caption(f"quote unavailable: {e}")
                    continue
                if q is None:
                    st.metric(label=sym, value="—")
                    st.caption("no quote")
                    continue
                st.metric(
                    label=sym,
                    value=f"${q['current']:.2f}",
                    delta=f"{q['percent_change']:+.2f}%",
                )
                st.caption(
                    f"day range {q['low']:.2f} – {q['high']:.2f}  ·  "
                    f"prev close {q['prev_close']:.2f}"
                )

    st.subheader(f"News: {selected}")
    try:
        items = fetch_news(selected)
    except httpx.HTTPError as e:
        st.caption(f"News unavailable: {e}")
        return

    if not items:
        st.caption("No recent headlines.")
        return

    for item in items:
        rel = _relative_time(item["ts"])
        st.markdown(f"**[{item['headline']}]({item['url']})**")
        st.caption(f"{item['source']} · {rel}")
        if item.get("summary"):
            st.write(item["summary"])
        st.divider()


st.title("Market Data Live")
symbol = st.selectbox("Symbol", SYMBOLS, index=0)

try:
    prices = fetch_prices(symbol, PRICE_LIMIT)
    alerts_all = fetch_alerts(OVERLAY_ALERT_LIMIT)
except httpx.HTTPError as e:
    st.error(f"Could not reach API at {API_URL}: {e}")
    st.stop()

status = fetch_market_status()
market_open = bool(status and status.get("is_open"))
if market_open and not prices.empty:
    render_live(prices, alerts_all, symbol)
else:
    render_after_hours(symbol, status)

with st.sidebar:
    st.subheader("Recent Alerts")
    sidebar_alerts = alerts_all.head(SIDEBAR_ALERT_LIMIT)
    if sidebar_alerts.empty:
        st.caption("No alerts yet.")
    else:
        display = sidebar_alerts[["ts", "symbol", "price", "z_score", "message"]].copy()
        display["ts"] = display["ts"].dt.strftime("%H:%M:%S")
        st.dataframe(display, hide_index=True, use_container_width=True)

footer("Market data: <a href='https://finnhub.io' target='_blank'>Finnhub</a>")
