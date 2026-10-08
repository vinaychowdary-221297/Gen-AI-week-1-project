# CSV Studio

A local website that turns any CSV into a dashboard and a written summary. Upload your own file or try the built-in samples. Everything runs on your computer — files stay local, and the summary is built with plain Python rules (no AI API calls).

## Requirements

- [Python](https://www.python.org/) 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (recommended for install and run)

## How to run

1. Open a terminal in this project folder.

2. Install dependencies and start the app:

```bash
uv run python server.py
```

3. Your browser should open automatically to [http://127.0.0.1:8080](http://127.0.0.1:8080). If it does not, open that URL yourself.

To stop the server, press `Ctrl+C` in the terminal.

### Without uv

```bash
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install flask pandas plotly
python server.py
```

**macOS / Linux:**

```bash
source .venv/bin/activate
pip install flask pandas plotly
python server.py
```

## Using the site

1. **Home** — upload a CSV or click a sample (inventory or portfolio).
2. **Load** — review columns, rename them, change roles, or hide columns you do not need.
3. **Dashboard** — pick a metric, group, filters, and date range; view charts and download filtered data.
4. **Summary** — read a written overview of the current dashboard view.

Extra sample CSVs (`sales.csv`, `website_traffic.csv`) are in `sample_data/` and can be uploaded from Home.

## Project layout

| Path | Purpose |
|------|---------|
| `server.py` | Flask app and routes |
| `analysis.py` | CSV profiling, filtering, summary text |
| `charts.py` | Plotly chart helpers |
| `templates/` | HTML pages |
| `static/` | CSS |
| `sample_data/` | Example CSV files |
