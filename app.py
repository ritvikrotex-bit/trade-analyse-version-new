import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
from datetime import datetime
import plotly.express as px
from io import BytesIO
import json
import math
import uuid
import re

# --- Page Configuration ---
st.set_page_config(page_title="Trade Analyzer & IP Lookup", page_icon="📊", layout="wide")

# --- Initialize Session State ---
if 'ip_history' not in st.session_state:
    st.session_state.ip_history = []

def analyze_trades(uploaded_file, scalping_threshold_seconds: int = 180):
    """Analyze trading positions from Excel file"""
    try:
        df = pd.read_excel(uploaded_file, sheet_name=0, header=None)

        # --- Find Positions section ---
        start_idx = df.index[df[0].astype(str).str.contains('Positions', case=False, na=False)].tolist()
        end_idx = df.index[df[0].astype(str).str.contains('Orders', case=False, na=False)].tolist()

        if not start_idx:
            st.error("Could not find 'Positions' section in the file.")
            return None

        start = start_idx[0] + 1
        end = end_idx[0] if end_idx else len(df)
        positions_raw = df.iloc[start:end]

        positions_raw = positions_raw.dropna(how='all')
        positions_raw.columns = positions_raw.iloc[0]
        positions_df = positions_raw[1:].reset_index(drop=True)

        # --- Rename key columns ---
        positions_df = positions_df.rename(columns={
            'Time': 'Open Time',
            'Price': 'Open Price'
        })
        positions_df.columns.values[8] = 'Close Time'
        positions_df.columns.values[9] = 'Close Price'

        # --- Convert datetime (supporting milliseconds) ---
        positions_df['Open Time'] = pd.to_datetime(
            positions_df['Open Time'], format='%Y.%m.%d %H:%M:%S.%f', errors='coerce'
        ).fillna(pd.to_datetime(positions_df['Open Time'], format='%Y.%m.%d %H:%M:%S', errors='coerce'))
        positions_df['Close Time'] = pd.to_datetime(
            positions_df['Close Time'], format='%Y.%m.%d %H:%M:%S.%f', errors='coerce'
        ).fillna(pd.to_datetime(positions_df['Close Time'], format='%Y.%m.%d %H:%M:%S', errors='coerce'))

        # --- Numeric conversions ---
        positions_df['Profit'] = pd.to_numeric(positions_df['Profit'], errors='coerce')
        positions_df['Volume'] = pd.to_numeric(positions_df.get('Volume', 0), errors='coerce').fillna(0)

        # --- Core calculations ---
        positions_df['Hold_Time'] = positions_df['Close Time'] - positions_df['Open Time']
        total_volume = positions_df['Volume'].sum()

        # --- Identify scalping trades: user-defined threshold (in seconds) ---
        scalping_tdelta = pd.Timedelta(seconds=int(scalping_threshold_seconds))
        scalping_df = positions_df[positions_df['Hold_Time'] <= scalping_tdelta]

        # --- Identify reversal trades (opposite type within 20s, same symbol) ---
        positions_df = positions_df.sort_values(by='Open Time').reset_index(drop=True)
        positions_df['Reversal'] = False

        for i in range(1, len(positions_df)):
            prev_close = positions_df.loc[i - 1, 'Close Time']
            curr_open = positions_df.loc[i, 'Open Time']
            prev_type = str(positions_df.loc[i - 1, 'Type']).strip().lower()
            curr_type = str(positions_df.loc[i, 'Type']).strip().lower()
            prev_symbol = str(positions_df.loc[i - 1, 'Symbol']).strip().upper()
            curr_symbol = str(positions_df.loc[i, 'Symbol']).strip().upper()

            if pd.notnull(prev_close) and pd.notnull(curr_open) and prev_symbol == curr_symbol:
                time_diff = abs((curr_open - prev_close).total_seconds())
                if time_diff <= 20 and (
                    (prev_type == 'buy' and curr_type == 'sell') or
                    (prev_type == 'sell' and curr_type == 'buy')
                ):
                    positions_df.loc[i, 'Reversal'] = True

        reversal_df = positions_df[positions_df['Reversal']]
        reversal_count = len(reversal_df)
        reversal_profit = reversal_df['Profit'].sum()

        # --- Identify burst trades (2 or more within 2 seconds) ---
        positions_df['Burst'] = False
        burst_groups = []
        current_group = [0]

        for i in range(1, len(positions_df)):
            prev_open = positions_df.loc[i - 1, 'Open Time']
            curr_open = positions_df.loc[i, 'Open Time']

            if pd.notnull(prev_open) and pd.notnull(curr_open):
                time_diff = abs((curr_open - prev_open).total_seconds())
                if time_diff <= 2:
                    current_group.append(i)
                else:
                    if len(current_group) >= 2:
                        burst_groups.append(current_group)
                    current_group = [i]

        if len(current_group) >= 2:
            burst_groups.append(current_group)

        for group in burst_groups:
            positions_df.loc[group, 'Burst'] = True

        burst_df = positions_df[positions_df['Burst']]
        burst_count = len(burst_df)
        burst_profit = burst_df['Profit'].sum()

        # --- Statistics ---
        total_positions = len(positions_df)
        total_profit = positions_df['Profit'].sum()
        scalping_count = len(scalping_df)
        scalping_profit = scalping_df['Profit'].sum()

        # --- Percentages ---
        scalping_percentage = (scalping_count / total_positions * 100) if total_positions > 0 else 0
        reversal_percentage = (reversal_count / total_positions * 100) if total_positions > 0 else 0
        burst_percentage = (burst_count / total_positions * 100) if total_positions > 0 else 0

        scalping_profit_percentage = (scalping_profit / total_profit * 100) if total_profit != 0 else 0
        reversal_profit_percentage = (reversal_profit / total_profit * 100) if total_profit != 0 else 0
        burst_profit_percentage = (burst_profit / total_profit * 100) if total_profit != 0 else 0

        avg_hold_time = positions_df['Hold_Time'].mean()
        avg_scalping_hold_time = scalping_df['Hold_Time'].mean() if len(scalping_df) > 0 else pd.Timedelta(0)

        # --- Extended metrics ---
        wins = positions_df[positions_df['Profit'] > 0]
        losses = positions_df[positions_df['Profit'] < 0]

        win_rate = len(wins) / total_positions * 100 if total_positions > 0 else 0
        avg_win = wins['Profit'].mean() if len(wins) > 0 else 0.0
        avg_loss = losses['Profit'].mean() if len(losses) > 0 else 0.0
        gross_profit = wins['Profit'].sum()
        gross_loss = losses['Profit'].sum()
        profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else 0.0
        max_win = positions_df['Profit'].max()
        max_loss = positions_df['Profit'].min()
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

        avg_winner_hold = wins['Hold_Time'].mean() if len(wins) > 0 else pd.Timedelta(0)
        avg_loser_hold = losses['Hold_Time'].mean() if len(losses) > 0 else pd.Timedelta(0)
        median_hold = positions_df['Hold_Time'].median()

        # Equity / drawdown (sorted by close time)
        eq_df = positions_df.sort_values('Close Time').reset_index(drop=True)
        equity_curve = eq_df['Profit'].cumsum()
        rolling_peak = equity_curve.cummax()
        drawdown_series = equity_curve - rolling_peak
        max_drawdown = drawdown_series.min()

        # Loss streak
        max_streak = streak = 0
        for p in eq_df['Profit']:
            if p < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        worst_loss_streak = max_streak

        # Best / worst day
        daily_pnl = eq_df.groupby(eq_df['Close Time'].dt.date)['Profit'].sum()
        best_day = daily_pnl.max()
        worst_day = daily_pnl.min()

        # Buy vs Sell
        buy_df = positions_df[positions_df['Type'].astype(str).str.lower() == 'buy']
        sell_df = positions_df[positions_df['Type'].astype(str).str.lower() == 'sell']
        buy_count = len(buy_df)
        buy_net = buy_df['Profit'].sum()
        sell_count = len(sell_df)
        sell_net = sell_df['Profit'].sum()

        # Symbol concentration
        symbol_counts = positions_df['Symbol'].value_counts()
        top_symbol = symbol_counts.index[0] if len(symbol_counts) > 0 else "N/A"
        symbol_concentration = symbol_counts.iloc[0] / total_positions * 100 if total_positions > 0 else 0.0

        # Session / hourly
        hourly = positions_df.groupby(positions_df['Open Time'].dt.hour)['Profit'].agg(['sum', 'count', 'mean'])
        hourly.index.name = 'Hour'
        dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        daily_dow = positions_df.groupby(positions_df['Open Time'].dt.day_name())['Profit'].agg(['sum', 'count', 'mean'])
        daily_dow = daily_dow.reindex([d for d in dow_order if d in daily_dow.index])

        # Martingale score
        martingale_flags = 0
        for i in range(1, len(eq_df)):
            if eq_df.loc[i - 1, 'Profit'] < 0 and eq_df.loc[i, 'Volume'] > eq_df.loc[i - 1, 'Volume']:
                martingale_flags += 1
        martingale_score = martingale_flags / (total_positions - 1) * 100 if total_positions > 1 else 0.0

        # Toxic %
        toxic_count = scalping_count + reversal_count + burst_count
        toxic_percentage = toxic_count / total_positions * 100 if total_positions > 0 else 0.0

        # Behavioral classification
        avg_hold_minutes = avg_hold_time.total_seconds() / 60 if pd.notna(avg_hold_time) else 0
        if avg_hold_minutes < 5 and scalping_percentage > 50:
            flow_classification = "High-risk scalper flow"
        elif martingale_score > 30:
            flow_classification = "Martingale/averaging flow"
        elif avg_hold_minutes < 60:
            flow_classification = "Intraday active flow"
        else:
            flow_classification = "Swing/positional flow"

        # Dealer decision
        if profit_factor < 0.8 and max_drawdown < -5000 and toxic_percentage > 50:
            dealer_decision = "B-Book – high confidence"
        elif profit_factor < 1.0:
            dealer_decision = "B-Book – moderate confidence"
        elif profit_factor > 1.5 and max_drawdown > -3000:
            dealer_decision = "A-Book candidate"
        else:
            dealer_decision = "Review required"

        # Add a Scalping flag column to positions_df so all three flag columns
        # (Scalping/Reversal/Burst) are aligned for the multi-sheet Excel export
        positions_df['Scalping'] = positions_df['Hold_Time'] <= scalping_tdelta

        # ── Top P&L contributors (Pareto / concentration analysis, ≥70%) ──
        THRESHOLD_PCT = 0.70

        winners_sorted = positions_df[positions_df['Profit'] > 0].sort_values('Profit', ascending=False)
        gross_profit_sum = winners_sorted['Profit'].sum()
        top_profit_contributors_df = pd.DataFrame()
        top_profit_count = 0
        top_profit_pct_of_count = 0.0
        top_profit_pct_of_gross = 0.0
        if gross_profit_sum > 0 and len(winners_sorted) > 0:
            winners_sorted = winners_sorted.copy()
            winners_sorted['Pct_of_Gross_Profit'] = (winners_sorted['Profit'] / gross_profit_sum * 100).round(2)
            winners_sorted['Cumulative_Profit'] = winners_sorted['Profit'].cumsum().round(2)
            winners_sorted['Cumulative_Pct'] = (winners_sorted['Cumulative_Profit'] / gross_profit_sum * 100).round(2)
            threshold_amt = gross_profit_sum * THRESHOLD_PCT
            cutoff_mask = winners_sorted['Cumulative_Profit'] >= threshold_amt
            if cutoff_mask.any():
                cutoff_label = cutoff_mask.idxmax()
                cutoff_pos = winners_sorted.index.get_loc(cutoff_label)
                top_profit_contributors_df = winners_sorted.iloc[:cutoff_pos + 1].copy()
                top_profit_count = len(top_profit_contributors_df)
                top_profit_pct_of_count = (top_profit_count / total_positions * 100) if total_positions > 0 else 0
                top_profit_pct_of_gross = (top_profit_contributors_df['Profit'].sum() / gross_profit_sum * 100)

        losers_sorted = positions_df[positions_df['Profit'] < 0].sort_values('Profit', ascending=True)
        gross_loss_abs = abs(losers_sorted['Profit'].sum())
        top_loss_contributors_df = pd.DataFrame()
        top_loss_count = 0
        top_loss_pct_of_count = 0.0
        top_loss_pct_of_gross = 0.0
        if gross_loss_abs > 0 and len(losers_sorted) > 0:
            losers_sorted = losers_sorted.copy()
            losers_sorted['Pct_of_Gross_Loss'] = (losers_sorted['Profit'].abs() / gross_loss_abs * 100).round(2)
            losers_sorted['Cumulative_Loss'] = losers_sorted['Profit'].cumsum().round(2)
            losers_sorted['Cumulative_Pct'] = (losers_sorted['Cumulative_Loss'].abs() / gross_loss_abs * 100).round(2)
            threshold_amt = -gross_loss_abs * THRESHOLD_PCT
            cutoff_mask = losers_sorted['Cumulative_Loss'] <= threshold_amt
            if cutoff_mask.any():
                cutoff_label = cutoff_mask.idxmax()
                cutoff_pos = losers_sorted.index.get_loc(cutoff_label)
                top_loss_contributors_df = losers_sorted.iloc[:cutoff_pos + 1].copy()
                top_loss_count = len(top_loss_contributors_df)
                top_loss_pct_of_count = (top_loss_count / total_positions * 100) if total_positions > 0 else 0
                top_loss_pct_of_gross = (top_loss_contributors_df['Profit'].abs().sum() / gross_loss_abs * 100)

        max_win_row = positions_df.loc[[positions_df['Profit'].idxmax()]] if total_positions > 0 else pd.DataFrame()
        max_loss_row = positions_df.loc[[positions_df['Profit'].idxmin()]] if total_positions > 0 else pd.DataFrame()

        # --- Return structured results ---
        return {
            "total_positions": total_positions,
            "total_profit": total_profit,
            "total_volume": total_volume,
            "scalping_count": scalping_count,
            "scalping_profit": scalping_profit,
            "scalping_percentage": scalping_percentage,
            "scalping_profit_percentage": scalping_profit_percentage,
            "reversal_count": reversal_count,
            "reversal_profit": reversal_profit,
            "reversal_percentage": reversal_percentage,
            "reversal_profit_percentage": reversal_profit_percentage,
            "burst_count": burst_count,
            "burst_profit": burst_profit,
            "burst_percentage": burst_percentage,
            "burst_profit_percentage": burst_profit_percentage,
            "avg_hold_time": avg_hold_time,
            "avg_scalping_hold_time": avg_scalping_hold_time,
            "scalping_df": scalping_df,
            "reversal_df": reversal_df,
            "burst_df": burst_df,
            "all_positions_df": positions_df,
            # extended
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_win": max_win,
            "max_loss": max_loss,
            "expectancy": expectancy,
            "avg_winner_hold": avg_winner_hold,
            "avg_loser_hold": avg_loser_hold,
            "median_hold": median_hold,
            "eq_df": eq_df,
            "equity_curve": equity_curve,
            "drawdown_series": drawdown_series,
            "max_drawdown": max_drawdown,
            "worst_loss_streak": worst_loss_streak,
            "daily_pnl": daily_pnl,
            "best_day": best_day,
            "worst_day": worst_day,
            "buy_count": buy_count,
            "buy_net": buy_net,
            "sell_count": sell_count,
            "sell_net": sell_net,
            "top_symbol": top_symbol,
            "symbol_concentration": symbol_concentration,
            "hourly": hourly,
            "daily_dow": daily_dow,
            "martingale_score": martingale_score,
            "toxic_percentage": toxic_percentage,
            "flow_classification": flow_classification,
            "dealer_decision": dealer_decision,
            # concentration / pareto
            "top_profit_contributors_df": top_profit_contributors_df,
            "top_profit_count": top_profit_count,
            "top_profit_pct_of_count": top_profit_pct_of_count,
            "top_profit_pct_of_gross": top_profit_pct_of_gross,
            "top_loss_contributors_df": top_loss_contributors_df,
            "top_loss_count": top_loss_count,
            "top_loss_pct_of_count": top_loss_pct_of_count,
            "top_loss_pct_of_gross": top_loss_pct_of_gross,
            "max_win_row": max_win_row,
            "max_loss_row": max_loss_row,
        }

    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        return None


# --- Bulk Helpers ---
@st.cache_data(show_spinner=False)
def _analyze_bytes(file_bytes: bytes, filename: str, scalping_threshold_seconds: int = 180):
    """Cached wrapper: hashable bytes input → analyze_trades result."""
    return analyze_trades(BytesIO(file_bytes), scalping_threshold_seconds)


def _build_overview_excel(result: dict, account_no: str) -> BytesIO:
    """Multi-sheet Excel with full proof: every trade flagged for category + per-flag sheets + summary."""
    buf = BytesIO()
    pos = result['all_positions_df'].copy()

    def _yn(col_name):
        if col_name in pos.columns:
            return pos[col_name].fillna(False).map({True: 'Y', False: ''})
        return ''

    max_w = result.get('max_win')
    max_l = result.get('max_loss')
    top_p_idx = set(result['top_profit_contributors_df'].index) if not result['top_profit_contributors_df'].empty else set()
    top_l_idx = set(result['top_loss_contributors_df'].index) if not result['top_loss_contributors_df'].empty else set()

    pos['Is_Scalping']               = _yn('Scalping')
    pos['Is_Reversal']               = _yn('Reversal')
    pos['Is_Burst']                  = _yn('Burst')
    pos['Is_Max_Win']                = pos['Profit'].apply(lambda p: 'Y' if p == max_w else '')
    pos['Is_Max_Loss']               = pos['Profit'].apply(lambda p: 'Y' if p == max_l else '')
    pos['Is_Top_Profit_Contributor'] = pos.index.map(lambda i: 'Y' if i in top_p_idx else '')
    pos['Is_Top_Loss_Contributor']   = pos.index.map(lambda i: 'Y' if i in top_l_idx else '')

    base_cols = [c for c in ['Symbol', 'Type', 'Open Time', 'Close Time', 'Volume', 'Profit', 'Hold_Time'] if c in pos.columns]
    flag_cols = ['Is_Scalping', 'Is_Reversal', 'Is_Burst', 'Is_Max_Win', 'Is_Max_Loss', 'Is_Top_Profit_Contributor', 'Is_Top_Loss_Contributor']
    pos_out = pos[base_cols + flag_cols]

    summary_rows = [
        ('Account', account_no),
        ('Total Trades', result['total_positions']),
        ('Net Profit', f"${result['total_profit']:.2f}"),
        ('Win Rate %', f"{result['win_rate']:.2f}"),
        ('Profit Factor', f"{result['profit_factor']:.2f}"),
        ('Max Win', f"${result['max_win']:.2f}"),
        ('Max Loss', f"${result['max_loss']:.2f}"),
        ('Max Drawdown', f"${result['max_drawdown']:.2f}"),
        ('Worst Loss Streak', result['worst_loss_streak']),
        ('Scalping Trades', result['scalping_count']),
        ('Reversal Trades', result['reversal_count']),
        ('Burst Trades', result['burst_count']),
        ('Toxic %', f"{result['toxic_percentage']:.2f}"),
        ('— Top Profit Contributors (≥70% of gross profit) —', ''),
        ('  ↳ Trade Count', result['top_profit_count']),
        ('  ↳ % of total trade count', f"{result['top_profit_pct_of_count']:.2f}%"),
        ('  ↳ % of gross profit explained', f"{result['top_profit_pct_of_gross']:.2f}%"),
        ('— Top Loss Contributors (≥70% of gross loss) —', ''),
        ('  ↳ Trade Count', result['top_loss_count']),
        ('  ↳ % of total trade count', f"{result['top_loss_pct_of_count']:.2f}%"),
        ('  ↳ % of gross loss explained', f"{result['top_loss_pct_of_gross']:.2f}%"),
        ('Dealer Decision', result['dealer_decision']),
        ('Flow Classification', result['flow_classification']),
    ]
    summary_df = pd.DataFrame(summary_rows, columns=['Metric', 'Value'])

    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        summary_df.to_excel(w, index=False, sheet_name='Summary')
        pos_out.to_excel(w, index=False, sheet_name='All Trades (Flagged)')
        if not result['top_profit_contributors_df'].empty:
            result['top_profit_contributors_df'].to_excel(w, index=False, sheet_name='Top Profit (≥70%)')
        if not result['top_loss_contributors_df'].empty:
            result['top_loss_contributors_df'].to_excel(w, index=False, sheet_name='Top Loss (≥70%)')
        if not result['max_win_row'].empty:
            result['max_win_row'].to_excel(w, index=False, sheet_name='Max Win Trade')
        if not result['max_loss_row'].empty:
            result['max_loss_row'].to_excel(w, index=False, sheet_name='Max Loss Trade')
        if result['scalping_count'] > 0:
            result['scalping_df'].to_excel(w, index=False, sheet_name='Scalping Trades')
        if result['reversal_count'] > 0:
            result['reversal_df'].to_excel(w, index=False, sheet_name='Reversal Trades')
        if result['burst_count'] > 0:
            result['burst_df'].to_excel(w, index=False, sheet_name='Burst Trades')

    buf.seek(0)
    return buf


def _build_comparison_df(results):
    """results: list of (filename, account_no, result_dict). Build the comparison DataFrame."""
    rows = []
    for fname, acc, r in results:
        if r is None:
            continue
        rows.append({
            "Account": acc,
            "File": fname,
            "Trades": r["total_positions"],
            "Net Profit": float(r["total_profit"]),
            "Win Rate %": round(r["win_rate"], 2),
            "Profit Factor": round(r["profit_factor"], 2),
            "Expectancy": round(r["expectancy"], 2),
            "Max Drawdown": float(r["max_drawdown"]),
            "Loss Streak": r["worst_loss_streak"],
            "Top Symbol": r["top_symbol"],
            "Concentration %": round(r["symbol_concentration"], 2),
            "Toxic %": round(r["toxic_percentage"], 2),
            "Flow": r["flow_classification"],
            "Dealer Decision": r["dealer_decision"],
        })
    return pd.DataFrame(rows)


def _build_client_report(account_no: str, r: dict, scalping_choice: int, ip_country: str = "N/A") -> str:
    pattern_notes = []
    if r["scalping_percentage"] > 30:
        pattern_notes.append("Scalping")
    if r["reversal_count"] > 0 and r["reversal_percentage"] > 0:
        pattern_notes.append("Hedging/Reversal")
    if r["burst_count"] > 5:
        pattern_notes.append("Burst/High-Frequency")
    trading_pattern = ", ".join(pattern_notes) if pattern_notes else "Normal Trading Flow"
    return (
        f"Account: {account_no}\n"
        f"Total Trades: {r['total_positions']}\n"
        f"Total Profit: ${r['total_profit']:.2f}\n"
        f"Scalping Trades: {r['scalping_count']} ({r['scalping_percentage']:.1f}% of total)\n"
        f"Scalping Profit: ${r['scalping_profit']:.2f} ({r['scalping_profit_percentage']:.1f}% of total profit)\n"
        f"Reversal Trades: {r['reversal_count']} ({r['reversal_percentage']:.1f}% of total)\n"
        f"Reversal Profit: ${r['reversal_profit']:.2f} ({r['reversal_profit_percentage']:.1f}% of total profit)\n"
        f"Burst Trades: {r['burst_count']} [{r['burst_percentage']:.1f}% of total]\n"
        f"Burst Profit: ${r['burst_profit']:.2f} [{r['burst_profit_percentage']:.1f}% of total profit]\n"
        f"Toxic Trading %: {r['toxic_percentage']:.1f}%\n"
        f"Trading Pattern: {trading_pattern}\n"
        f"Scalping Threshold Used: {scalping_choice} seconds"
    )


def _render_copy_button(report_text: str, button_key: str, show_code: bool = True, label: str = "📋 Copy Report"):
    if show_code:
        st.code(report_text, language=None)
    escaped = json.dumps(report_text)
    label_js = json.dumps(label)
    btn_id = f"copyBtn_{button_key}"
    components.html(
        f"""
        <div style="margin:4px 0 8px 0;">
        <button id="{btn_id}" style="background:linear-gradient(90deg,#3b82f6,#06b6d4);color:#ffffff;border:none;border-radius:8px;padding:.55rem 1rem;font-weight:600;font-family:'DM Sans',Arial,sans-serif;cursor:pointer;box-shadow:0 1px 3px rgba(59,130,246,.25);width:100%;font-size:14px;">
            {label}
        </button>
        </div>
        <script>
        (function(){{
            var b=document.getElementById('{btn_id}');
            if(!b)return;
            b.addEventListener('click',async function(){{
                var t={escaped};
                var ok=false;
                try{{
                    if(navigator.clipboard && window.isSecureContext){{
                        await navigator.clipboard.writeText(t);
                        ok=true;
                    }}
                }}catch(e){{ ok=false; }}
                if(!ok){{
                    try{{
                        var ta=document.createElement('textarea');
                        ta.value=t;
                        ta.setAttribute('readonly','');
                        ta.style.position='fixed';
                        ta.style.top='0';
                        ta.style.left='0';
                        ta.style.opacity='0';
                        document.body.appendChild(ta);
                        ta.focus();
                        ta.select();
                        ta.setSelectionRange(0, t.length);
                        ok = document.execCommand('copy');
                        document.body.removeChild(ta);
                    }}catch(e){{ ok=false; }}
                }}
                b.textContent = ok ? '✅ Copied!' : '⚠️ Copy failed — select text manually';
                setTimeout(function(){{ b.textContent = {label_js}; }}, 2000);
            }});
        }})();
        </script>
        """,
        height=55,
    )


def _render_account_expander(filename: str, account_no: str, r: dict, scalping_choice: int = 180):
    """One drill-down block per file in the bulk view."""
    dealer = r["dealer_decision"]
    flow = r["flow_classification"]
    dealer_color = "#ef4444" if "B-Book" in dealer else ("#10b981" if "A-Book" in dealer else "#f59e0b")

    short_name = filename if len(filename) <= 40 else filename[:37] + "..."
    label = f"📁 Account {account_no} · {short_name} · {dealer}"
    with st.expander(label, expanded=False):
        st.markdown(
            f"<div style='padding:12px;border-radius:8px;background:rgba(233,238,251,0.7);border-left:5px solid {dealer_color};margin-bottom:10px'>"
            f"<span style='font-weight:600;color:{dealer_color}'>Dealer Decision: {dealer}</span> &nbsp;·&nbsp; "
            f"<span style='color:#333'>Flow: <b>{flow}</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        c = st.columns(3)
        c[0].metric("Net Profit", f"${r['total_profit']:.2f}")
        c[1].metric("Win Rate %", f"{r['win_rate']:.2f}")
        c[2].metric("Profit Factor", f"{r['profit_factor']:.2f}")

        c2 = st.columns(3)
        c2[0].metric("Max Drawdown", f"${r['max_drawdown']:.2f}")
        c2[1].metric("Worst Loss Streak", r['worst_loss_streak'])
        c2[2].metric("Symbol Concentration %", f"{r['symbol_concentration']:.2f}")

        c3 = st.columns(3)
        c3[0].metric("Avg Win", f"${r['avg_win']:.2f}")
        c3[1].metric("Avg Loss", f"${r['avg_loss']:.2f}")
        c3[2].metric("Toxic %", f"{r['toxic_percentage']:.2f}")

        flags = []
        if r['symbol_concentration'] > 80:
            flags.append(f"⚠️ High symbol concentration — {r['symbol_concentration']:.1f}% on **{r['top_symbol']}**")
        if r['max_drawdown'] < -10000:
            flags.append(f"🔴 Severe drawdown: **${r['max_drawdown']:.2f}**")
        elif r['max_drawdown'] < -3000:
            flags.append(f"🟡 Elevated drawdown: **${r['max_drawdown']:.2f}**")
        if r['profit_factor'] < 1.0:
            flags.append("🔴 Profit Factor below 1.0 — net losing strategy")
        if r['martingale_score'] > 30:
            flags.append(f"⚠️ Martingale/averaging pattern ({r['martingale_score']:.1f}%)")
        if r['avg_loss'] != 0 and r['avg_win'] > 0 and abs(r['avg_loss']) > r['avg_win'] * 3:
            flags.append(f"⚠️ Loss asymmetry: avg loss is {abs(r['avg_loss']) / r['avg_win']:.1f}× the avg win")
        if r['toxic_percentage'] > 50:
            flags.append(f"🔴 High flagged trade rate: {r['toxic_percentage']:.1f}%")
        if flags:
            st.markdown("**Risk Flags:**")
            for f in flags:
                st.markdown(f)

        st.markdown("---")
        st.markdown("**📄 Client Report**")
        _render_copy_button(
            _build_client_report(account_no, r, scalping_choice),
            f"{account_no}_{uuid.uuid4().hex[:6]}"
        )


def _render_bulk_view(uploaded_files, scalping_choice: int):
    """Top-level bulk renderer: process files, render summary, table, expanders."""
    st.subheader(f"📦 Bulk Comparison — {len(uploaded_files)} files")

    results = []
    errors = []
    prog = st.progress(0.0)
    status = st.empty()

    for i, f in enumerate(uploaded_files):
        status.write(f"Processing {f.name} ({i + 1}/{len(uploaded_files)})...")
        try:
            r = _analyze_bytes(f.getvalue(), f.name, scalping_choice)
            if r is None:
                errors.append((f.name, "Could not parse file (no Positions section found)"))
            else:
                acc_match = re.search(r"ReportHistory[-_ ]?(\d+)", f.name)
                acc = acc_match.group(1) if acc_match else "Unknown"
                results.append((f.name, acc, r))
        except Exception as exc:
            errors.append((f.name, str(exc)))
        prog.progress((i + 1) / len(uploaded_files))

    status.empty()
    prog.empty()

    # Inline errors first so user sees what's wrong
    for fname, err in errors:
        st.error(f"❌ {fname}: {err}")

    if not results:
        st.warning("No files were processed successfully.")
        return

    # ── Summary header ──────────────────────────────────────────────────────
    total_accounts = len(results)
    agg_profit = sum(r["total_profit"] for _, _, r in results)
    agg_trades = sum(r["total_positions"] for _, _, r in results)
    a_book = sum(1 for _, _, r in results if "A-Book" in r["dealer_decision"])
    b_book_high = sum(1 for _, _, r in results if "B-Book – high" in r["dealer_decision"])
    b_book_mod = sum(1 for _, _, r in results if "B-Book – moderate" in r["dealer_decision"])
    review = sum(1 for _, _, r in results if "Review" in r["dealer_decision"])

    s = st.columns(4)
    s[0].metric("Accounts Processed", total_accounts)
    s[1].metric("Aggregate Net P&L", f"${agg_profit:.2f}")
    s[2].metric("Total Trades", agg_trades)
    s[3].metric(
        "Decision Mix",
        f"{a_book} A-Book",
        delta=f"{b_book_high} B-Hi · {b_book_mod} B-Mod · {review} Review",
        delta_color="off",
    )

    # ── Comparison table ────────────────────────────────────────────────────
    st.subheader("📊 Comparison Table")
    df_summary = _build_comparison_df(results)
    st.dataframe(
        df_summary,
        use_container_width=True,
        height=min(400, 60 + 35 * len(df_summary)),
        column_config={
            "Net Profit": st.column_config.NumberColumn(format="$%.2f"),
            "Max Drawdown": st.column_config.NumberColumn(format="$%.2f"),
            "Expectancy": st.column_config.NumberColumn(format="$%.2f"),
            "Win Rate %": st.column_config.NumberColumn(format="%.2f"),
            "Profit Factor": st.column_config.NumberColumn(format="%.2f"),
            "Concentration %": st.column_config.NumberColumn(format="%.2f"),
            "Toxic %": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.download_button(
        "📥 Download Comparison CSV",
        df_summary.to_csv(index=False).encode("utf-8"),
        file_name="bulk_comparison.csv",
        mime="text/csv",
        key="bulk_csv_download",
    )

    # ── Per-account drill-down expanders ────────────────────────────────────
    st.subheader("🔍 Per-Account Drill-Down")
    for fname, acc, r in results:
        _render_account_expander(fname, acc, r, scalping_choice)

    # ── All client reports stacked ───────────────────────────────────────────
    st.markdown("---")
    st.subheader("📄 Client Reports")

    # Build combined report for bulk copy/download
    separator = "\n" + ("=" * 60) + "\n\n"
    combined_sections = []
    for fname, acc, r in results:
        section = f"Account {acc}\n{'-' * 60}\n" + _build_client_report(acc, r, scalping_choice)
        combined_sections.append(section)
    combined_report = separator.join(combined_sections)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bulk_cols = st.columns([1, 1])
    with bulk_cols[0]:
        st.download_button(
            "📥 Download All Reports (.txt)",
            combined_report.encode("utf-8"),
            file_name=f"client_reports_{timestamp}.txt",
            mime="text/plain",
            key="bulk_reports_download",
            use_container_width=True,
        )
    with bulk_cols[1]:
        _render_copy_button(
            combined_report,
            f"bulk_all_{uuid.uuid4().hex[:6]}",
            show_code=False,
            label="📋 Copy All Reports",
        )

    st.markdown("---")

    for fname, acc, r in results:
        st.markdown(f"**Account {acc}**")
        _render_copy_button(
            _build_client_report(acc, r, scalping_choice),
            f"bulk_{acc}_{uuid.uuid4().hex[:6]}"
        )
        st.markdown("---")


# --- IP Lookup Helpers ---
def get_ip_details(ip_address):
    try:
        response = requests.get(f'https://ipinfo.io/{ip_address}/json', timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def add_ip_to_history(ip, details):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"timestamp": timestamp, "ip": ip, "details": details}
    st.session_state.ip_history.insert(0, entry)
    if len(st.session_state.ip_history) > 10:
        st.session_state.ip_history = st.session_state.ip_history[:10]


# ---------- CSS — Light Finance-Terminal Theme ----------
theme_css_light = r"""
<style>
/* ── FONT IMPORTS ───────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* ── DESIGN TOKENS ──────────────────────────────────────────────────────── */
:root {
  --bg-page       : #e9eefb;
  --bg-panel      : #ffffff;
  --bg-panel-grad : linear-gradient(180deg, #ffffff 0%, #f4f7fe 100%);
  --bg-panel-alt  : #f4f7fe;
  --bg-stripe     : #e8eefa;
  --border        : #c8d3ee;
  --border-muted  : #dde5f7;
  --accent        : #3b82f6;
  --accent-mid    : #06b6d4;
  --accent-violet : #8b5cf6;
  --accent-soft   : #dbeafe;
  --accent-teal   : #0891b2;
  --profit        : #10b981;
  --loss          : #ef4444;
  --warn          : #f59e0b;
  --text          : #0f172a;
  --text-muted    : #64748b;
  --font-ui       : 'DM Sans', system-ui, -apple-system, sans-serif;
  --font-mono     : 'JetBrains Mono', 'Courier New', monospace;
  --gradient-bar  : linear-gradient(90deg, #3b82f6 0%, #06b6d4 50%, #8b5cf6 100%);
  --shadow-card   : 0 1px 3px rgba(59,130,246,.08), 0 4px 16px rgba(59,130,246,.06);
  --shadow-hover  : 0 6px 24px rgba(59,130,246,.18);
  --radius        : 14px;
  /* legacy aliases */
  --bg            : var(--bg-panel);
  --panel         : var(--bg-stripe);
  --accent-1      : var(--accent);
  --accent-2      : var(--accent-mid);
}

/* ── BASE ───────────────────────────────────────────────────────────────── */
html, body {
  overflow-x  : hidden !important;
  font-family : var(--font-ui) !important;
  background  : var(--bg-page) !important;
  color       : var(--text) !important;
}

/* ── 3-PX ACCENT STRIPE (Bloomberg-style top bar) ───────────────────────── */
body::before {
  content    : '';
  display    : block;
  position   : fixed;
  top        : 0; left: 0;
  width      : 100%;
  height     : 3px;
  background : var(--gradient-bar);
  z-index    : 9999;
}

/* ── DOT-GRID TEXTURE (repurposed from old .stv-wave div) ───────────────── */
.stv-wave {
  position         : fixed !important;
  top: 0; left: 0;
  width            : 100vw !important;
  height           : 100vh !important;
  z-index          : -1 !important;
  pointer-events   : none !important;
  background-color : var(--bg-page) !important;
  background-image : radial-gradient(circle, rgba(67,97,238,.10) 1.5px, transparent 1.5px) !important;
  background-size  : 20px 20px !important;
  animation        : none !important;
  opacity          : 1 !important;
}

/* ── SHELL / CHROME ─────────────────────────────────────────────────────── */
[data-testid="stSidebar"]      { display: none !important; }
header[data-testid="stHeader"] { display: none !important; }

/* ── MAIN CONTAINER ─────────────────────────────────────────────────────── */
.main .block-container {
  background-color : transparent !important;
  color            : var(--text) !important;
  max-width        : 100% !important;
  padding-left     : 2rem !important;
  padding-right    : 2rem !important;
  padding-top      : 1.5rem !important;
}

/* ── TYPOGRAPHY ─────────────────────────────────────────────────────────── */
h1,h2,h3,h4,h5,h6,p,span,label,div,
[data-testid="stMarkdownContainer"] {
  color       : var(--text) !important;
  font-family : var(--font-ui) !important;
}

h1 { font-size: 1.75rem !important; font-weight: 700 !important; letter-spacing: -.02em !important; }

h2 {
  font-size     : 1.2rem !important;
  font-weight   : 600 !important;
  border-bottom : 2px solid var(--border) !important;
  padding-bottom: .4rem !important;
  margin-bottom : .9rem !important;
}

h3 {
  font-size   : 1rem !important;
  font-weight : 600 !important;
  color       : var(--accent) !important;
}

/* ── METRIC CARDS ───────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
  background    : var(--bg-panel-grad) !important;
  border        : 1px solid var(--border) !important;
  border-radius : var(--radius) !important;
  box-shadow    : var(--shadow-card) !important;
  padding       : 1rem 1.1rem !important;
  position      : relative !important;
  overflow      : hidden !important;
  transition    : box-shadow .2s ease, transform .15s ease !important;
}

[data-testid="stMetric"]::before {
  content    : '';
  position   : absolute;
  top        : 0; left: 0;
  width      : 100%;
  height     : 2px;
  background : var(--gradient-bar);
  opacity    : .85;
}

[data-testid="stMetric"]:hover {
  box-shadow : var(--shadow-hover) !important;
  transform  : translateY(-1px) !important;
}

[data-testid="stMetricLabel"] > div,
[data-testid="stMetricLabel"] label,
[data-testid="stMetricLabel"] p {
  font-family    : var(--font-ui) !important;
  font-size      : 11px !important;
  font-weight    : 500 !important;
  text-transform : uppercase !important;
  letter-spacing : 1.2px !important;
  color          : var(--text-muted) !important;
}

[data-testid="stMetricValue"] > div,
[data-testid="stMetricValue"] {
  font-family : var(--font-mono) !important;
  font-size   : 1.55rem !important;
  font-weight : 700 !important;
  color       : var(--text) !important;
  line-height : 1.2 !important;
}

[data-testid="stMetricDelta"] > div {
  font-family : var(--font-mono) !important;
  font-size   : .75rem !important;
}

/* ── BUTTONS ────────────────────────────────────────────────────────────── */
.stButton > button,
button[data-testid*="baseButton-secondary"],
button[data-testid*="baseButton-primary"],
[data-testid*="stDownloadButton"] > button,
[data-testid*="stDownloadButton"] button {
  background    : var(--accent) !important;
  color         : #ffffff !important;
  border        : none !important;
  border-radius : 8px !important;
  font-family   : var(--font-ui) !important;
  font-weight   : 600 !important;
  font-size     : .875rem !important;
  letter-spacing: .02em !important;
  padding       : .5rem 1.1rem !important;
  transition    : background .2s ease, box-shadow .2s ease, transform .15s ease !important;
  box-shadow    : 0 1px 3px rgba(67,97,238,.22) !important;
}

.stButton > button:hover,
button[data-testid*="baseButton-secondary"]:hover,
button[data-testid*="baseButton-primary"]:hover,
[data-testid*="stDownloadButton"] > button:hover,
[data-testid*="stDownloadButton"] button:hover {
  background  : var(--accent-mid) !important;
  box-shadow  : var(--shadow-hover) !important;
  transform   : translateY(-1px) !important;
}

/* ── FILE UPLOADER ──────────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
  background    : var(--bg-panel) !important;
  border-radius : var(--radius) !important;
}

[data-testid="stFileUploader"] section,
[data-testid="stFileUploaderDropzone"] {
  border        : 1.5px dashed var(--border) !important;
  border-radius : var(--radius) !important;
  padding       : 1rem 1.25rem !important;
  min-height    : 96px !important;
}

/* Hide Material-icon ligature fallback text inside the uploader button
   that renders as literal "upload" before the icon font finishes loading. */
[data-testid="stFileUploader"] button [data-testid="stIconMaterial"],
[data-testid="stFileUploaderDropzone"] button [data-testid="stIconMaterial"],
[data-testid="stBaseButton-secondary"] [data-testid="stIconMaterial"] {
  font-family : 'Material Symbols Outlined', 'Material Symbols Rounded',
                'Material Icons' !important;
  font-weight : normal !important;
  font-style  : normal !important;
  font-size   : 1.1rem !important;
  line-height : 1 !important;
  font-feature-settings: 'liga' !important;
  -webkit-font-feature-settings: 'liga' !important;
  -webkit-font-smoothing: antialiased !important;
  text-rendering: optimizeLegibility !important;
  direction   : ltr !important;
  white-space : nowrap !important;
  word-wrap   : normal !important;
  display     : inline-block !important;
  width       : 1.1rem !important;
  height      : 1.1rem !important;
  overflow    : hidden !important;
  color       : currentColor !important;
}

/* Final safety net: if the icon font still fails to render and the
   element ends up looking like plain text, hide it so we only see the
   button label instead of "uploadupload". */
@supports not (font-feature-settings: 'liga') {
  [data-testid="stFileUploader"] button [data-testid="stIconMaterial"] {
    display : none !important;
  }
}

[data-testid="stFileUploader"] button,
[data-testid="stFileUploaderDropzone"] button {
  display     : inline-flex !important;
  align-items : center !important;
  gap         : .4rem !important;
}

/* ── TEXT INPUTS ────────────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, select {
  background    : var(--bg-panel) !important;
  color         : var(--text) !important;
  font-family   : var(--font-ui) !important;
  border        : 1px solid var(--border) !important;
  border-radius : 8px !important;
}

/* ── TABS ───────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {
  border-bottom : 2px solid var(--border) !important;
  gap           : .2rem !important;
}

[data-testid="stTabs"] [role="tab"] {
  font-family   : var(--font-ui) !important;
  font-size     : .875rem !important;
  font-weight   : 500 !important;
  color         : var(--text-muted) !important;
  border-radius : 6px 6px 0 0 !important;
  padding       : .45rem 1rem !important;
  transition    : color .15s ease !important;
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color         : var(--accent) !important;
  font-weight   : 600 !important;
  border-bottom : 2px solid var(--accent) !important;
}

/* ── EXPANDERS ──────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
  background    : var(--bg-panel-grad) !important;
  border        : 1px solid var(--border) !important;
  border-top    : 2px solid var(--accent) !important;
  border-radius : var(--radius) !important;
  box-shadow    : var(--shadow-card) !important;
  margin-bottom : .75rem !important;
}

[data-testid="stExpander"] summary {
  font-family  : var(--font-ui) !important;
  font-weight  : 600 !important;
  color        : var(--text) !important;
  padding      : .75rem 1rem !important;
  gap          : 1rem !important;
}

[data-testid="stExpander"] summary svg {
  flex-shrink  : 0 !important;
  margin-right : .25rem !important;
}

[data-testid="stExpander"] summary > div,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {
  margin-left  : 1.25rem !important;
  white-space  : nowrap !important;
  overflow     : hidden !important;
  text-overflow: ellipsis !important;
  min-width    : 0 !important;
}

/* ── DATAFRAME ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
  border        : 1px solid var(--border) !important;
  border-radius : var(--radius) !important;
  overflow      : hidden !important;
  box-shadow    : var(--shadow-card) !important;
}

/* ── CODE BLOCK (client report) ─────────────────────────────────────────── */
[data-testid="stCode"] {
  background    : var(--bg-stripe) !important;
  border        : 1px solid var(--border) !important;
  border-radius : var(--radius) !important;
}

[data-testid="stCode"] pre,
[data-testid="stCode"] code {
  font-family : var(--font-mono) !important;
  font-size   : .8rem !important;
  color       : var(--text) !important;
  background  : transparent !important;
}

/* ── PROGRESS BAR ───────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div {
  background    : var(--gradient-bar) !important;
  border-radius : 999px !important;
}

[data-testid="stProgress"] > div {
  background    : var(--border-muted) !important;
  border-radius : 999px !important;
}

/* ── ALERT BOXES ────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
  border-radius    : var(--radius) !important;
  font-family      : var(--font-ui) !important;
  border-left-width: 4px !important;
}

/* ── DIVIDERS ───────────────────────────────────────────────────────────── */
hr {
  border     : none !important;
  border-top : 1px solid var(--border-muted) !important;
  margin     : 1.25rem 0 !important;
}

/* ── IP LOOKUP CARDS ────────────────────────────────────────────────────── */
.ip-card {
  background    : var(--bg-panel) !important;
  border        : 1px solid var(--border) !important;
  border-radius : var(--radius) !important;
  box-shadow    : var(--shadow-card) !important;
  padding       : 1rem 1.1rem !important;
  margin-bottom : 1.2rem !important;
  text-align    : center !important;
  color         : var(--text) !important;
  transition    : box-shadow .2s ease !important;
}

.ip-card:hover { box-shadow: var(--shadow-hover) !important; }

.ip-card h4 {
  font-family   : var(--font-ui) !important;
  font-size     : 1rem !important;
  font-weight   : 600 !important;
  color         : var(--text) !important;
  margin-bottom : 6px !important;
}

.ip-card p {
  font-family : var(--font-ui) !important;
  font-size   : .875rem !important;
  color       : var(--text-muted) !important;
}

.ip-card hr {
  border     : none !important;
  border-top : 1px solid var(--border-muted) !important;
  margin     : .6rem 0 !important;
}

/* ── CAPTIONS ───────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p, small {
  font-family : var(--font-ui) !important;
  font-size   : .75rem !important;
  color       : var(--text-muted) !important;
}

/* ── LOGO CONTAINERS (unchanged) ────────────────────────────────────────── */
.logo-container {
  display        : flex;
  align-items    : center;
  justify-content: center;
  gap            : 1rem;
  height         : 110px;
  margin-bottom  : 0.25rem;
}

.logo-container img,
[data-testid="stImage"] img {
  object-fit : contain !important;
  width      : auto !important;
}

.stImage img[src*="Rotex"],
.logo-header-img {
  height      : 32px !important;
  width       : auto !important;
  object-fit  : contain !important;
  margin-top  : -25px !important;
  display     : block !important;
  margin-left : auto !important;
  margin-right: auto !important;
}

.logo-footer-img {
  height  : 98px !important;
  display : block !important;
  margin  : 0 auto !important;
}
</style>

<!-- Dot-grid texture layer -->
<div class="stv-wave"></div>
"""

# Inject CSS
st.markdown(theme_css_light, unsafe_allow_html=True)

# --- Header with only Rotex logo centered ---
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.markdown('<div class="logo-container">', unsafe_allow_html=True)
    st.image("Rotex.png", use_container_width=False)
    st.markdown('</div>', unsafe_allow_html=True)
    # Add CSS to control Rotex sizing (smaller & lifted)
    st.markdown('<style>.stImage img[src*="Rotex"]{height:32px !important; width:auto !important; object-fit:contain !important; margin-top:-25px !important; display:block !important; margin-left:auto !important; margin-right:auto !important;}</style>', unsafe_allow_html=True)

st.title("📊 Trade Analyzer & 🌐 IP Lookup Tool")
st.markdown("---")

# --- Trade Analysis Section ---
st.header("📈 Trade Analysis")

st.markdown(
    "**Upload one or more MT5 Excel reports.** "
    "A single file shows the full detailed analysis; multiple files render a side-by-side comparison."
)
uploaded_files = st.file_uploader(
    "Upload Excel Trade Report(s) — select one or many",
    type=["xlsx"],
    key="trade_file",
    accept_multiple_files=True,
)

# --- Scalping threshold selector ---
st.markdown("**Scalping threshold** — choose how many seconds qualify as a scalp:")
scalping_choice = st.selectbox(
    "Scalping threshold (seconds)",
    options=[60, 120, 180],
    index=2,
    help="Trades with hold time less than or equal to this will be classified as scalping."
)

if uploaded_files and len(uploaded_files) > 1:
    # ── BULK COMPARISON MODE ───────────────────────────────────────────────
    _render_bulk_view(uploaded_files, scalping_choice)

elif uploaded_files:
    # ── SINGLE-FILE DETAILED MODE (existing flow) ──────────────────────────
    uploaded_file = uploaded_files[0]
    with st.spinner("Analyzing trades..."):
        result = analyze_trades(uploaded_file, scalping_threshold_seconds=scalping_choice)

    if result:
        # --- Extract Account Number from Filename ---
        filename = uploaded_file.name
        acc_match = re.search(r"ReportHistory[-_ ]?(\d+)", filename)
        account_no = acc_match.group(1) if acc_match else "Unknown"

        toxic_percentage = result["toxic_percentage"]
        pattern_notes = []
        if result["scalping_percentage"] > 30:
            pattern_notes.append("Scalping")
        if result["reversal_count"] > 0 and result["reversal_percentage"] > 0:
            pattern_notes.append("Hedging/Reversal")
        if result["burst_count"] > 5:
            pattern_notes.append("Burst/High-Frequency")
        trading_pattern = ", ".join(pattern_notes) if pattern_notes else "Normal Trading Flow"

        def fmt_td(td):
            if pd.isna(td):
                return "N/A"
            total_s = int(td.total_seconds())
            h, rem = divmod(abs(total_s), 3600)
            m, s = divmod(rem, 60)
            return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

        # ── TABS ──────────────────────────────────────────────────────────────
        tab1, tab2, tab4, tab5, tab6 = st.tabs([
            "📊 Overview",
            "⚙️ Decision Engine",
            "📉 Session & Drawdown",
            "📁 Charts & Tables",
            "🚩 Flagged Trades",
        ])

        # ── TAB 1: OVERVIEW ───────────────────────────────────────────────────
        with tab1:
            st.subheader("📊 Overview")

            r1 = st.columns(4)
            r1[0].metric("Net Profit", f"${result['total_profit']:.2f}")
            r1[1].metric("Win Rate %", f"{result['win_rate']:.2f}")
            r1[2].metric("Profit Factor", f"{result['profit_factor']:.2f}")
            r1[3].metric("Flagged Trade %", f"{toxic_percentage:.2f}")

            r2 = st.columns(4)
            r2[0].metric("Average Win", f"${result['avg_win']:.2f}")
            r2[1].metric("Average Loss", f"${result['avg_loss']:.2f}")
            r2[2].metric("Max Win", f"${result['max_win']:.2f}")
            r2[3].metric("Max Loss", f"${result['max_loss']:.2f}")

            r3 = st.columns(4)
            r3[0].metric("Avg Winner Hold", fmt_td(result['avg_winner_hold']))
            r3[1].metric("Avg Loser Hold", fmt_td(result['avg_loser_hold']))
            r3[2].metric("Median Hold", fmt_td(result['median_hold']))
            r3[3].metric("Avg Hold Time", fmt_td(result['avg_hold_time']))

            r4 = st.columns(4)
            r4[0].metric("Worst Day", f"${result['worst_day']:.2f}")
            r4[1].metric("Best Day", f"${result['best_day']:.2f}")
            r4[2].metric("Max Drawdown", f"${result['max_drawdown']:.2f}")
            r4[3].metric("Worst Loss Streak", result['worst_loss_streak'])

            r5 = st.columns(4)
            r5[0].metric("Symbol Concentration %", f"{result['symbol_concentration']:.2f}")
            r5[1].metric("Buy Trades", result['buy_count'])
            r5[2].metric("Sell Trades", result['sell_count'])
            r5[3].metric("Total Volume", f"{result['total_volume']:.2f}")

            r6 = st.columns(2)
            r6[0].metric("Buy Net P&L", f"${result['buy_net']:.2f}")
            r6[1].metric("Sell Net P&L", f"${result['sell_net']:.2f}")

            st.markdown("---")
            st.markdown("#### 🎯 P&L Concentration (Pareto, ≥70%)")
            r7 = st.columns(4)
            r7[0].metric(
                "Top Profit Contributors",
                result['top_profit_count'],
                delta=f"{result['top_profit_pct_of_gross']:.1f}% of gross profit",
                delta_color="off",
                help="Smallest set of winning trades whose combined profit reaches 70% of gross profit. Fewer = more concentrated/fragile."
            )
            r7[1].metric(
                "% of Total Trades",
                f"{result['top_profit_pct_of_count']:.2f}%",
                help="What share of all trades these top profit contributors represent."
            )
            r7[2].metric(
                "Top Loss Contributors",
                result['top_loss_count'],
                delta=f"{result['top_loss_pct_of_gross']:.1f}% of gross loss",
                delta_color="off",
                help="Smallest set of losing trades whose combined loss reaches 70% of gross loss."
            )
            r7[3].metric(
                "% of Total Trades",
                f"{result['top_loss_pct_of_count']:.2f}%",
                help="What share of all trades these top loss contributors represent."
            )

            tc_cols = st.columns(2)
            with tc_cols[0]:
                st.markdown("**Top Profit Contributors (≥70% of gross profit)**")
                if not result['top_profit_contributors_df'].empty:
                    show = ['Symbol', 'Type', 'Open Time', 'Profit', 'Pct_of_Gross_Profit', 'Cumulative_Pct']
                    show = [c for c in show if c in result['top_profit_contributors_df'].columns]
                    st.dataframe(result['top_profit_contributors_df'][show], use_container_width=True, height=240)
                else:
                    st.caption("No profitable trades.")
            with tc_cols[1]:
                st.markdown("**Top Loss Contributors (≥70% of gross loss)**")
                if not result['top_loss_contributors_df'].empty:
                    show = ['Symbol', 'Type', 'Open Time', 'Profit', 'Pct_of_Gross_Loss', 'Cumulative_Pct']
                    show = [c for c in show if c in result['top_loss_contributors_df'].columns]
                    st.dataframe(result['top_loss_contributors_df'][show], use_container_width=True, height=240)
                else:
                    st.caption("No losing trades.")

        # ── TAB 2: DECISION ENGINE ────────────────────────────────────────────
        with tab2:
            st.subheader("⚙️ Decision Engine")

            dealer = result['dealer_decision']
            flow = result['flow_classification']
            dealer_color = "#ef4444" if "B-Book" in dealer else ("#10b981" if "A-Book" in dealer else "#f59e0b")

            st.markdown(
                f"<div style='padding:16px;border-radius:10px;background:rgba(233,238,251,0.7);border-left:6px solid {dealer_color};margin-bottom:12px'>"
                f"<span style='font-size:1.1rem;font-weight:600;color:{dealer_color}'>Dealer Decision: {dealer}</span><br>"
                f"<span style='color:#333'>Flow Classification: <b>{flow}</b></span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            dc = st.columns(3)
            dc[0].metric("Expectancy / Trade", f"${result['expectancy']:.2f}")
            dc[1].metric("Profit Factor", f"{result['profit_factor']:.2f}", help="< 1 = losing | > 1.3 = acceptable | > 1.5 = strong")
            dc[2].metric("Martingale Score %", f"{result['martingale_score']:.1f}")

            st.markdown("#### Risk Flags")
            flags = []
            if result['symbol_concentration'] > 80:
                flags.append(f"⚠️ High symbol concentration — {result['symbol_concentration']:.1f}% trades on **{result['top_symbol']}**")
            if result['max_drawdown'] < -10000:
                flags.append(f"🔴 Severe drawdown: **${result['max_drawdown']:.2f}**")
            elif result['max_drawdown'] < -3000:
                flags.append(f"🟡 Elevated drawdown: **${result['max_drawdown']:.2f}**")
            if result['profit_factor'] < 1.0:
                flags.append("🔴 Profit Factor below 1.0 — net losing strategy")
            if result['martingale_score'] > 30:
                flags.append(f"⚠️ Martingale/averaging pattern detected ({result['martingale_score']:.1f}%)")
            if result['avg_loss'] != 0 and abs(result['avg_loss']) > result['avg_win'] * 3:
                flags.append(f"⚠️ Loss asymmetry: avg loss is {abs(result['avg_loss']) / result['avg_win']:.1f}× the avg win")
            if toxic_percentage > 50:
                flags.append(f"🔴 High flagged trade rate: {toxic_percentage:.1f}%")
            if not flags:
                flags.append("✅ No critical risk flags detected")
            for f in flags:
                st.markdown(f)

        # ── TAB 4: SESSION & DRAWDOWN ─────────────────────────────────────────
        with tab4:
            st.subheader("📉 Equity Curve")
            eq_df = result['eq_df']
            equity_curve = result['equity_curve']
            drawdown_series = result['drawdown_series']

            fig_eq = px.line(
                x=eq_df['Close Time'], y=equity_curve,
                labels={'x': 'Date', 'y': 'Cumulative P&L'},
                title='Equity Curve'
            )
            fig_eq.update_traces(line_color='#3b82f6')
            fig_eq.update_layout(height=300, margin=dict(t=40, b=20, l=0, r=0))
            st.plotly_chart(fig_eq, use_container_width=True)

            st.subheader("📉 Drawdown")
            fig_dd = px.area(
                x=eq_df['Close Time'], y=drawdown_series,
                title='Drawdown from Peak',
                color_discrete_sequence=['#ef4444']
            )
            fig_dd.update_layout(height=250, margin=dict(t=40, b=20, l=0, r=0))
            st.plotly_chart(fig_dd, use_container_width=True)

            st.subheader("⏰ P&L by Hour of Day")
            hourly = result['hourly'].reset_index()
            fig_hr = px.bar(
                hourly, x='Hour', y='sum',
                title='Net P&L by Hour',
                labels={'sum': 'Net P&L', 'Hour': 'Hour (broker time)'},
                color='sum',
                color_continuous_scale=['#ef4444', '#e9eefb', '#3b82f6']
            )
            fig_hr.update_layout(height=280, margin=dict(t=40, b=20, l=0, r=0), coloraxis_showscale=False)
            st.plotly_chart(fig_hr, use_container_width=True)

            st.subheader("📅 Day-of-Week Performance")
            dow = result['daily_dow'].reset_index()
            dow.columns = ['Day', 'Net P&L', 'Trades', 'Avg P&L']
            st.dataframe(dow.style.format({'Net P&L': '${:.2f}', 'Avg P&L': '${:.2f}'}), use_container_width=True)

        # ── TAB 5: CHARTS & TABLES ────────────────────────────────────────────
        with tab5:
            # ── Overview download ──────────────────────────────────────────────
            st.subheader("📋 Overview — All Trades")
            display_cols = ['Symbol', 'Type', 'Open Time', 'Close Time', 'Volume', 'Profit', 'Hold_Time']
            show_cols = [c for c in display_cols if c in result['all_positions_df'].columns]
            st.dataframe(result['all_positions_df'][show_cols], use_container_width=True, height=400)
            ov_dc = st.columns(2)
            with ov_dc[0]:
                st.download_button("📥 Overview CSV", result['all_positions_df'][show_cols].to_csv(index=False).encode(), f"overview_{account_no}.csv", "text/csv", key="ov_csv")
            with ov_dc[1]:
                rich_buf = _build_overview_excel(result, account_no)
                st.download_button(
                    "📊 Overview Excel — Multi-sheet w/ proof",
                    rich_buf,
                    file_name=f"overview_{account_no}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="ov_xl",
                    help="Includes flagged All-Trades sheet (Is_Scalping/Reversal/Burst/Max_Win/Max_Loss/Top_Contributor) + per-category sheets + concentration analysis."
                )

            st.markdown("---")
            st.subheader("⚡ Scalping Statistics")
            scalp_cols = st.columns(4)
            scalp_cols[0].metric("Scalping Trades", result["scalping_count"], delta=f"{result['scalping_percentage']:.1f}% of total")
            scalp_cols[1].metric("Scalping Profit", f"${result['scalping_profit']:.2f}", delta=f"{result['scalping_profit_percentage']:.1f}% of profit")
            scalp_cols[2].metric("Scalping Win Rate", f"{(result['scalping_df']['Profit'] > 0).sum() / len(result['scalping_df']) * 100:.1f}%" if len(result['scalping_df']) > 0 else "N/A")
            scalp_cols[3].metric("Avg Scalp Time", fmt_td(result['avg_scalping_hold_time']) if result["scalping_count"] > 0 else "N/A")
            if result["scalping_count"] > 0:
                dc = st.columns(2)
                with dc[0]:
                    st.download_button("📥 Scalping CSV", result["scalping_df"].to_csv(index=False).encode(), f"scalping_trades_{account_no}.csv", "text/csv", key="scalp_csv")
                with dc[1]:
                    buf = BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        result["scalping_df"].to_excel(w, index=False, sheet_name='Scalping')
                    buf.seek(0)
                    st.download_button("📊 Scalping Excel", buf, f"scalping_trades_{account_no}.xlsx", key="scalp_xl")

            st.markdown("---")
            st.subheader("🔁 Reversal Trade Statistics")
            rev_cols = st.columns(4)
            rev_cols[0].metric("Reversal Trades", result["reversal_count"], delta=f"{result['reversal_percentage']:.1f}% of total")
            rev_cols[1].metric("Reversal Profit", f"${result['reversal_profit']:.2f}", delta=f"{result['reversal_profit_percentage']:.1f}% of profit")
            rev_cols[2].metric("Reversal Win Rate", f"{(result['reversal_df']['Profit'] > 0).sum() / len(result['reversal_df']) * 100:.1f}%" if len(result['reversal_df']) > 0 else "N/A")
            rev_cols[3].metric("Avg Reversal Profit", f"${result['reversal_df']['Profit'].mean():.2f}" if len(result['reversal_df']) > 0 else "N/A")
            if result["reversal_count"] > 0:
                dc = st.columns(2)
                with dc[0]:
                    st.download_button("📥 Reversal CSV", result["reversal_df"].to_csv(index=False).encode(), f"reversal_trades_{account_no}.csv", "text/csv", key="rev_csv")
                with dc[1]:
                    buf = BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        result["reversal_df"].to_excel(w, index=False, sheet_name='Reversals')
                    buf.seek(0)
                    st.download_button("📊 Reversal Excel", buf, f"reversal_trades_{account_no}.xlsx", key="rev_xl")

            st.markdown("---")
            st.subheader("🚀 Burst Trade Statistics")
            burst_cols = st.columns(4)
            burst_cols[0].metric("Burst Trades", result["burst_count"], delta=f"{result['burst_percentage']:.1f}% of total")
            burst_cols[1].metric("Burst Profit", f"${result['burst_profit']:.2f}", delta=f"{result['burst_profit_percentage']:.1f}% of profit")
            burst_cols[2].metric("Burst Win Rate", f"{(result['burst_df']['Profit'] > 0).sum() / len(result['burst_df']) * 100:.1f}%" if len(result['burst_df']) > 0 else "N/A")
            burst_cols[3].metric("Avg Burst Profit", f"${result['burst_df']['Profit'].mean():.2f}" if len(result['burst_df']) > 0 else "N/A")
            if result["burst_count"] > 0:
                dc = st.columns(2)
                with dc[0]:
                    st.download_button("📥 Burst CSV", result["burst_df"].to_csv(index=False).encode(), f"burst_trades_{account_no}.csv", "text/csv", key="burst_csv")
                with dc[1]:
                    buf = BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        result["burst_df"].to_excel(w, index=False, sheet_name='Bursts')
                    buf.seek(0)
                    st.download_button("📊 Burst Excel", buf, f"burst_trades_{account_no}.xlsx", key="burst_xl")

            st.markdown("---")
            st.subheader("🥧 Trade Type Distribution")
            scalp_n = result["scalping_count"]
            rev_n = result["reversal_count"]
            burst_n = result["burst_count"]
            others_n = result["total_positions"] - (scalp_n + rev_n + burst_n)
            pie_data = pd.DataFrame({
                'Category': ['Scalping', 'Reversal', 'Burst', 'Other'],
                'Count': [scalp_n, rev_n, burst_n, others_n]
            })
            fig_pie = px.pie(
                pie_data, names='Category', values='Count',
                color='Category',
                color_discrete_sequence=['#f59e0b', '#3b82f6', '#8b5cf6', '#10b981']
            )
            fig_pie.update_traces(textinfo='percent+label', textposition='inside', pull=[0.05, 0.05, 0.05, 0])
            fig_pie.update_layout(height=350, margin=dict(t=40, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True)

            st.subheader("📊 Trade P&L Distribution")
            fig_hist = px.histogram(
                result['all_positions_df'], x='Profit', nbins=40,
                title='Trade P&L Distribution',
                color_discrete_sequence=['#3b82f6']
            )
            fig_hist.update_layout(height=280, margin=dict(t=40, b=20, l=0, r=0))
            st.plotly_chart(fig_hist, use_container_width=True)

        # ── TAB 6: FLAGGED TRADES ─────────────────────────────────────────────
        with tab6:
            st.subheader("🚩 Flagged Trades")
            st.caption("Three flagging lenses applied to this account's trade history.")

            flag_t1, flag_t2, flag_t3 = st.tabs([
                "🎯 Top Profit Concentration (≥70%)",
                "⚡ Same-Second Open/Close",
                "💥 Max Win & Max Loss",
            ])

            # ── Flag 1: Top 10% winners ≥70% gross profit ─────────────────────
            with flag_t1:
                st.markdown(
                    "**Definition:** Take the **top 10% of winning trades** (ranked by profit). "
                    "If their combined profit reaches **≥70% of gross profit**, this flag is "
                    "triggered — the equity curve is concentration-driven and fragile."
                )
                all_df = result['all_positions_df']
                winners = all_df[all_df['Profit'] > 0].copy()
                gross_profit_sum = float(winners['Profit'].sum()) if not winners.empty else 0.0

                if winners.empty or gross_profit_sum <= 0:
                    st.caption("No profitable trades to evaluate.")
                else:
                    winners_sorted = winners.sort_values('Profit', ascending=False).reset_index(drop=True)
                    top_n = max(1, math.ceil(len(winners_sorted) * 0.10))
                    top10 = winners_sorted.iloc[:top_n].copy()
                    combined_profit = float(top10['Profit'].sum())
                    pct_of_gross = (combined_profit / gross_profit_sum * 100) if gross_profit_sum > 0 else 0.0
                    pct_of_total_trades = (top_n / len(all_df) * 100) if len(all_df) > 0 else 0.0
                    triggered = pct_of_gross >= 70.0

                    top10['Pct_of_Gross_Profit'] = (top10['Profit'] / gross_profit_sum * 100).round(2)
                    top10['Cumulative_Pct'] = (top10['Profit'].cumsum() / gross_profit_sum * 100).round(2)

                    banner_color = "#ef4444" if triggered else "#10b981"
                    banner_text = (
                        "🚩 FLAG TRIGGERED — top 10% of winners drive ≥70% of gross profit (concentration risk)"
                        if triggered else
                        "✅ Flag not triggered — gross profit is more evenly distributed across winners"
                    )
                    st.markdown(
                        f"<div style='padding:12px;border-radius:8px;background:rgba(233,238,251,0.6);"
                        f"border-left:6px solid {banner_color};margin:8px 0 14px 0;"
                        f"color:{banner_color};font-weight:600'>{banner_text}</div>",
                        unsafe_allow_html=True,
                    )

                    m = st.columns(4)
                    m[0].metric("Top 10% Winners", top_n, delta=f"of {len(winners_sorted)} winning trades", delta_color="off")
                    m[1].metric("% of Total Trades", f"{pct_of_total_trades:.2f}%")
                    m[2].metric("Combined Profit", f"${combined_profit:.2f}")
                    m[3].metric("% of Gross Profit", f"{pct_of_gross:.1f}%", delta="≥ 70% threshold" if triggered else "below threshold", delta_color="inverse" if triggered else "off")

                    show_cols = [c for c in [
                        'Symbol', 'Type', 'Open Time', 'Close Time', 'Volume',
                        'Profit', 'Pct_of_Gross_Profit', 'Cumulative_Pct'
                    ] if c in top10.columns]
                    st.dataframe(top10[show_cols], use_container_width=True, height=380)

                    dl = st.columns(2)
                    with dl[0]:
                        st.download_button(
                            "📥 Top 10% Winners CSV",
                            top10[show_cols].to_csv(index=False).encode(),
                            f"top10pct_winners_{account_no}.csv",
                            "text/csv",
                            key="flag_top10_csv",
                        )
                    with dl[1]:
                        buf = BytesIO()
                        with pd.ExcelWriter(buf, engine='openpyxl') as w:
                            top10[show_cols].to_excel(w, index=False, sheet_name='Top10pctWinners')
                        buf.seek(0)
                        st.download_button(
                            "📊 Top 10% Winners Excel",
                            buf,
                            f"top10pct_winners_{account_no}.xlsx",
                            key="flag_top10_xl",
                        )

            # ── Flag 2: Same-second open/close ────────────────────────────────
            with flag_t2:
                st.markdown(
                    "**Definition:** Trades where the open and close timestamps land in the "
                    "**same second** (hold time ≤ 1s). The tightest possible HFT/latency-style "
                    "behavior — typically tighter than scalping."
                )
                all_df = result['all_positions_df']
                if 'Hold_Time' in all_df.columns:
                    hold_sec = all_df['Hold_Time'].dt.total_seconds()
                else:
                    hold_sec = (all_df['Close Time'] - all_df['Open Time']).dt.total_seconds()
                same_sec_mask = hold_sec.abs() <= 1
                same_sec_df = all_df[same_sec_mask].copy()

                if same_sec_df.empty:
                    st.caption("No same-second open/close trades found.")
                else:
                    total_trades = len(all_df)
                    total_profit = float(same_sec_df['Profit'].sum())
                    wins = int((same_sec_df['Profit'] > 0).sum())
                    win_rate = (wins / len(same_sec_df) * 100) if len(same_sec_df) else 0.0
                    pct_of_total = (len(same_sec_df) / total_trades * 100) if total_trades else 0.0

                    m = st.columns(4)
                    m[0].metric("Flagged Trades", len(same_sec_df), delta=f"{pct_of_total:.1f}% of total", delta_color="off")
                    m[1].metric("Total P&L", f"${total_profit:.2f}")
                    m[2].metric("Win Rate", f"{win_rate:.1f}%")
                    m[3].metric("Avg P&L", f"${same_sec_df['Profit'].mean():.2f}")

                    show_cols = [c for c in [
                        'Symbol', 'Type', 'Open Time', 'Close Time', 'Volume', 'Profit', 'Hold_Time'
                    ] if c in same_sec_df.columns]
                    st.dataframe(same_sec_df[show_cols], use_container_width=True, height=380)

                    dl = st.columns(2)
                    with dl[0]:
                        st.download_button(
                            "📥 Same-Second CSV",
                            same_sec_df[show_cols].to_csv(index=False).encode(),
                            f"same_second_trades_{account_no}.csv",
                            "text/csv",
                            key="flag_samesec_csv",
                        )
                    with dl[1]:
                        buf = BytesIO()
                        with pd.ExcelWriter(buf, engine='openpyxl') as w:
                            same_sec_df[show_cols].to_excel(w, index=False, sheet_name='SameSecond')
                        buf.seek(0)
                        st.download_button(
                            "📊 Same-Second Excel",
                            buf,
                            f"same_second_trades_{account_no}.xlsx",
                            key="flag_samesec_xl",
                        )

            # ── Flag 3: Max win & max loss trade ──────────────────────────────
            with flag_t3:
                st.markdown(
                    "**Definition:** The single largest winning trade and the single largest "
                    "losing trade for this account."
                )
                all_df = result['all_positions_df']
                if all_df.empty or 'Profit' not in all_df.columns:
                    st.caption("No trades available.")
                else:
                    max_idx = all_df['Profit'].idxmax()
                    min_idx = all_df['Profit'].idxmin()
                    max_row = all_df.loc[max_idx]
                    min_row = all_df.loc[min_idx]

                    def _fmt_row(row, kind: str, color: str):
                        symbol = row.get('Symbol', 'N/A')
                        ttype = row.get('Type', 'N/A')
                        ot = row.get('Open Time', 'N/A')
                        ct = row.get('Close Time', 'N/A')
                        vol = row.get('Volume', 'N/A')
                        prof = float(row.get('Profit', 0.0))
                        hold = row.get('Hold_Time', None)
                        hold_str = fmt_td(hold) if hold is not None else "N/A"
                        return (
                            f"<div style='padding:14px;border-radius:10px;background:rgba(233,238,251,0.6);"
                            f"border-left:6px solid {color};margin-bottom:8px'>"
                            f"<div style='font-size:1.05rem;font-weight:700;color:{color};margin-bottom:6px'>{kind}: ${prof:,.2f}</div>"
                            f"<div><b>Symbol:</b> {symbol} &nbsp;·&nbsp; <b>Type:</b> {ttype}</div>"
                            f"<div><b>Volume:</b> {vol} &nbsp;·&nbsp; <b>Hold Time:</b> {hold_str}</div>"
                            f"<div><b>Open:</b> {ot}</div>"
                            f"<div><b>Close:</b> {ct}</div>"
                            f"</div>"
                        )

                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown(_fmt_row(max_row, "💚 Highest Profit Trade", "#10b981"), unsafe_allow_html=True)
                    with cols[1]:
                        st.markdown(_fmt_row(min_row, "❤️ Highest Loss Trade", "#ef4444"), unsafe_allow_html=True)

                    st.markdown("---")
                    extremes_df = pd.DataFrame([max_row, min_row])
                    extremes_df.insert(0, 'Flag', ['Max Win', 'Max Loss'])
                    show_cols = ['Flag'] + [c for c in [
                        'Symbol', 'Type', 'Open Time', 'Close Time', 'Volume', 'Profit', 'Hold_Time'
                    ] if c in extremes_df.columns]
                    st.dataframe(extremes_df[show_cols], use_container_width=True)

                    dl = st.columns(2)
                    with dl[0]:
                        st.download_button(
                            "📥 Max Win/Loss CSV",
                            extremes_df[show_cols].to_csv(index=False).encode(),
                            f"max_win_loss_{account_no}.csv",
                            "text/csv",
                            key="flag_extremes_csv",
                        )
                    with dl[1]:
                        buf = BytesIO()
                        with pd.ExcelWriter(buf, engine='openpyxl') as w:
                            extremes_df[show_cols].to_excel(w, index=False, sheet_name='MaxWinLoss')
                        buf.seek(0)
                        st.download_button(
                            "📊 Max Win/Loss Excel",
                            buf,
                            f"max_win_loss_{account_no}.xlsx",
                            key="flag_extremes_xl",
                        )

        # ── CLIENT REPORT (outside tabs) ──────────────────────────────────────
        st.markdown("---")
        st.subheader("📄 Client Report")
        ip_country = "N/A"
        if st.session_state.ip_history:
            last_details = st.session_state.ip_history[0]["details"]
            if "error" not in last_details:
                ip_country = last_details.get("country", "N/A")
        _render_copy_button(
            _build_client_report(account_no, result, scalping_choice, ip_country),
            f"single_{account_no}"
        )

else:
    st.info("👆 Upload one or more Excel files to analyze your trades")

st.markdown("---")

# --- 🌐 IP Lookup Section (Modern Card Layout with Embedded Map) ---
st.header("🌐 IP Address Lookup")

st.markdown("""
Enter *one or more IP addresses* below — separated by commas or new lines.
You'll instantly get their location, ISP, and a small map — all inside elegant cards.
""")

with st.container():
    ip_input = st.text_area(
        "Enter IP Addresses",
        placeholder="e.g., 8.8.8.8, 1.1.1.1 or each on a new line",
        height=100,
        key="ip_input_field"
    )

    lookup_col1, lookup_col2 = st.columns([4, 1])
    with lookup_col2:
        lookup_btn = st.button("🔍 Lookup IPs", use_container_width=True)
    with lookup_col1:
        st.caption("You can check multiple IPs at once.")

if lookup_btn and ip_input.strip():
    ip_list = [ip.strip() for ip in ip_input.replace("\n", ",").split(",") if ip.strip()]
    st.info(f"Looking up {len(ip_list)} IP address(es)...")

    for ip in ip_list:
        with st.spinner(f"Looking up {ip}..."):
            details = get_ip_details(ip)
            add_ip_to_history(ip, details)

# --- Display Lookup Results as Cards ---
if st.session_state.ip_history:
    st.subheader("📜 Recent IP Lookups")

    cards_per_row = 3
    ip_entries = st.session_state.ip_history

    for row_start in range(0, len(ip_entries), cards_per_row):
        cols = st.columns(cards_per_row)
        for i, entry in enumerate(ip_entries[row_start:row_start + cards_per_row]):
            details = entry["details"]
            with cols[i]:
                if "error" in details:
                    st.error(f"❌ {entry['ip']}\n\n{details['error']}")
                    continue

                city = details.get("city", "N/A")
                region = details.get("region", "N/A")
                country = details.get("country", "N/A")
                org = details.get("org", "N/A")
                loc = details.get("loc", None)
                timezone = details.get("timezone", "N/A")

                # Card container - Light Mode Styling
                st.markdown(
                    f"""
                    <div class="ip-card">
                        <h4 style="margin-bottom: 6px; color: #000000 !important;">🌐 {entry['ip']}</h4>
                        <p style="font-size: 0.9rem; color: #333333 !important;">{city}, {region}, {country}</p>
                        <hr style="margin: 0.5rem 0; border-color: rgba(0,191,255,0.2);">
                        <p style="font-size: 0.85rem; color: #000000 !important;">
                            <b>ISP:</b> {org}<br>
                            <b>Timezone:</b> {timezone}<br>
                            <b>Location:</b> {loc if loc else 'N/A'}
                        </p>
                        <p style="font-size: 0.75rem; color: #666666 !important; margin-top: 0.5rem;">⏱ {entry['timestamp']}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Add small embedded map
                if loc:
                    lat, lon = map(float, loc.split(","))
                    st.map(
                        pd.DataFrame({"lat": [lat], "lon": [lon]}),
                        use_container_width=True,
                        height=180,
                    )

    st.markdown("---")
    clear_col = st.columns([1, 6, 1])[1]
    with clear_col:
        if st.button("🗑 Clear History", use_container_width=True):
            st.session_state.ip_history = []
            st.rerun()
else:
    st.info("👆 Enter one or more IP addresses to get started")

# --- Footer with only Eagle Eye centered ---
st.markdown("---")
fcol1, fcol2, fcol3 = st.columns([1, 2, 1])
with fcol2:
    st.markdown('<div class="logo-container">', unsafe_allow_html=True)
    st.image("Eagleeye.png", use_container_width=False)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<style>.stImage img[src*="Eagleeye"]{height:98px !important; width:auto !important; object-fit:contain !important; display:block; margin:0 auto !important;}</style>', unsafe_allow_html=True)
st.markdown("Built with ❤ using Streamlit • For efficient trade analysis and quick IP insights")

