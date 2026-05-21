"""Streamlit dashboard.

Reads exclusively from the REST API (never Postgres). One page, 10s
auto-refresh, symbol dropdown, price chart with red dots overlaid at alert
timestamps, plus a "Recent Alerts" sidebar. SPEC §8 has the full layout.
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

API_URL = os.environ.get("API_URL", "http://localhost:8000")
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"]
PRICE_LIMIT = 200
SIDEBAR_ALERT_LIMIT = 10
OVERLAY_ALERT_LIMIT = 200
REFRESH_INTERVAL_MS = 10_000

st.set_page_config(page_title="Market Data Live", layout="wide")
st_autorefresh(interval=REFRESH_INTERVAL_MS, key="autorefresh")


@st.cache_data(ttl=5)
def fetch_prices(symbol: str, limit: int) -> pd.DataFrame:
    with httpx.Client(base_url=API_URL, timeout=5.0) as client:
        r = client.get(f"/prices/{symbol}", params={"limit": limit})
        r.raise_for_status()
        data = r.json()
    if not data:
        return pd.DataFrame(columns=["ts", "price"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts")


@st.cache_data(ttl=5)
def fetch_alerts(limit: int) -> pd.DataFrame:
    with httpx.Client(base_url=API_URL, timeout=5.0) as client:
        r = client.get("/alerts", params={"limit": limit})
        r.raise_for_status()
        data = r.json()
    if not data:
        return pd.DataFrame(columns=["symbol", "ts", "price", "z_score", "message"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


st.title("Market Data Live")
symbol = st.selectbox("Symbol", SYMBOLS, index=0)

try:
    prices = fetch_prices(symbol, PRICE_LIMIT)
    alerts_all = fetch_alerts(OVERLAY_ALERT_LIMIT)
except httpx.HTTPError as e:
    st.error(f"Could not reach API at {API_URL}: {e}")
    st.stop()

if prices.empty:
    st.info(
        f"No price data for {symbol} yet. "
        "Outside US market hours the Finnhub feed delivers no trades; "
        "the chart will fill in once the ingestor starts receiving ticks."
    )
else:
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

with st.sidebar:
    st.subheader("Recent Alerts")
    sidebar_alerts = fetch_alerts(SIDEBAR_ALERT_LIMIT)
    if sidebar_alerts.empty:
        st.caption("No alerts yet.")
    else:
        display = sidebar_alerts[["ts", "symbol", "price", "z_score", "message"]].copy()
        display["ts"] = display["ts"].dt.strftime("%H:%M:%S")
        st.dataframe(display, hide_index=True, use_container_width=True)

st.markdown(
    "<div style='text-align: center; color: #888; font-size: 0.85em; margin-top: 2em;'>"
    "Market data: <a href='https://finnhub.io' target='_blank'>Finnhub</a>"
    "</div>",
    unsafe_allow_html=True,
)
