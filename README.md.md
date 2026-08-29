# Portfolio Return

A simple portfolio analysis and recommendation app for tracking stock performance, comparing against market benchmarks, and generating portfolio suggestions from your holdings.

This project can be run locally on your machine, or cloned from GitHub and used directly from the repository.

## What the app does

- Upload a CSV of holdings and analyze portfolio performance
- Compare returns across multiple trailing windows such as 1M, 3M, 6M, 1Y, 3Y, and 5Y
- View portfolio value, XIRR, benchmark comparison, and per-stock performance
- Optionally use buy price and buy date for cost-basis analysis
- Generate a rule-based recommendation screen based on portfolio and benchmark performance
- Run a simple backtest comparison for monthly vs quarterly rebalancing

## Project structure

- `app.py` — Flask web app
- `backtest.py` — CLI backtest script
- `engine.py` — portfolio math, fetching, and metrics
- `recommender/` — recommendation logic and rendering

## Requirements

- Python 3.10+
- Git
- Internet access for live market data via yfinance

## Local setup

1. Clone the repository:

```bash
git clone https://github.com/vinodmehtahyd/Portfolio_Return.git
cd Portfolio_Return
```

2. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install flask pandas yfinance
```

## Run the app locally

Start the app:

```bash
python app.py
```

Then open this in your browser:

```text
http://127.0.0.1:5000
```

The app will show an upload form for your portfolio CSV.

## CSV format

Your CSV should include at least:

- `ticker`
- `shares`

Optional columns:

- `buy_price`
- `buy_date`

Example:

```csv
ticker,shares,buy_price,buy_date
AAPL,10,150.25,2023-01-15
MSFT,5,280.00,2022-06-20
GOOGL,3
```

Notes:

- If `buy_price` and `buy_date` are missing, the app works in period-based mode and evaluates performance from the stock listing date onward.
- Use correct ticker symbols and, where needed, country suffixes like `.NS` for Indian listings.

## Analyze a portfolio

1. Open the app in your browser.
2. Upload a CSV file containing your holdings.
3. Choose the return windows you want to compare.
4. Click Analyze.

You will see:

- portfolio totals
- benchmark comparison
- return tables
- holdings breakdown
- recommendation button

## Get a recommendation

After running the analysis:

1. Click the "Get Recommendation" button.
2. The app evaluates the portfolio against benchmarks and ranking signals.
3. A recommendation screen is displayed with suggested action and score explanations.

## Run the backtest script

This project also includes a backtest CLI that compares baseline, monthly rebalance, quarterly rebalance, and benchmark performance.

Usage:

```bash
python backtest.py portfolio.csv
```

Optional arguments:

```bash
python backtest.py portfolio.csv 365 1y,3y,5y
```

Arguments:

- first argument: CSV file path
- second argument: number of days ago to start the backtest
- third argument: comma-separated return periods

## GitHub usage

If you want to use the project directly from GitHub:

```bash
git clone https://github.com/vinodmehtahyd/Portfolio_Return.git
cd Portfolio_Return
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If there is no `requirements.txt` in the repo yet, install the packages manually as shown above:

```bash
python -m pip install flask pandas yfinance
```

Then run:

```bash
python app.py
```

## Troubleshooting

- If the app shows no data for a ticker, confirm the ticker is valid and spelled correctly.
- If live data fails, check your internet connection and ensure the ticker is available on Yahoo Finance.
- For Indian stocks, use the correct market symbol format such as `.NS` when needed.

## Notes

This project relies on Yahoo Finance data for current and historical prices, so live market access is required when running the app or backtests.
