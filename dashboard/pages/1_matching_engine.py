"""Matching engine view: live top-of-book, depth ladder, and recent trades.

Reads exclusively from the matching-engine HTTP API. Same 10s refresh cadence
and singleton-client conventions as the Finnhub page.
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

ENGINE_URL = os.environ.get("MATCHING_ENGINE_URL", "http://localhost:8080")
SYMBOLS = os.environ.get("ME_SYMBOLS", "SYNTH1,SYNTH2").split(",")
DEPTH = 10
TRADES_LIMIT = 20
REFRESH_INTERVAL_MS = 500
CACHE_TTL_S = 0.5

st.set_page_config(page_title="Matching Engine", layout="wide")
st_autorefresh(interval=REFRESH_INTERVAL_MS, key="me_autorefresh")


@st.cache_resource
def _client() -> httpx.Client:
    return httpx.Client(base_url=ENGINE_URL, timeout=5.0)


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_top(symbol: str) -> dict:
    r = _client().get(f"/book/{symbol}/top")
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_book(symbol: str, depth: int) -> dict:
    r = _client().get(f"/book/{symbol}", params={"depth": depth})
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=CACHE_TTL_S)
def fetch_trades(symbol: str, limit: int) -> pd.DataFrame:
    r = _client().get("/trades", params={"symbol": symbol, "limit": limit})
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=["ts", "price", "quantity", "makerOrderId", "takerOrderId"])
    df = pd.DataFrame(data)
    df["ts"] = pd.to_datetime(df["timestampMillis"], unit="ms", utc=True)
    return df


st.title("Matching Engine")
symbol = st.selectbox("Symbol", SYMBOLS, index=0)

try:
    top = fetch_top(symbol)
    book = fetch_book(symbol, DEPTH)
    trades = fetch_trades(symbol, TRADES_LIMIT)
except httpx.HTTPError as e:
    st.error(f"Could not reach matching engine at {ENGINE_URL}: {e}")
    st.stop()

def _show(v: object) -> str:
    return "-" if v is None else str(v)


c1, c2, c3, c4 = st.columns(4)
c1.metric("Best Bid", _show(top.get("bestBid")))
c2.metric("Best Ask", _show(top.get("bestAsk")))
c3.metric("Spread", _show(top.get("spread")))
c4.metric("Last Trade", _show(top.get("lastTradePrice")))

st.subheader("Order Book Depth")
bids = book.get("bids", [])
asks = book.get("asks", [])
if not bids and not asks:
    st.info("Book is empty.")
else:
    bid_df = pd.DataFrame(bids)
    ask_df = pd.DataFrame(asks)
    fig = go.Figure()
    if not ask_df.empty:
        fig.add_trace(
            go.Bar(
                y=ask_df["price"].astype(str),
                x=ask_df["quantity"],
                orientation="h",
                name="Asks",
                marker_color="#d9534f",
            )
        )
    if not bid_df.empty:
        fig.add_trace(
            go.Bar(
                y=bid_df["price"].astype(str),
                x=-bid_df["quantity"],
                orientation="h",
                name="Bids",
                marker_color="#5cb85c",
            )
        )
    fig.update_layout(
        height=420,
        margin={"l": 20, "r": 20, "t": 10, "b": 20},
        xaxis_title="quantity (asks right, bids left)",
        yaxis_title="price",
        barmode="overlay",
        showlegend=True,
        yaxis={"categoryorder": "category descending"},
    )
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Recent Trades")
if trades.empty:
    st.caption("No trades yet.")
else:
    view = trades[["ts", "price", "quantity", "makerOrderId", "takerOrderId"]].copy()
    view["ts"] = view["ts"].dt.strftime("%H:%M:%S.%f").str[:-3]
    view = view.rename(
        columns={
            "ts": "time",
            "price": "price",
            "quantity": "qty",
            "makerOrderId": "maker",
            "takerOrderId": "taker",
        }
    )
    st.dataframe(view, hide_index=True, use_container_width=True)

st.markdown(
    "<div style='text-align: center; color: #888; font-size: 0.85em; margin-top: 2em;'>"
    "Synthetic order flow generated locally; no real market data."
    "</div>",
    unsafe_allow_html=True,
)
