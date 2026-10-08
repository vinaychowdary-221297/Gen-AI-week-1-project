# CSV Studio: Project Write-up

## Project overview

CSV Studio is a small local website that turns any CSV file into a dashboard and a written summary. It is meant to be general: the same site works for an ecommerce inventory, a stock portfolio, a sales export, or website traffic, without any setup for a particular file layout.

The site has four pages, reached from a menu at the top:

- Home: explains the site and offers an upload box and two sample buttons.
- Load: shows the file, a quality check (rows, columns, missing cells, duplicate rows), and a table of every column. Each column gets a guessed role: number, date, category, or text. You can rename a column, change its role, or leave it out.
- Dashboard: a short row of controls (metric, group by, one "All" menu per category filter, and a date range), headline numbers, a trend chart, a breakdown chart, the first 20 filtered rows, and a download of the filtered CSV.
- Summary: a written readout of the current dashboard view. It covers an overview, what stands out (largest and smallest groups, the highest row, outliers), data health (duplicates, missing values, columns with only one value), relationships between number columns, and suggested next looks.

When a file has a quantity and a price column, the site adds a calculated value column automatically: line_value for inventory (quantity × unit_price) and position_value for a portfolio (shares × price).

Everything runs on the user's computer. Files are not sent anywhere, and the summary is written by plain rules in Python, not by an AI model.

Tech stack:

- Python 3.12, with uv managing the environment and packages
- Flask for the web pages
- pandas for reading and analyzing the CSV
- Plotly for the charts

To run it: uv run python server.py, then open http://127.0.0.1:8080.

## Datasets used

All four datasets are small synthetic files created for this project. They live in the sample_data folder. Each one includes a few deliberate flaws so the Load and Summary pages have something real to report.

Inventory (inventory.csv)

- 41 rows and 7 columns: product, sku, category, quantity, unit_price, warehouse, last_restock.
- Four categories (Home, Electronics, Apparel, Grocery) across three warehouses, restocked from January to June 2026.
- Deliberate flaws: one exact duplicate row, one missing quantity, two missing warehouse values, and one large outlier (Bulk Packing Tape at 5,000 units).
- Opened with the "Use inventory sample" button.

Stock portfolio (portfolio.csv)

- 33 rows and 7 columns: ticker, name, sector, shares, price, cost_basis, as_of.
- Eight holdings tracked at four month-end dates from January to April 2026.
- Deliberate flaws: one holding with no sector (four rows), one missing cost basis, and one exact duplicate row.
- Opened with the "Use portfolio sample" button.

Sales (sales.csv)

- 40 rows and 6 columns: order_date, region, channel, product_line, orders, revenue.
- Weekly orders across four regions and two channels from January to May 2026.
- Deliberate flaw: one missing orders value.
- Loaded by choosing the file with the upload box. It has no button.

Website traffic (website_traffic.csv)

- 40 rows and 6 columns: visit_date, source, device, campaign, sessions, signups.
- Weekly sessions and signups by traffic source and device, January to May 2026.
- Deliberate flaw: one blank campaign value.
- Loaded by choosing the file with the upload box. It has no button.

## Prompts used during vibe coding

These are the prompts in the order I used them. The wording below is cleaned up so each request is clear and correctly spelled. The meaning is the same as what I typed during the session.

1. Starting the project:

> I want to build a small Python project with Streamlit. It should be a general website that can load any CSV, such as an ecommerce inventory file, a stock portfolio, or another table. Please use three tabs: the first tab loads a CSV file, the second tab creates dashboards and general views, and the third tab gives a comprehensive summary. Let’s brainstorm first. We can start building after I confirm the plan.

2. Confirming the plan:

> Yes to all four points. Use the three tabs named Load, Dashboard, and Summary. Keep the summary local, with no AI calls. Include the two sample CSV files. Also set the project up with uv.

3. Asking for a website instead of an application:

> Please rebuild this as a website, not a Streamlit application.

4. Simplifying the dashboard:

> Please make the Dashboard page simpler. It is the second page in the menu.

5. Asking for a fix:

> Please check why the site is failing to start, and fix it.

6. Checking the tech stack:

> Are we using this tech stack: Replit, Streamlit, pandas, and Plotly?

> Can we build this website with Streamlit?

> Can we use the tech stack I provided and create the website with it?

7. Adding more sample data:

> Please add more sample data that I can load through the existing file picker. Do not add any new buttons. I want to choose the files myself from my computer. Keep the existing sample buttons, and only create the extra sample files.

8. Asking for this write-up:

> Please create a document I can submit as a Google Doc. Explain what I built. Include a project overview, the datasets used, the prompts I used during vibe coding, the iterations I tried, and any learnings or observations from the workflow.

## Iterations

Iteration 1: Brainstorm before building

I asked for a plan first and confirmed it before any code was written. The agreed plan was three tabs (Load, Dashboard, Summary), a summary written locally with no AI calls, two sample CSVs, and Streamlit, pandas, and Plotly, managed with uv.

Iteration 2: Streamlit app

The first version was a Streamlit app with the three tabs. It guessed column roles, let me edit them in a table, built four charts (trend, breakdown, distribution, and a scatter plot), and wrote the summary. It was checked with both samples, including switching between them and filtering inventory to Electronics only (41 rows down to 9).

Iteration 3: Rebuilt as a website

Streamlit felt like an application rather than a website, so I asked for a website. The agent kept the analysis and chart code and replaced Streamlit with Flask pages: a home page, a top menu, and separate Load, Dashboard, and Summary pages. Settings live in the page address, so a dashboard view can be bookmarked and the Summary page reflects the same filters.

Iteration 4: Simpler dashboard

The dashboard had about eight dropdowns, long checkbox lists, and four charts. It was cut down to two charts (trend and breakdown), one "All" menu per category filter, a date range, and a 20-row table.

Iteration 5: Debugging a startup failure

The site would not start. The cause was the command, not the code: running python server.py uses the computer's main Python, which does not have Flask installed. The packages live in the project environment that uv manages. Starting with uv run python server.py fixed it.

Iteration 6: Tech stack question

I asked whether the project used Replit, Streamlit, pandas, and Plotly. It does not. The current site uses Flask, pandas, and Plotly with uv, runs locally, and never used Replit. Streamlit was the first version and was replaced in iteration 3. I also asked whether Streamlit can build a website (it can serve one in the browser) and whether the site could be rebuilt on my original stack. That rebuild has not been done yet, so the site described here is the Flask version.

Iteration 7: More sample data

I asked for more data to try through the upload box without adding buttons. Two new files were added, sales.csv and website_traffic.csv, and the two existing sample buttons were left as they were.

## Learnings and observations

- Brainstorming first paid off. Agreeing on the tabs, the local-only summary, and the stack before any code meant the first build matched what I had in mind.
- Words like "application" and "website" mean different things to different people. Streamlit does run in a browser, but its look did not match what I meant by a website. Being specific about the look I wanted earlier would have saved a rebuild.
- Changing the stack can still be cheap if the core logic is separate. Because the column guessing, filtering, charts, and summary were in their own files, moving from Streamlit to Flask reused all of them.
- Simpler was better for the dashboard. Two charts and short menus were easier to read than four charts and long checkbox lists, and the Summary page still covers the deeper analysis.
- Many "it's failing" problems are about the environment, not the code. With uv, the site has to be started through uv run so it uses the project's packages.
- Deliberately flawed sample data is a good test. Duplicates, blanks, and an outlier gave the Data health and What stands out sections something real to report, which made it easy to check they worked.
- Short, direct prompts worked well for small changes, such as "Please make the Dashboard page simpler" and "Please check why the site is failing to start." Bigger changes worked better when I named exactly what to keep, for example "Keep the existing sample buttons, and only create the extra sample files."
- I should check the agent's results myself. The agent tested pages automatically, but it could not click through the site in a real browser window, so a quick manual look is still worth doing.
