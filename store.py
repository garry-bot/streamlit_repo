import streamlit as st
import pandas as pd
import numpy as np
import time
from library import liquidity_tree
import MetaTrader5 as mt5
import plotly.graph_objects as go

# --- 1. THE STORE (NGXS Logic) ---
class FibStore:
    def __init__(self):
        # Initialize State if not present
        if "fib_history" not in st.session_state:
            st.session_state.fib_history = []
        if "current_pivots" not in st.session_state:
            # Starting defaults
            st.session_state.current_pivots = {"high": 0.0, "low": 0.0}
        if "symbol" not in st.session_state:
            st.session_state.symbol = "XAUUSD"
        if "selectedTimeFrame" not in st.session_state:
            st.session_state.selectedTimeFrame = mt5.TIMEFRAME_M30
        if "theme_mode" not in st.session_state:
            st.session_state.theme_mode = 'dark'
        if "tree_map" not in st.session_state:
            st.session_state.tree_map = {}
    # 1. The Service (Global function)
    
    def prepare_dataSource(self):
        # Defensive check: ensure session state has what we need
        if "symbol" not in st.session_state or "selectedTimeFrame" not in st.session_state:
            return None

        rates = mt5.copy_rates_from_pos(
            st.session_state.symbol, 
            st.session_state.selectedTimeFrame, 
            0, 
            500
        )

        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        # Calculate base bounds
        max_p = df['close'].max()
        min_p = df['close'].min()
        diff = max_p - min_p

        df['max_price'] = max_p
        df['min_price'] = min_p
        df['difference'] = diff

        st.session_state.current_pivots = {"high": max_p, "low": min_p}

        # Run your external logic to attach the tree_map to df.attrs
        liquidity_tree.buildTree(df)
        return df

    # --- SELECTORS ---
    @property
    def history_df(self):
        """Returns the 'Memory' of where levels were."""
        return pd.DataFrame(st.session_state.fib_history)
    
    @property
    def history_list(self):
        return st.session_state.fib_history

    @property
    def symbool(self):
        """Returns the state symbol"""
        return st.session_state.symbol
    @property
    def selectedTimeFrame(self):
        """Returns the state selectedTimeFrame"""
        return st.session_state.selectedTimeFrame
    

    def dispatch_update(self, symbol: str, selectedTimeFrame):
        st.session_state.symbol = symbol
        st.session_state.selectedTimeFrame = selectedTimeFrame

        df = self.prepare_dataSource()
        if df is None:
            return
        df['time'] = pd.to_datetime(df['time'], unit='s')
        # 1. Force conversion to scalar if it's a Series
        if isinstance(df['high'], pd.Series):
            current_val = float(df['high'].iloc[-1])
        else:
            current_val = float(df['high'])
        
        if isinstance(df['low'], pd.Series):
            current_low = float(df['low'].iloc[-1])
        else:
            current_low = float(df['low'])
    
        curr_pivots = st.session_state.current_pivots
        
        # 2. Update logic using only scalar floats
        new_high = max(float(curr_pivots["high"]), current_val)
        new_low = min(float(curr_pivots["low"]), current_low)
        
        st.session_state.current_pivots = {"high": new_high, "low": new_low}
        # CLEAN THE TREE MAP
        st.session_state.tree_map = df.attrs.get('tree_map', {})

        # The Tree now "starts" at the most recent relevant swing
        start_time = df['time'].iloc[0]
        end_time = df['time'].iloc[-1]
        # 3. Save to history
        snapshot = {
            "timestamp": pd.Timestamp.now(),
            "price": current_val,
            "high": new_high,
            "low": new_low,
            "start_time": start_time,
            "end_time": end_time,
            "close": float(df['close'].iloc[-1]),
            "time": df['time'].iloc[-1]
    }
        st.session_state.fib_history.append(snapshot)

# --- 2. THE UI & REFRESHER ---
st.set_page_config(layout="wide")
store = FibStore()

st.title("📈 Stateful Fibonacci Tracker")
st.write("This chart 'remembers' previous levels and updates every 15 seconds.")

# This fragment acts as our "Subscription/Observer"
@st.fragment(run_every="5s")
def live_dashboard():
    store.dispatch_update(st.session_state.symbol, st.session_state.selectedTimeFrame)
    df = store.history_df
    if df.empty:
        st.warning("⏳ Waiting for the first market tick from MetaTrader 5...")
        return
    else:
        latest_price = df['price'].iloc[-1]
        latest_high = df['high'].iloc[-1]
        latest_low = df['low'].iloc[-1]
        latest_row = df.iloc[-1]
        current_start = latest_row['start_time']
        current_end = latest_row['end_time']
        if current_start == current_end:
            current_start = current_start - pd.Timedelta(minutes=30)
        # DISPLAY METRICS using the scalars
        c1, c2, c3 = st.columns(3)
        c1.metric("Current Price", f"${latest_price:.2f}")
        c2.metric("High", f"${latest_high:.2f}")
        c3.metric("Low", f"${latest_low:.2f}")

        fig = go.Figure()
        tree_map: dict = st.session_state.tree_map

        # Safety: if the map is missing, don't crash, just show price
        if not tree_map:
            print("Warning: tree_map not found in df.attrs")
            tree_map = {}
        theme_mode = st.session_state.theme_mode

        # 1. Setup Theme
        price_color = "white" if theme_mode == "dark" else "black"
        bg_template = "plotly_dark" if theme_mode == "dark" else "plotly_white"

        # df here is store.history_df
        fig.add_trace(go.Scatter(
            x=df['time'],  # This is now a clean column of single timestamps
            y=df['price'], # Using 'price' or 'close' (as long as it's a scalar)
            name="Price Action",
            line=dict(color="#00FF00", width=2)
        ))

        # 3. Visual Styles Mapping
        zones = {
           
            "equilibriumAxis": ["Equilibrium Axis", "#0929c6", "solid", 3],

            # # OTE (Optimal Trade Entry) Range
            "longOTE": ["OTE Range Min", "#045319", "dash", 1],
            "shortOTE": ["OTE Range Max", "#F21808", "dash", 1],


            #Institution Axis
            "top_institution_axis": ["Top Institution Axis", "#9E779E", "dashdot", 1.5],
            "bot_institution_axis": ["Bot Institution Axis", "#9E779E", "dashdot", 1.5],
        }

        # 4. Draw Horizontal Branches
        for key, level_data in tree_map.items():
            if key in zones:
                settings = zones[key]
                try:
                    # Ensure level_price is a single float
                    if isinstance(level_data, (pd.Series, list, np.ndarray)):
                        level_price = float(level_data[0])
                    else:
                        level_price = float(level_data)
                except:
                    continue
                
                # PLOTLY TRACE
                fig.add_trace(go.Scatter(
                    x=[current_start, current_end], # USE THE SCALARS HERE
                    y=[level_price, level_price],   # Same Y for horizontal line
                    mode='lines+text',
                    name=settings[0],
                    text=["", f"  {settings[0]} ({level_price:.2f})"],
                    textposition="middle right",
                    line=dict(color=settings[1], dash=settings[2], width=settings[3]),
                    opacity=0.8,
                    showlegend=False # Cleaner look
                ))

        # 5. Layout Tweaks
        fig.update_layout(
            template=bg_template,
            title="Equinox Liquidity Tree Structure",
            xaxis_title="Timeline",
            yaxis_title="Price",
            hovermode="x unified",
            height=550,
            margin=dict(r=180), # Increased margin to fit the price labels
            showlegend=True
        )
        st.plotly_chart(fig, use_container_width=True)

# Execute the fragment
live_dashboard()
