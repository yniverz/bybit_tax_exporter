from __future__ import annotations

from ctypes import Union
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta, timezone
import traceback
from uuid import uuid4

from .db import get_session, init_db
from .models import Account, CryptoCurrency, FiatCurrency
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
import csv


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ByBit Tax App")
        self.geometry("900x500")

        self._make_widgets()

    def _make_widgets(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Taxes tab (replaces previous Tasks tab)
        self.taxes_frame = ttk.Frame(notebook)
        notebook.add(self.taxes_frame, text="Taxes")
        self._init_taxes(self.taxes_frame)

        # Historical Fiat Prices tab
        self.prices_frame = ttk.Frame(notebook)
        notebook.add(self.prices_frame, text="Fiat Prices")
        self._init_prices(self.prices_frame)

        # Download Trades tab
        self.download_frame = ttk.Frame(notebook)
        notebook.add(self.download_frame, text="Download Trades")
        self._init_downloads(self.download_frame)

        # Manual Buys tab
        self.manual_buys_frame = ttk.Frame(notebook)
        notebook.add(self.manual_buys_frame, text="Manual Buys")
        self._init_manual_buys(self.manual_buys_frame)

        # Accounts tab
        self.accounts_frame = ttk.Frame(notebook)
        notebook.add(self.accounts_frame, text="Accounts")
        self._init_accounts(self.accounts_frame)

    def _init_taxes(self, frame: ttk.Frame) -> None:
        row = 0
        ttk.Label(frame, text="Tax calculations (Germany - simplified)", font=("Helvetica", 14, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=8)
        row += 1

        ttk.Label(frame, text="Account").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.tax_account_var = tk.StringVar()
        self.tax_account_combo = ttk.Combobox(frame, textvariable=self.tax_account_var, state="readonly", width=40)
        self.tax_account_combo.grid(row=row, column=1, columnspan=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Optional date filters for the calculation
        ttk.Label(frame, text="Start Date (YYYY-MM-DD)").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.tax_start_var = tk.StringVar(value="")
        self.tax_start_entry = ttk.Entry(frame, textvariable=self.tax_start_var, width=20)
        self.tax_start_entry.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="End Date (YYYY-MM-DD)").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.tax_end_var = tk.StringVar(value="")
        self.tax_end_entry = ttk.Entry(frame, textvariable=self.tax_end_var, width=20)
        self.tax_end_entry.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Defaults: start = first day of current year, end = today
        try:
            from datetime import date
            today = date.today()
            start_of_year = today.replace(month=1, day=1)
            self.tax_start_var.set(start_of_year.isoformat())
            self.tax_end_var.set(today.isoformat())
        except Exception:
            pass

        self.btn_calc_taxes = ttk.Button(frame, text="Calculate", command=self._start_tax_calc)
        self.btn_calc_taxes.grid(row=row, column=0, sticky="w", padx=8, pady=(8, 4))
        self.btn_refresh_tax_accounts = ttk.Button(frame, text="Refresh Accounts", command=self._refresh_tax_accounts)
        self.btn_refresh_tax_accounts.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=(8, 4))
        row += 1

        self.tax_progress = ttk.Progressbar(frame, mode="indeterminate")
        self.tax_progress.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1
        self.tax_status_var = tk.StringVar(value="Idle")
        ttk.Label(frame, textvariable=self.tax_status_var).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 8))
        row += 1

        # Summary table
        columns = ("year", "category", "fees", "net", "net_taxable")
        self.tax_tree = ttk.Treeview(frame, columns=columns, show="headings", height=12, selectmode="extended")
        for col, w, anchor in (
            ("year", 80, "center"),
            ("category", 120, "center"),
            ("fees", 120, "e"),
            ("net", 140, "e"),
            ("net_taxable", 140, "e"),
        ):
            self.tax_tree.heading(col, text=col.replace("_", " ").title())
            self.tax_tree.column(col, width=w, anchor=anchor)
        self.tax_tree.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=8)
        try:
            self.tax_tree.bind("<Double-1>", lambda _e: self._open_tax_chart_for_selection())
        except Exception:
            pass
        frame.rowconfigure(row, weight=1)
        row += 1

        # Export button for selected rows
        btns_tax = ttk.Frame(frame)
        btns_tax.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))
        ttk.Button(btns_tax, text="Export Selected to CSV…", command=lambda: self._export_tax_selection_csv()).pack(side=tk.LEFT)
        row += 1

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self._refresh_tax_accounts()

    def _init_prices(self, frame: ttk.Frame) -> None:
        row = 0
        ttk.Label(frame, text="Historical Fiat Prices", font=("Helvetica", 14, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=8)
        row += 1

        # Pair selection via enums
        ttk.Label(frame, text="Coin").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.price_coin_var = tk.StringVar()
        coin_values = [c.value for c in CryptoCurrency]
        self.price_coin_combo = ttk.Combobox(frame, textvariable=self.price_coin_var, values=coin_values, state="readonly", width=12)
        self.price_coin_combo.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="Fiat").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.price_fiat_var = tk.StringVar()
        fiat_values = [f.value for f in FiatCurrency]
        self.price_fiat_combo = ttk.Combobox(frame, textvariable=self.price_fiat_var, values=fiat_values, state="readonly", width=12)
        self.price_fiat_combo.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Start date
        ttk.Label(frame, text="Start Date (YYYY-MM-DD)").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.price_start_date_var = tk.StringVar()
        self.price_start_date_entry = ttk.Entry(frame, textvariable=self.price_start_date_var, width=20)
        self.price_start_date_entry.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        # Interval selection
        ttk.Label(frame, text="Interval").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.price_interval_var = tk.StringVar()
        # Human-friendly labels mapped to Bybit v5 interval values
        self._price_intervals = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "1h": "60",
            "4h": "240",
            "1d": "D",
        }
        self.price_interval_combo = ttk.Combobox(frame, textvariable=self.price_interval_var, values=list(self._price_intervals.keys()), state="readonly", width=12)
        self.price_interval_combo.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Controls
        self.btn_start_prices = ttk.Button(frame, text="Start", command=self._start_prices_download)
        self.btn_start_prices.grid(row=row, column=0, sticky="w", padx=8, pady=(8, 4))
        row += 1

        # Progress and status
        self.prices_progress = ttk.Progressbar(frame, mode="indeterminate")
        self.prices_progress.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1
        self.prices_status_var = tk.StringVar(value="Idle")
        ttk.Label(frame, textvariable=self.prices_status_var).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 8))
        row += 1

        # Existing coverage table
        ttk.Label(frame, text="Existing price coverage").grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 4))
        row += 1
        columns = ("coin", "fiat", "from", "to", "items")
        self.prices_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        self.prices_tree.heading("coin", text="Coin")
        self.prices_tree.heading("fiat", text="Fiat")
        self.prices_tree.heading("from", text="From")
        self.prices_tree.heading("to", text="To")
        self.prices_tree.heading("items", text="Items")
        self.prices_tree.column("coin", width=80, anchor="center")
        self.prices_tree.column("fiat", width=80, anchor="center")
        self.prices_tree.column("from", width=120, anchor="w")
        self.prices_tree.column("to", width=120, anchor="w")
        self.prices_tree.column("items", width=80, anchor="e")
        self.prices_tree.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=8)
        frame.rowconfigure(row, weight=1)
        row += 1

        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))
        ttk.Button(btns, text="Refresh", command=self._refresh_prices_overview).pack(side=tk.LEFT)
        ttk.Label(btns, text="Tip: select a row to prefill coin/fiat and next start date").pack(side=tk.LEFT, padx=(8, 0))
        row += 1

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.rowconfigure(row, weight=0)

        self.prices_tree.bind("<<TreeviewSelect>>", self._on_prices_tree_selected)

        # Defaults
        try:
            from datetime import date, timedelta
            # subtract one month
            start_date = date.today().replace(day=1) - timedelta(days=1)
            start_date = start_date.replace(day=1)
            self.price_start_date_var.set(start_date.isoformat())
            if coin_values:
                self.price_coin_var.set(coin_values[0])
            if fiat_values:
                self.price_fiat_var.set(fiat_values[0])
            # Default interval to daily
            try:
                self.price_interval_var.set("5m")
            except Exception:
                pass
        except Exception:
            pass

        # Initial load
        self._refresh_prices_overview()

    def _set_prices_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (self.price_coin_combo, self.price_fiat_combo, self.price_start_date_entry, getattr(self, 'price_interval_combo', None), self.btn_start_prices):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _start_prices_download(self) -> None:
        coin = (self.price_coin_var.get() or "").upper().strip()
        fiat = (self.price_fiat_var.get() or "").upper().strip()
        if not coin or not fiat:
            messagebox.showerror("Fiat Prices", "Select both Coin and Fiat.", parent=self)
            return
        try:
            start = datetime.fromisoformat(self.price_start_date_var.get()).date()
        except Exception:
            messagebox.showerror("Fiat Prices", "Invalid start date. Use YYYY-MM-DD.", parent=self)
            return

        self._set_prices_controls_enabled(False)
        self.prices_status_var.set("Starting price download…")
        self.prices_progress.start(120)

        def worker():
            try:
                interval_label = (self.price_interval_var.get() or "1d").strip()
                count = self._do_download_prices(coin, fiat, start, interval_label)
                self.after(0, lambda n=count: self._on_prices_finished(f"Imported {n} points."))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_prices_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_prices_finished(self, msg: str) -> None:
        self.prices_progress.stop()
        self.prices_status_var.set(f"Completed: {msg}")
        self._set_prices_controls_enabled(True)

    def _on_prices_error(self, message: str) -> None:
        self.prices_progress.stop()
        self.prices_status_var.set(f"Error: {message}")
        self._set_prices_controls_enabled(True)

    def _do_download_prices(self, coin: str, fiat: str, start_date: datetime.date, interval_label: str = "1d") -> int:
        """Download kline close prices from Bybit spot for a given interval and persist.

        - Checks symbol as COINFIAT; if not found, tries FIATCOIN and inverts price.
        - Saves rows into HistoricalFiatPrice with timestamp field (kline start, UTC).
        - interval_label: one of keys in self._price_intervals (e.g., '1m','5m','15m','1h','4h','1d').
        - Returns count of imported/updated rows.
        """
        # Import here to avoid hard dependency at import-time
        try:
            from pybit.unified_trading import HTTP  # type: ignore
        except Exception as e:
            raise RuntimeError("pybit is not installed. Please install dependencies.") from e

        client = HTTP(testnet=False)

        # Helper to check instruments
        def spot_symbol_exists(symbol: str) -> bool:
            try:
                res = client.get_instruments_info(category="spot", symbol=symbol)  # type: ignore[attr-defined]
                return bool(res and res.get("retCode") in (0, "0") and res.get("result", {}).get("list"))
            except Exception:
                return False

        sym = f"{coin}{fiat}"
        inverted = False
        if not spot_symbol_exists(sym):
            alt = f"{fiat}{coin}"
            if spot_symbol_exists(alt):
                sym = alt
                inverted = True
            else:
                raise RuntimeError(f"Spot pair not found on Bybit: {coin}/{fiat} nor {fiat}/{coin}")

        # Fetch klines from start to now in pages
        start_ms = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        bybit_interval = self._price_intervals.get(interval_label, "D")

        imported = 0
        limit = 1000  # Bybit allows large batches
        interval_ms_map = {
            "1": 60_000,
            "5": 5 * 60_000,
            "15": 15 * 60_000,
            "60": 60 * 60_000,
            "240": 4 * 60 * 60_000,
            "D": 24 * 60 * 60_000,
        }
        interval_ms = interval_ms_map.get(bybit_interval, 24 * 60 * 60_000)
        window_ms = limit * interval_ms

        window_start = start_ms
        while window_start <= end_ms:
            window_end = min(window_start + window_ms - 1, end_ms)
            self.after(0, lambda ws=window_start, we=window_end, il=interval_label: self.prices_status_var.set(
                f"Fetching {il} klines {datetime.fromtimestamp(ws/1000, tz=timezone.utc).isoformat(sep=' ')} → {datetime.fromtimestamp(we/1000, tz=timezone.utc).isoformat(sep=' ')}…"
            ))

            params = {
                "category": "spot",
                "symbol": sym,
                "interval": bybit_interval,
                "start": window_start,
                "end": window_end,
                "limit": limit,
            }
            data = client.get_kline(**params)  # type: ignore[attr-defined]
            time.sleep(1/10) # maximum 10 requests per second
            if not isinstance(data, dict) or data.get("retCode") not in (0, "0"):
                raise RuntimeError(f"Bybit kline error: {data}")
            klist = (data.get("result") or {}).get("list") or []
            # Normalize sort by timestamp ascending
            try:
                klist.sort(key=lambda x: int(x[0]))
            except Exception:
                pass

            rows = []
            for k in klist:
                try:
                    ts = int(k[0]) + interval_ms
                    close = float(k[4])
                except Exception:
                    continue
                ts_dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                price = (1.0 / close) if inverted and close != 0 else close
                rows.append((ts_dt, price))

            if rows:
                self._persist_hfp_rows(coin, fiat, rows)
                imported += len(rows)

            # Advance to next window without overlap
            window_start = window_end + 1

        return imported

    def _persist_hfp_rows(self, coin: str, fiat: str, rows: list[tuple[datetime, float]]) -> None:
        from .models import HistoricalFiatPrice, CryptoCurrency as CC, FiatCurrency as FC
        # Validate to enums; will raise if invalid
        try:
            coin_enum = CC(coin)
            fiat_enum = FC(fiat)
        except Exception:
            raise RuntimeError(f"Unsupported coin/fiat for HistoricalFiatPrice: {coin}/{fiat}")

        with get_session() as session:
            for ts_dt, price in rows:
                # Upsert by unique constraint (coin, fiat, timestamp)
                obj = (
                    session.query(HistoricalFiatPrice)
                    .filter(
                        HistoricalFiatPrice.coin == coin_enum,
                        HistoricalFiatPrice.fiat == fiat_enum,
                        HistoricalFiatPrice.timestamp == ts_dt,
                    )
                    .one_or_none()
                )
                if obj is None:
                    obj = HistoricalFiatPrice(coin=coin_enum, fiat=fiat_enum, timestamp=ts_dt, price=price)
                    session.add(obj)
                else:
                    obj.price = price

    def _refresh_prices_overview(self) -> None:
        from .models import HistoricalFiatPrice as HFP
        # Clear existing
        for i in getattr(self, "prices_tree", []).get_children():
            self.prices_tree.delete(i)
        # Query grouped coverage
        with get_session() as session:
            rows = (
                session.query(
                    HFP.coin,
                    HFP.fiat,
                    func.min(HFP.timestamp),
                    func.max(HFP.timestamp),
                    func.count(HFP.id),
                )
                .group_by(HFP.coin, HFP.fiat)
                .order_by(HFP.coin.asc(), HFP.fiat.asc())
                .all()
            )
        for coin, fiat, dmin, dmax, cnt in rows:
            cval = getattr(coin, "value", str(coin))
            fval = getattr(fiat, "value", str(fiat))
            self.prices_tree.insert(
                "",
                tk.END,
                values=(cval, fval, (dmin.isoformat(sep=' ') if dmin else ""), (dmax.isoformat(sep=' ') if dmax else ""), int(cnt)),
            )

    def _on_prices_tree_selected(self, _event=None) -> None:
        sel = self.prices_tree.selection()
        if not sel:
            return
        vals = self.prices_tree.item(sel[0], "values")
        if not vals or len(vals) < 5:
            return
        coin, fiat, _from, to, _days = vals
        # Prefill coin/fiat
        try:
            if coin:
                self.price_coin_var.set(coin)
            if fiat:
                self.price_fiat_var.set(fiat)
        except Exception:
            pass
        # Prefill next start date as day after 'to'
        try:
            if to:
                d = datetime.fromisoformat(to).date()
                nd = d.replace(day=d.day)  # no-op guard
                from datetime import timedelta
                nd = d + timedelta(days=1)
                self.price_start_date_var.set(nd.isoformat())
        except Exception:
            pass

    # --- Taxes tab logic
    def _refresh_tax_accounts(self) -> None:
        with get_session() as session:
            rows = session.query(Account).order_by(Account.name.asc()).all()
        self._tax_accounts = {f"{a.name} (#{a.id})": a.id for a in rows}
        keys = list(self._tax_accounts.keys())
        self.tax_account_combo["values"] = keys
        if keys and not self.tax_account_var.get():
            self.tax_account_var.set(keys[0])

    def _set_tax_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (self.tax_account_combo, getattr(self, 'tax_start_entry', None), getattr(self, 'tax_end_entry', None), self.btn_calc_taxes, self.btn_refresh_tax_accounts):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _start_tax_calc(self) -> None:
        label = self.tax_account_var.get().strip()
        if not label or label not in getattr(self, "_tax_accounts", {}):
            messagebox.showerror("Taxes", "Please select an account.", parent=self)
            return
        account_id = self._tax_accounts[label]

        # Parse optional start/end (date-only)
        start_txt = (getattr(self, 'tax_start_var', tk.StringVar(value="")).get() or "").strip()
        end_txt = (getattr(self, 'tax_end_var', tk.StringVar(value="")).get() or "").strip()
        start_dt = None
        end_dt = None
        try:
            if start_txt:
                # Interpret start as start-of-day UTC
                sd = datetime.fromisoformat(start_txt).date()
                start_dt = datetime.combine(sd, datetime.min.time(), tzinfo=timezone.utc)
            if end_txt:
                # Interpret end as end-of-day UTC
                ed = datetime.fromisoformat(end_txt).date()
                end_dt = datetime.combine(ed, datetime.max.time().replace(microsecond=999999), tzinfo=timezone.utc)
        except Exception:
            messagebox.showerror("Taxes", "Invalid date. Use YYYY-MM-DD.", parent=self)
            return
        if start_dt and end_dt and end_dt < start_dt:
            messagebox.showerror("Taxes", "End must be after Start.", parent=self)
            return
        self._set_tax_controls_enabled(False)
        self.tax_status_var.set("Calculating…")
        self.tax_progress.start(120)

        def worker():
            try:
                summary = self._calculate_taxes(account_id, start_dt=start_dt, end_dt=end_dt)
                self.after(0, lambda s=summary: self._render_tax_summary(s))
            except Exception as exc:
                print(traceback.format_exc())
                self.after(0, lambda e=exc: self._on_tax_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_tax_error(self, message: str) -> None:
        self.tax_progress.stop()
        self.tax_status_var.set(f"Error: {message}")
        self._set_tax_controls_enabled(True)

    def _render_tax_summary(self, summary: dict) -> None:
        # Render rows: one per (year, category)
        for i in self.tax_tree.get_children():
            self.tax_tree.delete(i)
        by_year = summary.get("by_year", {}) if isinstance(summary, dict) else {}
        # Keep detailed events for plotting/export
        self._tax_events_by_year = summary.get("events_by_year", {}) if isinstance(summary, dict) else {}
        for year in sorted(by_year.keys()):
            cats = by_year[year]
            for cat_key in ("spot", "deriv"):
                row = cats.get(cat_key, {})
                gains = float(row.get("gains", 0.0))
                losses = float(row.get("losses", 0.0))
                gains_taxable = float(row.get("taxable_gains", 0.0))
                losses_taxable = float(row.get("taxable_losses", 0.0))
                fees = float(row.get("fees", 0.0))
                net = gains - losses
                net_taxable = gains_taxable - losses_taxable
                
                if cat_key == "spot":
                    net -= fees
                    net_taxable -= fees
                    
                self.tax_tree.insert("", tk.END, values=(year, ("Spot" if cat_key == "spot" else "Derivatives"), f"{fees:.2f}", f"{net:.2f}", f"{net_taxable:.2f}"))
        self.tax_progress.stop()
        self.tax_status_var.set("Completed")
        self._set_tax_controls_enabled(True)

    def _open_tax_chart_for_selection(self) -> None:
        # Build cumulative PnL lines for selected rows and show a matplotlib chart
        sel = self.tax_tree.selection()
        if not sel:
            messagebox.showinfo("Taxes", "Select one or more rows to visualize.", parent=self)
            return
        events_map = getattr(self, "_tax_events_by_year", None)
        if not events_map:
            messagebox.showinfo("Taxes", "Please run a calculation first.", parent=self)
            return

        # Parse selections into keys: (year:int, cat_key:str)
        keys: list[tuple[int,str]] = []
        for iid in sel:
            vals = self.tax_tree.item(iid, "values")
            if not vals or len(vals) < 2:
                continue
            try:
                year = int(vals[0])
            except Exception:
                continue
            cat_disp = str(vals[1]).strip().lower()
            cat_key = "spot" if cat_disp.startswith("spot") else "deriv"
            keys.append((year, cat_key))
        if not keys:
            messagebox.showerror("Taxes", "Could not parse selection.", parent=self)
            return

        # Lazy import matplotlib to avoid hard dependency at import-time
        try:
            from matplotlib.figure import Figure  # type: ignore
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # type: ignore
        except Exception as e:
            messagebox.showerror("Plotting", f"matplotlib not available: {e}", parent=self)
            return

        # Prepare single combined series: cumulative net (PnL - fees) over time for all selected rows
        combined_deltas: list[tuple[datetime, float]] = []
        for (year, cat) in keys:
            series_events = (events_map.get(year, {}) or {}).get(cat, [])
            for ev in series_events:
                if ev.get("type") == "pnl":
                    ts = ev.get("close_ts") or ev.get("open_ts")
                    try:
                        amt = float(ev.get("fiat_value", 0.0))
                    except Exception:
                        amt = 0.0
                    if ts:
                        combined_deltas.append((ts, amt))
                elif ev.get("type") == "fee":
                    ts = ev.get("ts")
                    try:
                        amt = -abs(float(ev.get("fiat_fee", 0.0)))
                    except Exception:
                        amt = 0.0
                    if ts:
                        combined_deltas.append((ts, amt))
        combined_deltas.sort(key=lambda x: x[0])
        x_vals: list[datetime] = []
        y_vals: list[float] = []
        csum = 0.0
        for ts, dv in combined_deltas:
            csum += dv
            x_vals.append(ts)
            y_vals.append(csum)
        if len(keys) == 1:
            y0, c0 = keys[0]
            label = f"{y0} - {'Spot' if c0=='spot' else 'Derivatives'}"
        else:
            label = f"Combined ({len(keys)} selections)"

        # Create window and plot
        win = tk.Toplevel(self)
        win.title("Cumulative PnL")
        fig = Figure(figsize=(8, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(x_vals, y_vals, label=label)
        ax.set_title("Cumulative PnL (incl. fees)")
        ax.set_xlabel("Time")
        ax.set_ylabel(f"PnL in {getattr(self, 'current_account_fiat', 'EUR')}")
        ax.legend(loc="best")
        ax.grid(True, linestyle=":", alpha=0.5)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(btns, text="Export CSV…", command=lambda k=keys: self._export_tax_selection_csv(k)).pack(side=tk.LEFT)

    def _export_tax_selection_csv(self, preselected: list[tuple[int,str]] | None = None) -> None:
        events_map = getattr(self, "_tax_events_by_year", None)
        if not events_map:
            messagebox.showinfo("Export", "No tax details to export. Run a calculation first.", parent=self)
            return
        # Determine selection if not provided
        keys: list[tuple[int,str]] = []
        if preselected is None:
            sel = self.tax_tree.selection()
            for iid in sel:
                vals = self.tax_tree.item(iid, "values")
                if not vals or len(vals) < 2:
                    continue
                try:
                    year = int(vals[0])
                except Exception:
                    continue
                cat_disp = str(vals[1]).strip().lower()
                cat_key = "spot" if cat_disp.startswith("spot") else "deriv"
                keys.append((year, cat_key))
        else:
            keys = list(preselected)

        if not keys:
            messagebox.showinfo("Export", "Select one or more rows to export.", parent=self)
            return

        # Ask for file path
        try:
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Export CSV",
                defaultextension=".csv",
                filetypes=[("CSV files", ".csv")],
                initialfile="tax_details.csv",
            )
        except Exception:
            path = ""
        if not path:
            return

        header = [
            "year","category","type","asset","qty","quote",
            "open_ts","close_ts","open_price","close_price",
            "fiat_value","fiat_fee","taxable",
        ]
        # Collect and sort events across all selected rows by effective timestamp
        combined: list[tuple[datetime, int, str, dict]] = []  # (ts, year, cat, event)
        for year, cat in keys:
            evs = (events_map.get(year, {}) or {}).get(cat, [])
            for ev in evs:
                if ev.get("type") == "pnl":
                    ts = ev.get("close_ts") or ev.get("open_ts")
                else:
                    ts = ev.get("ts")
                if ts is None:
                    continue
                combined.append((ts, year, cat, ev))

        combined.sort(key=lambda t: t[0])

        rows: list[list[str]] = []
        # for ts, year, cat in combined:
        #     ev = _ = None
        #     # unpack tuple properly (ts, year, cat, ev)
        
        # build rows now in sorted order
        rows = []
        for ts, year, cat, ev in combined:
            if ev.get("type") == "pnl":
                rows.append([
                    str(year),
                    "spot" if cat == "spot" else "deriv",
                    "pnl",
                    str(ev.get("asset") or ""),
                    f"{float(ev.get('qty', 0.0)):.10f}",
                    str(ev.get("quote") or ""),
                    (ev.get("open_ts").isoformat(sep=' ') if ev.get("open_ts") else ""),
                    (ev.get("close_ts").isoformat(sep=' ') if ev.get("close_ts") else ""),
                    (f"{float(ev.get('open_price', 0.0)):.10f}" if ev.get("open_price") is not None else ""),
                    (f"{float(ev.get('close_price', 0.0)):.10f}" if ev.get("close_price") is not None else ""),
                    f"{float(ev.get('fiat_value', 0.0)):.10f}",
                    "",
                    ("1" if ev.get("taxable", True) else "0"),
                ])
            elif ev.get("type") == "fee":
                rows.append([
                    str(year),
                    "spot" if cat == "spot" else "deriv",
                    "fee",
                    "",
                    "",
                    "",
                    (ev.get("ts").isoformat(sep=' ') if ev.get("ts") else ""),
                    "",
                    "","",
                    "",
                    f"{float(ev.get('fiat_fee', 0.0)):.10f}",
                    "1",
                ])

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)
        except Exception as e:
            messagebox.showerror("Export", f"Failed to write CSV: {e}", parent=self)
            return
        messagebox.showinfo("Export", f"Exported {len(rows)} rows to {path}", parent=self)

    def _calculate_taxes(self, account_id: int, start_dt: datetime | None = None, end_dt: datetime | None = None) -> dict:
        # FIFO tax calculation in-memory, split by category (Spot vs Derivatives)
        # Assumptions:
        # - EUR is base fiat; we don't track EUR lots.
        # - Fees on spot are in quote currency; included in EUR via conversion on the event date.
        # - Derivative closed PnL produces quote currency lots for positive net (after fees), categorized as 'deriv'.
        #   Negative net is treated as immediate loss in EUR for derivative category.
        # - HistoricalFiatPrice provides EUR conversion for BTC/ETH/USDT; we use the closest date on or before the event.
        from .models import SpotExecution, DerivativeClosedPnl, HistoricalFiatPrice as HFP

        # Helper: parse symbol into (base, quote)
        def parse_symbol(sym: str) -> tuple[str, str]:
            for q in list(CryptoCurrency._value2member_map_.keys()) + list(FiatCurrency._value2member_map_.keys()):
                if sym.endswith(q):
                    return sym[: -len(q)], q
            return sym[:-3], sym[-3:]
        
        # get account's fiat
        with get_session() as s:
            account = s.query(Account).filter(Account.id == account_id).one_or_none()
            if account is None:
                raise RuntimeError(f"Account ID {account_id} not found.")
            fiat = (account.fiat_currency.value if account.fiat_currency else "EUR").upper()
        # store for UI labels
        try:
            self.current_account_fiat = fiat
        except Exception:
            pass

        # Helper: get EUR per coin at timestamp using nearest price within 12 hours
        def fiat_rate_for(coin: str, dt: datetime, r: SpotExecution = None) -> float:
            if coin.upper() == fiat.upper():
                return 1.0
            if r is not None:
                if r.base.upper() == coin.upper() and r.quote.upper() == fiat.upper():
                    return r.price
                if r.quote.upper() == coin.upper() and r.base.upper() == fiat.upper():
                    return 1.0 / r.price
                
            max_diff = timedelta(hours=12)
            with get_session() as s2:
                before = (
                    s2.query(HFP)
                    .filter(HFP.coin == coin.upper(), HFP.fiat == fiat.upper(), HFP.timestamp <= dt)
                    .order_by(HFP.timestamp.desc())
                    .first()
                )
                after = (
                    s2.query(HFP)
                    .filter(HFP.coin == coin.upper(), HFP.fiat == fiat.upper(), HFP.timestamp >= dt)
                    .order_by(HFP.timestamp.asc())
                    .first()
                )
            candidates = []
            if before is not None:
                candidates.append(before)
            if after is not None and (not before or after.timestamp != before.timestamp):
                candidates.append(after)
            if not candidates:
                raise RuntimeError(f"Missing {fiat} price for {coin} around {dt.isoformat()} (no data).")
            closest = min(candidates, key=lambda r: abs((r.timestamp - dt)))
            if abs(closest.timestamp - dt) > max_diff:
                raise RuntimeError(
                    f"Closest {fiat} price for {coin} at {closest.timestamp.isoformat()} is more than 12h from requested time {dt.isoformat()}"
                )
            return float(closest.price)

        # Lot model
        class Lot:
            __slots__ = ("qty", "buy_price", "category", "ts")
            def __init__(self, qty: float, buy_price: float, category: str, ts: datetime):
                self.qty = qty
                self.buy_price = buy_price
                self.category = category  # 'spot' | 'deriv'
                self.ts = ts

        # Pools: asset -> list[Lot] ordered by ts (FIFO)
        pools: dict[str, list[Lot]] = {}

        class CategorySummary:
            def __init__(self) -> None:
                self.gains = 0.0
                self.losses = 0.0
                self.taxable_gains = 0.0
                self.taxable_losses = 0.0
                self.fees = 0.0

            def as_dict(self) -> dict:
                return {
                    "gains": self.gains,
                    "losses": self.losses,
                    "taxable_gains": self.taxable_gains,
                    "taxable_losses": self.taxable_losses,
                    "fees": self.fees,
                }

        # Yearly buckets per category
        agg: dict[int, dict[str, CategorySummary]] = {}
        # Detailed events per year/category for plotting/export
        events_by_year: dict[int, dict[str, list[dict]]] = {}

        def add_fee(category: str, dt: datetime, fiat_amount: float):
            y = dt.year
            agg.setdefault(y, {}).setdefault(category, CategorySummary())
            agg[y][category].fees += fiat_amount
            events_by_year.setdefault(y, {}).setdefault(category, []).append({
                "type": "fee",
                "ts": dt,
                "fiat_fee": float(fiat_amount),
                "category": category,
            })

        def add_pl(category: str, dt: datetime, fiat_amount: float, taxable: bool = True):
            y = dt.year
            d = agg.setdefault(y, {}).setdefault(category, CategorySummary())
            if fiat_amount >= 0:
                d.gains += fiat_amount
                if taxable:
                    d.taxable_gains += fiat_amount
            else:
                d.losses += -fiat_amount
                if taxable:
                    d.taxable_losses += -fiat_amount

        def add_lot(asset: str, qty: float, buy_price: float, ts: datetime):
            category = "spot"  # default for spot executions
            if qty <= 0:
                return
            pools.setdefault(asset.upper(), []).append(Lot(qty, buy_price, category, ts))

        def dispose(asset: str, quote: str, qty: float, sell_price: float, ts: datetime):
            # Consume from oldest lots across categories; attribute P/L by lot.category
            if qty <= 0:
                return
            asset = asset.upper()
            lots = pools.get(asset, [])
            remain = qty
            
            while remain > 1e-8:
                if not lots:
                    raise RuntimeError(f"Not enough {asset} to sell {qty} at {ts.isoformat()}")

                lot = lots[0]
                take = min(lot.qty, remain)
                proceeds = sell_price * take
                cost = lot.buy_price * take
                quote_fiat_rate = fiat_rate_for(quote, ts)
                fiat_pnl = (proceeds - cost) * quote_fiat_rate
                # not taxable if buy and sell longer than 1 year apart
                taxable = (ts - lot.ts) < timedelta(days=365)
                add_pl(lot.category, ts, fiat_pnl, taxable=taxable)
                # record detailed event
                y = ts.year
                events_by_year.setdefault(y, {}).setdefault(lot.category, []).append({
                    "type": "pnl",
                    "asset": asset,
                    "qty": float(take),
                    "quote": quote,
                    "open_ts": lot.ts,
                    "close_ts": ts,
                    "open_price": float(lot.buy_price),
                    "close_price": float(sell_price),
                    "fiat_value": float(fiat_pnl),
                    "taxable": bool(taxable),
                    "category": lot.category,
                })
                lot.qty -= take
                remain -= take
                if lot.qty <= 1e-8:
                    lots.pop(0)
            pools[asset] = lots

        # Gather and process events in chronological order
        with get_session() as session:
            q_spot = session.query(SpotExecution).filter(SpotExecution.account_id == account_id)
            if start_dt:
                q_spot = q_spot.filter(SpotExecution.timestamp >= start_dt)
            if end_dt:
                q_spot = q_spot.filter(SpotExecution.timestamp <= end_dt)
            spot_rows = q_spot.order_by(SpotExecution.timestamp.asc()).all()

            q_deriv = session.query(DerivativeClosedPnl).filter(DerivativeClosedPnl.account_id == account_id)
            if start_dt:
                q_deriv = q_deriv.filter(DerivativeClosedPnl.timestamp >= start_dt)
            if end_dt:
                q_deriv = q_deriv.filter(DerivativeClosedPnl.timestamp <= end_dt)
            deriv_rows = q_deriv.order_by(DerivativeClosedPnl.timestamp.asc()).all()

        # Merge events by time
        events: list[tuple[datetime, str, Union[SpotExecution, DerivativeClosedPnl]]] = []  # (ts, kind, row)
        for r in spot_rows:
            events.append((r.timestamp, "spot", r))
        for r in deriv_rows:
            events.append((r.timestamp, "deriv", r))
        events.sort(key=lambda x: x[0])

        for ts, kind, row in events:
            if kind == "spot":
                r: SpotExecution = row
                base = r.base.upper()
                quote = r.quote.upper()
                qty = float(r.qty)
                price = float(r.price)
                fee_quote = float(r.fees or 0.0)
                rate_quote_fiat = fiat_rate_for(quote, ts, r)
                side = getattr(r.side, "name", str(r.side)).upper()
                if side == "BUY":
                    add_lot(base, qty, price, ts)
                    add_fee("spot", ts, fee_quote * rate_quote_fiat)
                else:  # SELL
                    dispose(base, quote, qty, price, ts)
                    add_fee("spot", ts, fee_quote * rate_quote_fiat)
            else:
                r: DerivativeClosedPnl = row
                sym = (r.symbol or "").upper()
                base, quote = parse_symbol(sym)
                net_units = float(r.closed_pnl or 0.0)
                rate_quote_fiat = fiat_rate_for(quote, ts)
                if (r.fees or 0.0) > 0:
                    add_fee("deriv", ts, float(r.fees) * rate_quote_fiat)

                if net_units > 0:
                    add_lot(quote, net_units, rate_quote_fiat, ts)
                elif net_units < 0:
                    dispose(quote, fiat, -net_units, rate_quote_fiat, ts)

                add_pl("deriv", ts, net_units * rate_quote_fiat)
                # record derivative detailed event (entry timestamp not available in model; use close ts)
                y = ts.year
                events_by_year.setdefault(y, {}).setdefault("deriv", []).append({
                    "type": "pnl",
                    "asset": base,
                    "qty": float(abs(getattr(r, 'qty', 0.0) or 0.0)),
                    "quote": quote,
                    "open_ts": ts,
                    "close_ts": ts,
                    "open_price": (float(r.entry_price) if r.entry_price is not None else None),
                    "close_price": (float(r.exit_price) if r.exit_price is not None else None),
                    "fiat_value": float(net_units * rate_quote_fiat),
                    "taxable": True,
                    "category": "deriv",
                })

        # Finalize net per year/category
        for y, cats in agg.items():
            for cat in ("spot", "deriv"):
                # Convert CategorySummary to dict
                d = cats.get(cat, CategorySummary())
                cats[cat] = d.as_dict()

        return {"by_year": agg, "events_by_year": events_by_year}


    # --- Manual Buys tab
    def _init_manual_buys(self, frame: ttk.Frame) -> None:
        from .models import CryptoCurrency as CC, FiatCurrency as FC
        row = 0
        ttk.Label(frame, text="Manual Spot Buys", font=("Helvetica", 14, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=8)
        row += 1

        # Account selection
        ttk.Label(frame, text="Account").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.manual_account_var = tk.StringVar()
        self.manual_account_combo = ttk.Combobox(frame, textvariable=self.manual_account_var, state="readonly", width=40)
        self.manual_account_combo.grid(row=row, column=1, columnspan=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Inputs
        ttk.Label(frame, text="Base").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.manual_base_var = tk.StringVar()
        self.manual_base_combo = ttk.Combobox(frame, textvariable=self.manual_base_var, values=[c.value for c in CC], state="readonly", width=12)
        self.manual_base_combo.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="Quote").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.manual_quote_var = tk.StringVar()
        # quote can be either crypto or fiat
        self.manual_quote_combo = ttk.Combobox(frame, textvariable=self.manual_quote_var, values=[c.value for c in CC] + [f.value for f in FC], state="readonly", width=12)
        self.manual_quote_combo.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        ttk.Label(frame, text="Quantity").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.manual_qty_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.manual_qty_var, width=16).grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="Price").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.manual_price_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.manual_price_var, width=16).grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        ttk.Label(frame, text="Fees (in quote)").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.manual_fees_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=self.manual_fees_var, width=16).grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="Timestamp (YYYY-MM-DD HH:MM)").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.manual_ts_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.manual_ts_var, width=20).grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(btns, text="Add Manual Buy", command=self._add_manual_buy).pack(side=tk.LEFT)
        ttk.Button(btns, text="Refresh", command=self._refresh_manual_buys).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Delete Selected", command=self._delete_selected_manual).pack(side=tk.LEFT, padx=(8, 0))
        row += 1

        # List of manual buys
        columns = ("exec_id", "timestamp", "base", "quote", "qty", "price", "fees")
        self.manual_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        for col, text_, width, anchor in (
            ("exec_id", "Exec ID", 220, "w"),
            ("timestamp", "Timestamp", 160, "w"),
            ("base", "Base", 80, "center"),
            ("quote", "Quote", 80, "center"),
            ("qty", "Qty", 120, "e"),
            ("price", "Price", 120, "e"),
            ("fees", "Fees", 120, "e"),
        ):
            self.manual_tree.heading(col, text=text_)
            self.manual_tree.column(col, width=width, anchor=anchor)
        self.manual_tree.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=8)
        frame.rowconfigure(row, weight=1)
        row += 1

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        # Defaults
        try:
            from datetime import datetime as _dt
            now = _dt.now(timezone.utc).replace(second=0, microsecond=0)
            self.manual_ts_var.set(now.strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass

        # Accounts list and initial load
        self._refresh_manual_accounts()
        try:
            self.manual_account_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_manual_buys())
        except Exception:
            pass
        self._refresh_manual_buys()

    def _refresh_manual_accounts(self) -> None:
        with get_session() as session:
            rows = session.query(Account).order_by(Account.name.asc()).all()
        self._manual_accounts = {f"{a.name} (#{a.id})": a.id for a in rows}
        keys = list(self._manual_accounts.keys())
        self.manual_account_combo["values"] = keys
        if keys and not self.manual_account_var.get():
            self.manual_account_var.set(keys[0])

    def _get_selected_manual_account_id(self) -> int | None:
        label = (self.manual_account_var.get() or "").strip()
        return getattr(self, "_manual_accounts", {}).get(label)

    def _refresh_manual_buys(self) -> None:
        from .models import SpotExecution
        for i in getattr(self, "manual_tree", []).get_children():
            self.manual_tree.delete(i)
        account_id = self._get_selected_manual_account_id()
        if not account_id:
            return
        with get_session() as session:
            rows = (
                session.query(SpotExecution)
                .filter(SpotExecution.account_id == account_id, SpotExecution.is_manual == True)
                .order_by(SpotExecution.timestamp.asc())
                .all()
            )
        for r in rows:
            self.manual_tree.insert(
                "",
                tk.END,
                values=(r.exec_id, r.timestamp.isoformat(sep=' '), r.base, r.quote, f"{float(r.qty):.8f}", f"{float(r.price):.8f}", f"{float(r.fees or 0):.8f}"),
            )

    def _add_manual_buy(self) -> None:
        from .models import SpotExecution, TradeSide
        account_id = self._get_selected_manual_account_id()
        if not account_id:
            messagebox.showerror("Manual Buys", "Please select an account.", parent=self)
            return
        base = (self.manual_base_var.get() or "").upper().strip()
        quote = (self.manual_quote_var.get() or "").upper().strip()
        if not base or not quote:
            messagebox.showerror("Manual Buys", "Please select base and quote.", parent=self)
            return
        try:
            qty = float(self.manual_qty_var.get())
            price = float(self.manual_price_var.get())
            fees = float(self.manual_fees_var.get() or 0)
        except Exception:
            messagebox.showerror("Manual Buys", "Invalid numeric values for quantity/price/fees.", parent=self)
            return
        if qty <= 0 or price <= 0:
            messagebox.showerror("Manual Buys", "Quantity and price must be positive.", parent=self)
            return
        try:
            ts_txt = (self.manual_ts_var.get() or "").strip()
            # Accept date-only as start-of-day UTC
            if len(ts_txt) == 10:
                ts = datetime.fromisoformat(ts_txt).replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromisoformat(ts_txt)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            messagebox.showerror("Manual Buys", "Invalid timestamp. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.", parent=self)
            return

        exec_id = f"MANUAL-{uuid4()}"
        try:
            with get_session() as session:
                obj = SpotExecution(
                    exec_id=exec_id,
                    account_id=account_id,
                    base=base,
                    quote=quote,
                    side=TradeSide.BUY,
                    qty=qty,
                    price=price,
                    fees=fees,
                    timestamp=ts,
                    is_manual=True,
                )
                session.add(obj)
        except Exception as e:
            messagebox.showerror("Manual Buys", f"Failed to save: {e}", parent=self)
            return
        self._refresh_manual_buys()

    def _delete_selected_manual(self) -> None:
        from .models import SpotExecution
        sel = self.manual_tree.selection()
        if not sel:
            messagebox.showinfo("Manual Buys", "Please select a row to delete.", parent=self)
            return
        vals = self.manual_tree.item(sel[0], "values")
        if not vals:
            return
        exec_id = vals[0]
        if not messagebox.askyesno("Manual Buys", "Delete selected manual buy?", parent=self):
            return
        try:
            with get_session() as session:
                obj = session.get(SpotExecution, exec_id)
                if obj is not None:
                    session.delete(obj)
        except Exception as e:
            messagebox.showerror("Manual Buys", f"Failed to delete: {e}", parent=self)
            return
        self._refresh_manual_buys()


    # --- Accounts tab
    def _init_accounts(self, frame: ttk.Frame) -> None:
        row = 0
        ttk.Label(frame, text="Accounts", font=("Helvetica", 14, "bold")).grid(row=row, column=0, sticky="w", padx=8, pady=8)
        row += 1

        columns = ("id", "name", "fiat_currency", "api_key", "api_secret")
        self.accounts_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        self.accounts_tree.heading("id", text="ID")
        self.accounts_tree.heading("name", text="Name")
        self.accounts_tree.heading("fiat_currency", text="Fiat")
        self.accounts_tree.heading("api_key", text="API Key")
        self.accounts_tree.heading("api_secret", text="API Secret")
        self.accounts_tree.column("id", width=60, anchor="center")
        self.accounts_tree.column("name", width=200)
        self.accounts_tree.column("fiat_currency", width=100)
        self.accounts_tree.column("api_key", width=260)
        self.accounts_tree.column("api_secret", width=140)
        self.accounts_tree.grid(row=row, column=0, sticky="nsew", padx=8)
        frame.rowconfigure(row, weight=1)
        frame.columnconfigure(0, weight=1)
        row += 1

        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(btns, text="Add Account", command=self._open_add_account_dialog).pack(side=tk.LEFT)
        ttk.Button(btns, text="Edit Selected", command=self._open_edit_account_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Refresh", command=self._refresh_accounts).pack(side=tk.LEFT, padx=(8, 0))

        self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        for i in self.accounts_tree.get_children():
            self.accounts_tree.delete(i)
        with get_session() as session:
            rows = session.query(Account).order_by(Account.name.asc()).all()
        for a in rows:
            masked = "••••••" if a.api_secret else ""
            self.accounts_tree.insert("", tk.END, values=(a.id, a.name, a.fiat_currency.value, a.api_key, masked))

    def _open_add_account_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("Add Account")
        win.transient(self)
        win.grab_set()

        name_var = tk.StringVar()
        key_var = tk.StringVar()
        secret_var = tk.StringVar()

        ttk.Label(win, text="Name").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        name_entry = ttk.Entry(win, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, sticky="w", padx=6, pady=6)

        available_fiats = [fc.value for fc in FiatCurrency]
        ttk.Label(win, text="Fiat Currency").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        fiat_var = tk.StringVar(value="EUR")
        fiat_combo = ttk.Combobox(win, textvariable=fiat_var, values=available_fiats, state="readonly", width=10)
        fiat_combo.grid(row=0, column=3, sticky="w", padx=6, pady=6)

        ttk.Label(win, text="API Key").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        key_entry = ttk.Entry(win, textvariable=key_var, width=40)
        key_entry.grid(row=1, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(win, text="API Secret").grid(row=2, column=0, sticky="e", padx=6, pady=6)
        secret_entry = ttk.Entry(win, textvariable=secret_var, width=40, show="•")
        secret_entry.grid(row=2, column=1, sticky="w", padx=6, pady=6)

        def save():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Validation", "Name is required.", parent=win)
                return
            if not fiat_var.get().strip():
                messagebox.showerror("Validation", "Fiat currency is required.", parent=win)
                return
            if not key_var.get().strip():
                messagebox.showerror("Validation", "API Key is required.", parent=win)
                return
            if not secret_var.get().strip():
                messagebox.showerror("Validation", "API Secret is required.", parent=win)
                return
            try:
                with get_session() as session:
                    session.add(Account(name=name, api_key=key_var.get(), api_secret=secret_var.get(), fiat_currency=fiat_var.get()))
            except IntegrityError:
                messagebox.showerror("Error", "Account name must be unique.", parent=win)
                return
            win.destroy()
            self._refresh_accounts()

        btns = ttk.Frame(win)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", padx=6, pady=10)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Save", command=save).pack(side=tk.RIGHT, padx=(0, 8))

        name_entry.focus_set()

    def _get_selected_account_id(self) -> int | None:
        sel = self.accounts_tree.selection()
        if not sel:
            return None
        vals = self.accounts_tree.item(sel[0], "values")
        try:
            return int(vals[0])
        except Exception:
            return None

    def _open_edit_account_dialog(self) -> None:
        acc_id = self._get_selected_account_id()
        if acc_id is None:
            messagebox.showinfo("Edit Account", "Please select an account to edit.", parent=self)
            return

        with get_session() as session:
            acc = session.get(Account, acc_id)
        if acc is None:
            messagebox.showerror("Edit Account", "Selected account not found.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title(f"Edit Account: {acc.name}")
        win.transient(self)
        win.grab_set()

        name_var = tk.StringVar(value=acc.name)
        key_var = tk.StringVar(value=acc.api_key)
        secret_var = tk.StringVar(value=acc.api_secret)
        secret_hidden = tk.BooleanVar(value=True)

        ttk.Label(win, text="Name").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        name_entry = ttk.Entry(win, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, sticky="w", padx=6, pady=6)

        available_fiats = [fc.value for fc in FiatCurrency]
        ttk.Label(win, text="Fiat Currency").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        fiat_var = tk.StringVar(value=acc.fiat_currency)
        fiat_combo = ttk.Combobox(win, textvariable=fiat_var, values=available_fiats, state="readonly", width=10)
        fiat_combo.grid(row=0, column=3, sticky="w", padx=6, pady=6)

        ttk.Label(win, text="API Key").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        key_entry = ttk.Entry(win, textvariable=key_var, width=40)
        key_entry.grid(row=1, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(win, text="API Secret").grid(row=2, column=0, sticky="e", padx=6, pady=6)
        secret_entry = ttk.Entry(win, textvariable=secret_var, width=40, show="•")
        secret_entry.grid(row=2, column=1, sticky="w", padx=6, pady=6)

        def toggle_secret():
            if secret_hidden.get():
                secret_entry.configure(show="")
                secret_hidden.set(False)
                toggle_btn.configure(text="Hide Secret")
            else:
                secret_entry.configure(show="•")
                secret_hidden.set(True)
                toggle_btn.configure(text="Show Secret")

        toggle_btn = ttk.Button(win, text="Show Secret", command=toggle_secret)
        toggle_btn.grid(row=2, column=2, sticky="w", padx=(0, 6))

        def save():
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showerror("Validation", "Name is required.", parent=win)
                return
            try:
                with get_session() as session:
                    obj = session.get(Account, acc_id)
                    if obj is None:
                        raise RuntimeError("Account disappeared.")
                    obj.name = new_name
                    obj.fiat_currency = fiat_var.get()
                    obj.api_key = key_var.get()
                    obj.api_secret = secret_var.get()
            except IntegrityError:
                messagebox.showerror("Error", "Account name must be unique.", parent=win)
                return
            win.destroy()
            self._refresh_accounts()

        btns = ttk.Frame(win)
        btns.grid(row=3, column=0, columnspan=3, sticky="e", padx=6, pady=10)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Save", command=save).pack(side=tk.RIGHT, padx=(0, 8))


    # --- Download Trades tab
    def _init_downloads(self, frame: ttk.Frame) -> None:
        row = 0
        ttk.Label(frame, text="Download Trades", font=("Helvetica", 14, "bold")).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=8)
        row += 1

        # Account selection
        ttk.Label(frame, text="Account").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.download_account_var = tk.StringVar()
        self.download_account_combo = ttk.Combobox(frame, textvariable=self.download_account_var, state="readonly", width=40)
        self.download_account_combo.grid(row=row, column=1, columnspan=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Date range
        ttk.Label(frame, text="Start Date (YYYY-MM-DD)").grid(row=row, column=0, sticky="e", padx=(8, 4))
        self.start_date_var = tk.StringVar()
        self.start_date_entry = ttk.Entry(frame, textvariable=self.start_date_var, width=20)
        self.start_date_entry.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

        ttk.Label(frame, text="End Date (YYYY-MM-DD)").grid(row=row, column=2, sticky="e", padx=(8, 4))
        self.end_date_var = tk.StringVar()
        self.end_date_entry = ttk.Entry(frame, textvariable=self.end_date_var, width=20)
        self.end_date_entry.grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
        row += 1

        # Controls
        self.btn_start_download = ttk.Button(frame, text="Start", command=self._start_download)
        self.btn_start_download.grid(row=row, column=0, sticky="w", padx=8, pady=(8, 4))
        self.btn_refresh_download_accounts = ttk.Button(frame, text="Refresh Accounts", command=self._refresh_download_accounts)
        self.btn_refresh_download_accounts.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=(8, 4))
        row += 1

        # Progress bar and status
        self.download_progress = ttk.Progressbar(frame, mode="indeterminate")
        self.download_progress.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8)
        row += 1

        self.download_status_var = tk.StringVar(value="Idle")
        ttk.Label(frame, textvariable=self.download_status_var).grid(row=row, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 8))
        row += 1

        # Existing downloads overview for selected account
        ttk.Label(frame, text="Existing downloads (selected account)").grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 4))
        row += 1
        columns = ("category", "from", "to", "rows")
        self.downloads_tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for col, text_, width, anchor in (
            ("category", "Category", 120, "center"),
            ("from", "From", 180, "w"),
            ("to", "To", 180, "w"),
            ("rows", "Rows", 100, "e"),
        ):
            self.downloads_tree.heading(col, text=text_)
            self.downloads_tree.column(col, width=width, anchor=anchor)
        self.downloads_tree.grid(row=row, column=0, columnspan=4, sticky="nsew", padx=8)
        frame.rowconfigure(row, weight=1)
        row += 1

        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))
        ttk.Button(btns, text="Refresh", command=self._refresh_downloads_overview).pack(side=tk.LEFT)
        row += 1

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        # Initialize account list and default dates
        self._refresh_download_accounts()
        try:
            from datetime import date, timedelta
            today = date.today()
            start_date = today.replace(day=1) - timedelta(days=1)
            start_date = start_date.replace(day=1)
            self.end_date_var.set(today.isoformat())
            self.start_date_var.set(start_date.isoformat())
        except Exception:
            pass

        # Bind account selection to refresh the overview table
        try:
            self.download_account_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_downloads_overview())
        except Exception:
            pass

        # Initial overview
        self._refresh_downloads_overview()

    def _refresh_download_accounts(self) -> None:
        # Load accounts into combobox as "name (#id)" while storing mapping
        with get_session() as session:
            rows = session.query(Account).order_by(Account.name.asc()).all()
        self._download_accounts = {f"{a.name} (#{a.id})": a.id for a in rows}
        keys = list(self._download_accounts.keys())
        self.download_account_combo["values"] = keys
        if keys and not self.download_account_var.get():
            self.download_account_var.set(keys[0])

    def _parse_dates(self) -> tuple[datetime | None, datetime | None]:
        try:
            start = datetime.fromisoformat(self.start_date_var.get()).replace(tzinfo=timezone.utc)
        except Exception:
            start = None
        try:
            # Interpret end date as end-of-day inclusive
            end = datetime.fromisoformat(self.end_date_var.get()).replace(tzinfo=timezone.utc)
            end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception:
            end = None
        return start, end

    def _set_download_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (
            self.download_account_combo,
            self.start_date_entry,
            self.end_date_entry,
            self.btn_start_download,
            self.btn_refresh_download_accounts,
        ):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _start_download(self) -> None:
        label = self.download_account_var.get().strip()
        if not label or label not in getattr(self, "_download_accounts", {}):
            messagebox.showerror("Download Trades", "Please select an account.", parent=self)
            return
        account_id = self._download_accounts[label]
        start_dt, end_dt = self._parse_dates()
        if start_dt is None or end_dt is None or end_dt < start_dt:
            messagebox.showerror("Download Trades", "Please provide a valid date range (YYYY-MM-DD).", parent=self)
            return

        self._set_download_controls_enabled(False)
        self.download_status_var.set("Starting download…")
        self.download_progress.start(100)

        def worker():
            try:
                self._do_download_trades(account_id, start_dt, end_dt)
                self.after(0, lambda: self._on_download_finished("Done"))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_download_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_finished(self, msg: str) -> None:
        self.download_progress.stop()
        self.download_status_var.set(f"Completed: {msg}")
        self._set_download_controls_enabled(True)
        # refresh coverage table
        try:
            self._refresh_downloads_overview()
        except Exception:
            pass

    def _on_download_error(self, message: str) -> None:
        self.download_progress.stop()
        self.download_status_var.set(f"Error: {message}")
        self._set_download_controls_enabled(True)

    def _refresh_downloads_overview(self) -> None:
        """Show existing Spot and Derivatives download coverage for the selected account."""
        # Clear existing
        for i in getattr(self, "downloads_tree", []).get_children():
            self.downloads_tree.delete(i)

        # Resolve selected account id
        label = (self.download_account_var.get() or "").strip()
        account_id = getattr(self, "_download_accounts", {}).get(label)
        if not account_id:
            return

        from .models import SpotExecution, DerivativeClosedPnl
        with get_session() as session:
            # Spot coverage
            s = (
                session.query(
                    func.min(SpotExecution.timestamp),
                    func.max(SpotExecution.timestamp),
                    func.count(SpotExecution.exec_id),
                )
                .filter(SpotExecution.account_id == account_id)
                .one()
            )
            # Derivatives coverage
            d = (
                session.query(
                    func.min(DerivativeClosedPnl.timestamp),
                    func.max(DerivativeClosedPnl.timestamp),
                    func.count(DerivativeClosedPnl.pnl_id),
                )
                .filter(DerivativeClosedPnl.account_id == account_id)
                .one()
            )

        # Insert rows if any data exists
        if s and any(s):
            s_min, s_max, s_cnt = s
            self.downloads_tree.insert(
                "",
                tk.END,
                values=(
                    "Spot",
                    (s_min.isoformat(sep=' ') if s_min else ""),
                    (s_max.isoformat(sep=' ') if s_max else ""),
                    int(s_cnt or 0),
                ),
            )
        if d and any(d):
            d_min, d_max, d_cnt = d
            self.downloads_tree.insert(
                "",
                tk.END,
                values=(
                    "Derivatives",
                    (d_min.isoformat(sep=' ') if d_min else ""),
                    (d_max.isoformat(sep=' ') if d_max else ""),
                    int(d_cnt or 0),
                ),
            )

    def _do_download_trades(self, account_id: int, start_dt: datetime, end_dt: datetime) -> None:
        """Fetch trade executions from Bybit via pybit and upsert into DB.

        Notes:
        - Minimal implementation: tries SPOT and LINEAR categories with v5 execution/list.
        - Progress is shown as indeterminate; we update status text between steps.
        - Gracefully handles missing pybit or API errors.
        """
        # Load credentials
        with get_session() as session:
            acc: Account | None = session.get(Account, account_id)
        if acc is None:
            raise RuntimeError("Account not found.")

        # Import pybit on demand
        try:
            from pybit.unified_trading import HTTP  # type: ignore
        except Exception as e:
            raise RuntimeError("pybit is not installed. Please install dependencies.") from e

        # Create client
        session_http = HTTP(testnet=False, api_key=acc.api_key, api_secret=acc.api_secret)

        # Helper to fetch a single page of executions for a given time window
        def fetch_spot_page(cursor: str | None, start_ms: int, end_ms: int) -> dict:
            params = {
                "category": "spot",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            time.sleep(1/30)
            return session_http.get_executions(**params)  # type: ignore[attr-defined]

        def fetch_linear_page(cursor: str | None, start_ms: int, end_ms: int) -> dict:
            params = {
                "category": "linear",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            time.sleep(1/30)
            return session_http.get_closed_pnl(**params)  # type: ignore[attr-defined]

        # Iterate by category first (SPOT then LINEAR), and within each category step through date windows (≤ ~7 days), with cursor paging inside each window
        from datetime import timedelta
        categories = ["spot", "linear"]
        imported = 0
        for cat in categories:
            window_start = start_dt
            while window_start <= end_dt:
                window_end = window_start + timedelta(days=6, hours=23)
                start_ms = int(window_start.timestamp() * 1000)
                end_ms = int(window_end.timestamp() * 1000)

                self.after(0, lambda c=cat, ws=window_start, we=window_end: self.download_status_var.set(f"Fetching {c.upper()} {ws.date()} → {we.date()}…"))
                cursor: str | None = None
                page = 0
                while True:
                    page += 1
                    data = fetch_spot_page(cursor, start_ms, end_ms) if cat == "spot" else fetch_linear_page(cursor, start_ms, end_ms)
                    # Expected structure: { "retCode": 0, "result": {"list": [...], "nextPageCursor": "..."}}
                    if not isinstance(data, dict) or data.get("retCode") not in (0, "0"):
                        raise RuntimeError(f"Bybit API error: {data}")
                    result = data.get("result") or {}
                    items = result.get("list") or []
                    next_cursor = result.get("nextPageCursor")

                    # Transform and persist
                    if items:
                        self.after(0, lambda c=cat, p=page, n=len(items): self.download_status_var.set(f"{c.upper()} {window_start.date()} → {window_end.date()} page {p}: {n} rows"))
                        if cat == "spot":
                            self._persist_spot_executions(account_id, items)
                        else:
                            self._persist_derivative_pnls(account_id, items)
                        imported += len(items)

                    if not next_cursor:
                        break
                    cursor = next_cursor

                # Keep same window advancement logic
                window_start = window_end

        self.after(0, lambda n=imported: self.download_status_var.set(f"Imported {n} rows."))

    def _persist_spot_executions(self, account_id: int, items: list[dict]) -> None:
        from .models import SpotExecution, TradeSide

        def parse_symbol(sym: str) -> tuple[str, str]:
            # Simple heuristic: split last 3-4 chars; Bybit symbols are like BTCUSDT, ETHUSDC, etc.
            for q in list(CryptoCurrency._value2member_map_.keys()) + list(FiatCurrency._value2member_map_.keys()):
                if sym.endswith(q):
                    return sym[: -len(q)], q
            # Fallback: first 3/last 3
            return sym[:-3], sym[-3:]

        with get_session() as session:
            for it in items:
                try:
                    exec_id = str(it.get("execId"))
                    if not exec_id:
                        continue
                    # Skip if exists
                    if session.get(SpotExecution, exec_id) is not None:
                        continue
                    sym = (it.get("symbol") or "").upper()
                    base, quote = parse_symbol(sym)
                    side_raw = (it.get("side") or "").upper()
                    side = TradeSide.BUY if side_raw == "BUY" else TradeSide.SELL
                    qty = float(it.get("execQty") or 0)
                    price = float(it.get("execPrice") or 0)
                    fee = float(it.get("execFee") or 0)
                    fee_currency = (it.get("feeCurrency") or "").upper()
                    if not fee_currency:
                        print(it)
                        raise RuntimeError("Missing fee currency")
                    if fee_currency not in (base, quote):
                        print(it)
                        raise RuntimeError(f"Unexpected fee currency {fee_currency} for symbol {sym}")
                    if sym.startswith(fee_currency):
                        fee *= price
                    ts_ms = int(it.get("execTime") or it.get("tradeTime") or 0)
                    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                    obj = SpotExecution(
                        exec_id=exec_id,
                        account_id=account_id,
                        base=base,
                        quote=quote,
                        side=side,
                        qty=qty,
                        price=price,
                        fees=fee,
                        timestamp=ts,
                    )
                    session.add(obj)
                except Exception:
                    # Be resilient to malformed rows
                    # continue
                    # for debug reasons dont continue
                    raise

    def _persist_derivative_pnls(self, account_id: int, items: list[dict]) -> None:
        from .models import DerivativeClosedPnl, TradeSide

        with get_session() as session:
            for it in items:
                try:
                    symbol = (it.get("symbol") or "").upper()
                    # Build a stable id
                    pnl_id = str(
                        it.get("orderId")
                        or f"{symbol}:{it.get('createdTime') or it.get('updatedTime') or it.get('closedTime') or 0}:{it.get('closedSize') or it.get('qty') or it.get('size') or 0}:{it.get('avgExitPrice') or it.get('exitPrice') or 0}"
                    )
                    if not pnl_id:
                        continue
                    if session.get(DerivativeClosedPnl, pnl_id) is not None:
                        continue

                    side_raw = (it.get("side") or "").upper()
                    side = TradeSide.BUY if side_raw == "BUY" else TradeSide.SELL
                    qty = float(it.get("qty"))
                    closed_pnl = float(it.get("closedPnl"))
                    fees = float(it.get("openFee") or 0) + float(it.get("closeFee") or 0)
                    entry_price = float(it.get("avgEntryPrice"))
                    exit_price = float(it.get("avgExitPrice"))
                    ts = datetime.fromtimestamp(int(it.get("updatedTime")) / 1000, tz=timezone.utc)

                    obj = DerivativeClosedPnl(
                        pnl_id=pnl_id,
                        account_id=account_id,
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        closed_pnl=closed_pnl,
                        fees=fees,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        timestamp=ts,
                    )
                    session.add(obj)
                except Exception:
                    continue


def run_app() -> int:
    init_db()
    app = App()
    app.mainloop()
    return 0

    
    
    
    
