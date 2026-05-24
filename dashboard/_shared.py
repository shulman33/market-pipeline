"""Shared dashboard helpers used by both pages.

Streamlit's `@st.cache_resource` returns the same singleton across reruns
within a process. Caching here keeps each page from leaking httpx clients on
every refresh.
"""

from __future__ import annotations

import httpx
import streamlit as st

DEFAULT_TIMEOUT_S = 5.0


@st.cache_resource
def http_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT_S)


def footer(text: str) -> None:
    st.markdown(
        "<div style='text-align: center; color: #888; font-size: 0.85em; margin-top: 2em;'>"
        f"{text}"
        "</div>",
        unsafe_allow_html=True,
    )
