[![License: NCPUL](https://img.shields.io/badge/license-NCPUL-blue.svg)](./LICENSE.md)

# Bybit Tax Exporter

A small desktop app to download your Bybit trades, fetch historical EUR prices, and calculate a simplified yearly PnL for taxes. It runs locally, stores data in SQLite, and provides a Tkinter GUI.

## Features

- Accounts: store Bybit API key/secret (read-only) per account and choose your fiat (EUR).
- Download Trades: fetch Spot executions and Derivatives closed PnL via Bybit v5 API.
- Fiat Prices: pull historical EUR prices for BTC/ETH/USDT and more; supports multiple intervals.
- Taxes: FIFO-based, Germany-style simplification (spot gains tax-free after 1 year), yearly summary, CSV export and simple PnL chart.
- Manual Buys: add manual spot purchases to include in calculations.
- Local storage: everything is saved in `data/app.db`.

## Install

Prerequisites: Python 3.10+, internet access for the Bybit API.

```bash
# create and activate a virtualenv (recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python src/main.py
```

On first launch the database is created at `data/app.db`.

macOS quick start: double‑click `Bybit Tax Exporter.command` in the project root to start the app from Finder.

## Usage (typical flow)

1) Open the app. 2) Add an account in Accounts (API key/secret, read-only). 3) Download Trades for a date range. 4) Fetch Fiat Prices (e.g., BTC/EUR daily from a past date). 5) Go to Taxes, pick the account, set dates if needed, and Calculate. Optional: export CSV or view the PnL chart.

Tips

- If a tax calculation fails with “missing price around …”, fetch prices covering that period in the Fiat Prices tab.
- Ensure your Bybit API key has permission to read trade history; testnet is not used.

