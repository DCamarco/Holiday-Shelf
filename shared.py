"""
Holiday Shelf: data loaders and shortlist helpers shared by every page.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"


@st.cache_data
def load_product_summary():
    return pd.read_csv(DATA_DIR / "product_summary.csv")


@st.cache_data
def load_product_prices():
    """Load typical and observed price ranges for each product."""
    orders = pd.read_csv(DATA_DIR / "orders_v2.csv", usecols=["item_name", "price"])
    orders["price"] = pd.to_numeric(orders["price"], errors="coerce")
    orders = orders.dropna(subset=["item_name", "price"])
    return (
        orders.groupby("item_name", as_index=False)
        .agg(
            typical_price=("price", "median"),
            min_price=("price", "min"),
            max_price=("price", "max"),
            price_observations=("price", "count"),
        )
    )


@st.cache_data
def load_weekly():
    return pd.read_csv(DATA_DIR / "weekly.csv", parse_dates=["week_start"])


@st.cache_data
def load_banners():
    path = DATA_DIR / "banner_performance.csv"
    return pd.read_csv(path) if path.exists() else None


@st.cache_data
def load_pairs():
    return pd.read_csv(DATA_DIR / "bundle_pairs.csv")


@st.cache_data
def load_rescue():
    return pd.read_csv(DATA_DIR / "cart_rescue.csv")


@st.cache_data
def load_order_stats():
    """Orders analysed, average products per order, orders with 2+ products."""
    o = pd.read_csv(DATA_DIR / "orders_v2.csv", usecols=["transaction_id"])
    per_order = o.groupby("transaction_id").size()
    return len(per_order), float(per_order.mean()), int((per_order >= 2).sum())


def init_state():
    if "shortlist" not in st.session_state:
        st.session_state.shortlist = {}  # item_name -> row dict


def add_to_shortlist(row: dict, key: str | None = None):
    st.session_state.shortlist[key or row["item_name"]] = row


def remove_from_shortlist(item_name: str):
    st.session_state.shortlist.pop(item_name, None)
