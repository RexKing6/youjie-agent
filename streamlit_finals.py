"""Recorded finals interface; no model or enterprise-system access."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title='有界｜决赛演示回放',layout='wide',initial_sidebar_state='collapsed')
st.markdown('<style>.block-container{padding:0;max-width:none}header[data-testid="stHeader"]{display:none}</style>',unsafe_allow_html=True)
assets=Path(__file__).resolve().parent/'showcase_static'
if not (assets/'index.html').is_file():
    st.error('决赛展示资源尚未构建。')
    st.stop()
showcase=components.declare_component('youjie_finals_showcase',path=str(assets))
showcase(key='finals-recording')
