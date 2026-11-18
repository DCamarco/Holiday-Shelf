"""
Holiday Shelf: Streamlit app entry point.
Run: streamlit run app.py

This file only sets up the page, the sidebar and the navigation. Each page lives in its
own file inside views/ (one file per page, each with a render() function), so to change a
page you edit that file. Shared data loaders and shortlist helpers are in shared.py, and
all styling is in ui.py.

Note: the folder is called views/ rather than pages/ on purpose. Streamlit treats a folder
named pages/ as automatic navigation and would add duplicate entries to the sidebar.
"""

import streamlit as st

import ui
from shared import init_state, remove_from_shortlist
from views import (
    banner_performance,
    bundles_cart_rescue,
    opportunity_finder,
    overview,
    season_playbook,
    shelf_scorecard,
    shortlist_builder,
)

st.set_page_config(
    page_title="Holiday Shelf",
    page_icon="🎁",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.apply_theme()
init_state()

# Sidebar order = the order of this dictionary. Add a page by adding one line here.
PAGES = {
    "Overview": overview.render,
    "Shelf Scorecard": shelf_scorecard.render,
    "Opportunity Finder": opportunity_finder.render,
    "Bundles & Cart Rescue": bundles_cart_rescue.render,
    "Banner Performance": banner_performance.render,
    "Season Playbook": season_playbook.render,
    "Shortlist Builder": shortlist_builder.render,
}

ui.sidebar_brand()
page = st.sidebar.radio("Go to", list(PAGES))

ui.sidebar_basket(len(st.session_state.shortlist))
if st.session_state.shortlist:
    with st.sidebar.expander("View shortlist"):
        for name in list(st.session_state.shortlist.keys()):
            c1, c2 = st.columns([4, 1])
            c1.caption(name)
            if c2.button("✕", key=f"remove_{name}"):
                remove_from_shortlist(name)
                st.rerun()

PAGES[page]()
