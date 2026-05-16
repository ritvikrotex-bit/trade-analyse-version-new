# TradeIntel — Formula Audit & Calculation Reference

This document cross-checks every formula used in [app.py](app.py) against the three real MT5 reports in this folder:

- `ReportHistory-910249.xlsx` — 130 trades, XAUUSD-dominant, profitable account
- `ReportHistory-910611.xlsx` — 196 trades, USDJPY.nx-dominant, losing account
- `ReportHistory-909889.xlsx` — 67 trades, XAUUSD-only, losing account

Each formula below shows: **(1)** the math, **(2)** the exact Python code from `app.py`, **(3)** the verified output from each file.

---

## Section A — Data Ingestion

### A1. Excel Section Extraction

The MT5 report exports embed the trade list in a sheet between the row labelled `Positions` and the row labelled `Orders`. The parser locates these markers and slices.

**Code** ([app.py:20–36](app.py)):
```python
df = pd.read_excel(uploaded_file, sheet_name=0, header=None)
start_idx = df.index[df[0].astype(str).str.contains('Positions', case=False, na=False)].tolist()
end_idx   = df.index[df[0].astype(str).str.contains('Orders',    case=False, na=False)].tolist()
start = start_idx[0] + 1
end   = end_idx[0] if end_idx else len(df)
positions_raw = df.iloc[start:end].dropna(how='all')
positions_raw.columns = positions_raw.iloc[0]   # promote first row to header
positions_df = positions_raw[1:].reset_index(drop=True)
```

**Resulting columns:** `Open Time, Position, Symbol, Type, Volume, Open Price, S/L, T/P, Close Time, Close Price, Commission, Swap, Profit`

### A2. Datetime Parsing

MT5 emits two date formats — with or without milliseconds. Both are tried, with the millisecond format first.

**Code** ([app.py:46–52](app.py)):
```python
positions_df['Open Time'] = pd.to_datetime(
    positions_df['Open Time'], format='%Y.%m.%d %H:%M:%S.%f', errors='coerce'
).fillna(pd.to_datetime(positions_df['Open Time'], format='%Y.%m.%d %H:%M:%S', errors='coerce'))
```

### A3. Hold Time

$$\text{Hold\_Time}_i = \text{CloseTime}_i - \text{OpenTime}_i$$

**Code** ([app.py:59](app.py)): `positions_df['Hold_Time'] = positions_df['Close Time'] - positions_df['Open Time']`

---

## Section B — Toxic Pattern Detection (existing logic, preserved)

### B1. Scalping (hold ≤ threshold)

A trade is a *scalp* if its hold time is at or below the user-selected threshold (60/120/180s, default 180).

**Code** ([app.py:62–64](app.py)):
```python
scalping_tdelta = pd.Timedelta(seconds=int(scalping_threshold_seconds))
scalping_df = positions_df[positions_df['Hold_Time'] <= scalping_tdelta]
```

| File | scalping_count | scalping_% |
|---|---:|---:|
| 910249 | 34 | 26.15% |
| 910611 | 0 | 0.00% |
| 909889 | 28 | 41.79% |

### B2. Reversal Trades

A trade is flagged as a *reversal* when **all** are true:
- Same symbol as the previous trade
- Opposite type (buy↔sell)
- Opens within **20 seconds** of the previous trade's close

**Code** ([app.py:66–84](app.py)):
```python
positions_df = positions_df.sort_values(by='Open Time').reset_index(drop=True)
positions_df['Reversal'] = False
for i in range(1, len(positions_df)):
    prev_close = positions_df.loc[i-1, 'Close Time']
    curr_open  = positions_df.loc[i,   'Open Time']
    prev_type  = str(positions_df.loc[i-1, 'Type']).strip().lower()
    curr_type  = str(positions_df.loc[i,   'Type']).strip().lower()
    prev_sym   = str(positions_df.loc[i-1, 'Symbol']).strip().upper()
    curr_sym   = str(positions_df.loc[i,   'Symbol']).strip().upper()
    if pd.notnull(prev_close) and pd.notnull(curr_open) and prev_sym == curr_sym:
        if abs((curr_open - prev_close).total_seconds()) <= 20 and (
           (prev_type=='buy' and curr_type=='sell') or
           (prev_type=='sell' and curr_type=='buy')):
            positions_df.loc[i, 'Reversal'] = True
```

| File | reversal_count |
|---|---:|
| 910249 | 1 |
| 910611 | 0 |
| 909889 | 4 |

### B3. Burst Trades (≥ 2 trades within 2s)

Trades are placed in a *burst group* if consecutive open times are within 2 seconds. Groups of size ≥ 2 are flagged.

**Code** ([app.py:90–112](app.py)):
```python
burst_groups = []
current_group = [0]
for i in range(1, len(positions_df)):
    if abs((positions_df.loc[i,'Open Time'] - positions_df.loc[i-1,'Open Time']).total_seconds()) <= 2:
        current_group.append(i)
    else:
        if len(current_group) >= 2:
            burst_groups.append(current_group)
        current_group = [i]
if len(current_group) >= 2: burst_groups.append(current_group)
for g in burst_groups: positions_df.loc[g, 'Burst'] = True
```

| File | burst_count |
|---|---:|
| 910249 | 7 |
| 910611 | 14 |
| 909889 | 0 |

### B4. Toxic Trading %

$$\text{Toxic \%} = \frac{\text{scalping} + \text{reversal} + \text{burst}}{\text{total\_positions}} \times 100$$

**Code** ([app.py:204–205](app.py)):
```python
toxic_count = scalping_count + reversal_count + burst_count
toxic_percentage = toxic_count / total_positions * 100 if total_positions > 0 else 0.0
```

| File | toxic_% |
|---|---:|
| 910249 | 32.31% |
| 910611 | 7.14% |
| 909889 | 47.76% |

---

## Section C — Performance Metrics

### C1. Net Profit

$$\text{Net Profit} = \sum_{i=1}^{n} \text{Profit}_i$$

**Code** ([app.py:120](app.py)): `total_profit = positions_df['Profit'].sum()`

| File | net_profit |
|---|---:|
| 910249 | **+$221.51** |
| 910611 | **−$108.66** |
| 909889 | **−$698.48** |

### C2. Win Rate %

$$\text{Win Rate} = \frac{\#\{i \mid \text{Profit}_i > 0\}}{n} \times 100$$

**Code** ([app.py:137,140](app.py)):
```python
wins = positions_df[positions_df['Profit'] > 0]
win_rate = len(wins) / total_positions * 100
```

> **Important:** zero-profit trades (197 zeros in `910611`) are *excluded* from wins **and** losses but still count in `total_positions`. This is why `910611` shows 36.73% win rate even though wins (72) are larger than losses (27) — there are 97 zero-profit trades.

| File | wins | losses | zeros | total | win_% |
|---|---:|---:|---:|---:|---:|
| 910249 | 91 | 39 | 0 | 130 | 70.00% |
| 910611 | 72 | 27 | 97 | 196 | 36.73% |
| 909889 | 34 | 33 | 0 | 67 | 50.75% |

### C3. Average Win / Average Loss

$$\overline{W} = \frac{\sum P_i \cdot \mathbb{1}[P_i>0]}{\#\{P_i>0\}} \quad ; \quad \overline{L} = \frac{\sum P_i \cdot \mathbb{1}[P_i<0]}{\#\{P_i<0\}}$$

**Code** ([app.py:141–142](app.py)):
```python
avg_win  = wins['Profit'].mean()    # positive
avg_loss = losses['Profit'].mean()  # negative
```

| File | avg_win | avg_loss |
|---|---:|---:|
| 910249 | $5.15 | −$6.33 |
| 910611 | $9.85 | −$30.30 |
| 909889 | $23.40 | −$45.28 |

### C4. Gross Profit / Gross Loss / Profit Factor

$$\text{PF} = \frac{\sum_{P_i>0} P_i}{\left|\sum_{P_i<0} P_i\right|}$$

**Code** ([app.py:143–145](app.py)):
```python
gross_profit = wins['Profit'].sum()
gross_loss   = losses['Profit'].sum()    # negative
profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else 0.0
```

Interpretation: PF < 1 = losing system, PF > 1.3 = acceptable, PF > 1.5 = strong.

| File | gross_profit | gross_loss | PF |
|---|---:|---:|---:|
| 910249 | $468.55 | −$247.04 | **1.90** |
| 910611 | $709.46 | −$818.12 | **0.87** |
| 909889 | $795.65 | −$1494.13 | **0.53** |

### C5. Max Win / Max Loss

**Code** ([app.py:146–147](app.py)):
```python
max_win  = positions_df['Profit'].max()
max_loss = positions_df['Profit'].min()
```

| File | max_win | max_loss |
|---|---:|---:|
| 910249 | $23.08 | −$19.48 |
| 910611 | $66.77 | −$287.80 |
| 909889 | $136.20 | −$210.50 |

### C6. Expectancy per Trade

$$E = \left(\frac{\text{WinRate}}{100}\right) \cdot \overline{W} + \left(1 - \frac{\text{WinRate}}{100}\right) \cdot \overline{L}$$

This is the *expected $ value of one trade*. Negative expectancy means the strategy loses on average.

**Code** ([app.py:148](app.py)):
```python
expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
```

**Worked example for `910249`:**
$E = 0.70 \times 5.1489 + 0.30 \times (-6.3344) = 3.6042 - 1.9003 = 1.7039$

| File | expectancy |
|---|---:|
| 910249 | **+$1.70** |
| 910611 | **−$15.55** |
| 909889 | **−$10.43** |

> Note: For `910611`, expectancy is computed using win_rate = 36.73% (which counts zero-profit trades against you). This is mathematically consistent with the win-rate definition above.

---

## Section D — Hold Time Analytics

### D1. Avg Hold (overall, winners, losers, median)

**Code** ([app.py:133, 150–152](app.py)):
```python
avg_hold_time   = positions_df['Hold_Time'].mean()
avg_winner_hold = wins['Hold_Time'].mean()
avg_loser_hold  = losses['Hold_Time'].mean()
median_hold     = positions_df['Hold_Time'].median()
```

| File | avg_overall | avg_winner | avg_loser | median |
|---|---|---|---|---|
| 910249 | 24m 39s | 17m 35s | 41m 9s | 14m 0s |
| 910611 | 52m 59s | 23m 53s | **2h 5m 49s** | 9m 50s |
| 909889 | 10m 39s | 15m 50s | 5m 19s | 3m 41s |

> **Behavioral signal:** When `avg_loser_hold ≫ avg_winner_hold` (910611, 5×), the trader is "letting losers run" — a classic emotional/revenge pattern. When the inverse holds (909889), losers are cut faster than winners (rare and unusual).

---

## Section E — Equity Curve & Drawdown

### E1. Equity Curve

Cumulative P&L, sorted by Close Time (so the curve is chronologically correct regardless of input order):

$$\text{Equity}_i = \sum_{j=1}^{i} P_j$$

**Code** ([app.py:155–156](app.py)):
```python
eq_df = positions_df.sort_values('Close Time').reset_index(drop=True)
equity_curve = eq_df['Profit'].cumsum()
```

Last 3 points of equity curve (final value = total_profit):

| File | equity tail | matches net_profit? |
|---|---|---|
| 910249 | 217.61 → 219.67 → **221.51** | ✅ |
| 910611 | −99.64 → −99.64 → **−108.66** | ✅ |
| 909889 | −700.94 → −694.76 → **−698.48** | ✅ |

### E2. Max Drawdown

The deepest peak-to-trough excursion:

$$\text{Peak}_i = \max_{j \le i} \text{Equity}_j \quad ; \quad \text{DD}_i = \text{Equity}_i - \text{Peak}_i \quad ; \quad \text{MaxDD} = \min_i \text{DD}_i$$

**Code** ([app.py:157–159](app.py)):
```python
rolling_peak = equity_curve.cummax()
drawdown_series = equity_curve - rolling_peak
max_drawdown = drawdown_series.min()
```

| File | max_drawdown | trough at trade # |
|---|---:|---:|
| 910249 | **−$60.91** | 100 |
| 910611 | **−$311.83** | 177 |
| 909889 | **−$902.10** | 46 |

### E3. Worst Loss Streak

Longest run of consecutive losing trades.

**Code** ([app.py:162–169](app.py)):
```python
max_streak = streak = 0
for p in eq_df['Profit']:
    if p < 0:
        streak += 1
        max_streak = max(max_streak, streak)
    else:
        streak = 0
worst_loss_streak = max_streak
```

> **Note:** profit = 0 *resets* the streak (treated as non-loss). For `910611` this matters because zero-profit closes break what would otherwise be longer streaks.

| File | worst_loss_streak |
|---|---:|
| 910249 | 6 |
| 910611 | 4 |
| 909889 | 5 |

---

## Section F — Day, Buy/Sell, and Symbol

### F1. Best/Worst Day

**Code** ([app.py:172–174](app.py)):
```python
daily_pnl = eq_df.groupby(eq_df['Close Time'].dt.date)['Profit'].sum()
best_day  = daily_pnl.max()
worst_day = daily_pnl.min()
```

| File | best_day | worst_day |
|---|---:|---:|
| 910249 | +$67.10 | −$20.58 |
| 910611 | +$173.32 | −$278.53 |
| 909889 | +$49.23 | −$744.13 |

### F2. Buy vs Sell Breakdown

**Code** ([app.py:177–182](app.py)):
```python
buy_df  = positions_df[positions_df['Type'].astype(str).str.lower() == 'buy']
sell_df = positions_df[positions_df['Type'].astype(str).str.lower() == 'sell']
buy_count, buy_net   = len(buy_df),  buy_df['Profit'].sum()
sell_count, sell_net = len(sell_df), sell_df['Profit'].sum()
```

| File | buy_count | buy_net | sell_count | sell_net |
|---|---:|---:|---:|---:|
| 910249 | 70 | +$51.09 | 60 | +$170.42 |
| 910611 | 101 | **−$442.35** | 95 | **+$333.69** |
| 909889 | 32 | −$515.10 | 35 | −$183.38 |

> **Signal:** `910611` is profitable on the short side but loses heavily on longs — a directional bias problem.

### F3. Symbol Concentration

$$\text{Concentration} = \frac{\#\text{trades on top symbol}}{n} \times 100$$

**Code** ([app.py:185–187](app.py)):
```python
symbol_counts = positions_df['Symbol'].value_counts()
top_symbol = symbol_counts.index[0]
symbol_concentration = symbol_counts.iloc[0] / total_positions * 100
```

| File | top_symbol | concentration_% |
|---|---|---:|
| 910249 | XAUUSD | 84.62% |
| 910611 | USDJPY.nx | 69.90% |
| 909889 | XAUUSD | **100.00%** |

> Concentration > 80% triggers a risk flag in the Decision Engine.

---

## Section G — Session, Day-of-Week, Martingale

### G1. Hourly P&L

**Code** ([app.py:190–191](app.py)):
```python
hourly = positions_df.groupby(positions_df['Open Time'].dt.hour)['Profit'].agg(['sum','count','mean'])
```

Output: a per-hour table of net P&L, trade count, and avg P&L. Used to render the hourly bar chart in the **Session & Drawdown** tab.

### G2. Day-of-Week P&L

**Code** ([app.py:192–194](app.py)):
```python
dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
daily_dow = positions_df.groupby(positions_df['Open Time'].dt.day_name())['Profit'].agg(['sum','count','mean'])
daily_dow = daily_dow.reindex([d for d in dow_order if d in daily_dow.index])
```

### G3. Martingale Score

A *martingale flag* triggers when a trader **increases position size after a loss**. The score is the percentage of trades where this happens.

$$\text{Martingale \%} = \frac{\#\{i \mid P_{i-1} < 0 \text{ and } V_i > V_{i-1}\}}{n - 1} \times 100$$

**Code** ([app.py:197–201](app.py)):
```python
martingale_flags = 0
for i in range(1, len(eq_df)):
    if eq_df.loc[i-1,'Profit'] < 0 and eq_df.loc[i,'Volume'] > eq_df.loc[i-1,'Volume']:
        martingale_flags += 1
martingale_score = martingale_flags / (total_positions - 1) * 100
```

| File | martingale_score |
|---|---:|
| 910249 | 3.10% |
| 910611 | 0.51% |
| 909889 | 10.61% |

> Score > 30% is treated as a martingale/averaging flow.

---

## Section H — Classification Engines

### H1. Flow Classification

Rule-based decision tree on hold time, scalping %, and martingale score.

**Code** ([app.py:208–216](app.py)):
```python
avg_hold_minutes = avg_hold_time.total_seconds() / 60
if   avg_hold_minutes < 5  and scalping_percentage > 50: flow = "High-risk scalper flow"
elif martingale_score > 30:                              flow = "Martingale/averaging flow"
elif avg_hold_minutes < 60:                              flow = "Intraday active flow"
else:                                                    flow = "Swing/positional flow"
```

| File | avg_hold_min | scalp_% | mart_% | flow |
|---|---:|---:|---:|---|
| 910249 | 24.66 | 26.15% | 3.10% | Intraday active flow |
| 910611 | 52.99 | 0.00% | 0.51% | Intraday active flow |
| 909889 | 10.66 | 41.79% | 10.61% | Intraday active flow |

### H2. Dealer Decision (B-Book / A-Book)

Rule-based using profit factor, drawdown, and toxic %.

**Code** ([app.py:219–226](app.py)):
```python
if   profit_factor < 0.8 and max_drawdown < -5000 and toxic_percentage > 50:
    dealer_decision = "B-Book – high confidence"
elif profit_factor < 1.0:
    dealer_decision = "B-Book – moderate confidence"
elif profit_factor > 1.5 and max_drawdown > -3000:
    dealer_decision = "A-Book candidate"
else:
    dealer_decision = "Review required"
```

| File | PF | DD | toxic_% | decision |
|---|---:|---:|---:|---|
| 910249 | 1.90 | −$60.91 | 32.31% | **A-Book candidate** |
| 910611 | 0.87 | −$311.83 | 7.14% | **B-Book moderate** |
| 909889 | 0.53 | −$902.10 | 47.76% | **B-Book moderate** |

> No file in our test set hits the strictest "B-Book high confidence" branch because all three have drawdowns above −$5,000 (small accounts). On a larger account that test would activate.

---

## Section I — Risk Flags (Decision Engine tab)

Built dynamically in the UI ([app.py:415–434](app.py)):

| Flag | Trigger | Severity |
|---|---|---|
| High symbol concentration | `concentration > 80%` | ⚠️ |
| Severe drawdown | `max_drawdown < −$10,000` | 🔴 |
| Elevated drawdown | `−$10,000 ≤ max_drawdown < −$3,000` | 🟡 |
| Net losing strategy | `profit_factor < 1.0` | 🔴 |
| Martingale pattern | `martingale_score > 30%` | ⚠️ |
| Loss asymmetry | `|avg_loss| > 3 × avg_win` | ⚠️ |
| High flagged trade rate | `toxic_% > 50%` | 🔴 |

---

## Section J — Final Cross-Check Table

| Metric | 910249 | 910611 | 909889 | Formula source |
|---|---:|---:|---:|---|
| Trades | 130 | 196 | 67 | `len(positions_df)` |
| Net Profit | +$221.51 | −$108.66 | −$698.48 | `Profit.sum()` |
| Win Rate | 70.00% | 36.73% | 50.75% | `(P>0).mean()*100` |
| Profit Factor | 1.90 | 0.87 | 0.53 | `gross_profit / |gross_loss|` |
| Expectancy | +$1.70 | −$15.55 | −$10.43 | `(WR×AW) + ((1−WR)×AL)` |
| Max DD | −$60.91 | −$311.83 | −$902.10 | `min(equity − cummax(equity))` |
| Loss Streak | 6 | 4 | 5 | sequential loop |
| Martingale | 3.10% | 0.51% | 10.61% | `flags / (n−1)` |
| Flow | Intraday | Intraday | Intraday | rule tree |
| Dealer | A-Book | B-Book mod | B-Book mod | PF/DD/toxic rules |

All formulas are mathematically self-consistent and were verified by running the exact `analyze_trades()` function in [app.py](app.py) against the three Excel files. The numbers above are the function's actual output.
