"""CSV Studio website. Pages: Home, Load, Dashboard, and Summary."""

from __future__ import annotations

import secrets
import uuid
import webbrowser
from datetime import date
from pathlib import Path
from threading import Timer
from urllib.parse import parse_qsl, urlencode

import pandas as pd
import plotly
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.datastructures import ImmutableMultiDict

from analysis import (
    ROLES,
    auto_rule,
    build_summary,
    build_working,
    category_filter_columns,
    choose_default_date,
    choose_default_group,
    choose_default_metric,
    default_agg,
    default_axes,
    filter_frame,
    fmt_num,
    profile_table,
    read_table,
)
from charts import breakdown_figure, trend_figure

ROOT = Path(__file__).resolve().parent
SAMPLES = {
    "inventory": ("Inventory sample", ROOT / "sample_data" / "inventory.csv"),
    "portfolio": ("Portfolio sample", ROOT / "sample_data" / "portfolio.csv"),
}
RULES = {"Day": "D", "Week": "W", "Month": "M"}
STORE: dict[str, dict] = {}

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


@app.context_processor
def inject_nav():
    data = STORE.get(session.get("sid", ""))
    return {
        "endpoint": request.endpoint,
        "source": None if data is None else data["source"],
        "has_data": data is not None,
    }


def _sid() -> str:
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def get_data():
    return STORE.get(session.get("sid", ""))


def store_frame(frame: pd.DataFrame, source: str) -> None:
    profile = profile_table(frame)
    working = build_working(frame, profile, [])
    STORE[_sid()] = {
        "raw": frame,
        "source": source,
        "profile": profile,
        "working": working,
        "excluded": [],
    }
    session.pop("view_query", None)


def _column_groups(working):
    frame = working.frame
    roles = working.roles
    numbers = [column for column, role in roles.items() if role == "number"]
    categories = [column for column, role in roles.items() if role == "category"]
    dates = [
        column
        for column, role in roles.items()
        if role == "date" and frame[column].notna().any()
    ]
    return numbers, categories, dates


def _date_bounds(frame: pd.DataFrame, date_col: str):
    values = frame[date_col].dropna()
    if values.empty:
        return None
    return values.min().date(), values.max().date()


def _parse_day(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def default_query(working) -> str:
    frame = working.frame
    roles = working.roles
    _, _, dates = _column_groups(working)
    metric = choose_default_metric(roles) or ""
    group = choose_default_group(roles) or ""
    aggregate = "Average" if metric and default_agg(metric) == "mean" else "Sum"
    pairs: list[tuple[str, str]] = [
        ("ready", "1"),
        ("metric", metric),
        ("aggregate", aggregate),
        ("group", group),
        ("interval", "Auto"),
    ]
    if dates:
        date_col = choose_default_date(frame, roles) or dates[0]
        pairs.append(("date", date_col))
        bounds = _date_bounds(frame, date_col)
        if bounds and bounds[0] != bounds[1]:
            pairs.append(("start", bounds[0].isoformat()))
            pairs.append(("end", bounds[1].isoformat()))
    return urlencode(pairs)


def build_page_model(data: dict, args) -> dict:
    working = data["working"]
    frame = working.frame
    roles = working.roles
    numbers, categories, dates = _column_groups(working)
    metric = args.get("metric") if args.get("metric") in numbers else choose_default_metric(roles)
    if metric and args.get("aggregate") in {"Sum", "Average"}:
        aggregate = args.get("aggregate")
    elif metric and default_agg(metric) == "mean":
        aggregate = "Average"
    else:
        aggregate = "Sum"
    how = "mean" if aggregate == "Average" else "sum"

    group_arg = args.get("group")
    if group_arg is None:
        group = choose_default_group(roles)
    elif group_arg in categories:
        group = group_arg
    else:
        group = None

    if dates and args.get("date") in dates:
        date_col = args.get("date")
    else:
        date_col = choose_default_date(frame, roles) if dates else None
    freq = args.get("interval") if args.get("interval") in {"Auto", "Day", "Week", "Month"} else "Auto"

    x_default, y_default = default_axes(roles)
    x_name = args.get("x") if args.get("x") in numbers else x_default
    y_name = args.get("y") if args.get("y") in numbers else y_default
    if args.get("color") in categories:
        color = args.get("color")
    elif "color" in args:
        color = None
    else:
        color = group

    bounds = _date_bounds(frame, date_col) if date_col else None
    start_day = end_day = None
    date_start = date_end = None
    filters_on = False
    date_form = None
    if bounds and bounds[0] == bounds[1]:
        date_form = {"name": date_col, "single": bounds[0].strftime("%d %b %Y")}
    elif bounds:
        start_day = _parse_day(args.get("start"), bounds[0])
        end_day = _parse_day(args.get("end"), bounds[1])
        if start_day > end_day:
            start_day, end_day = end_day, start_day
        date_form = {
            "name": date_col,
            "min": bounds[0].isoformat(),
            "max": bounds[1].isoformat(),
            "start": start_day.isoformat(),
            "end": end_day.isoformat(),
        }
        if start_day != bounds[0] or end_day != bounds[1]:
            filters_on = True
            date_start = pd.Timestamp(start_day)
            date_end = pd.Timestamp(end_day) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    filter_names = category_filter_columns(frame, roles)
    category_filters: dict[str, list[str]] = {}
    filter_ui = []
    ready = args.get("ready") == "1"
    for index, column in enumerate(filter_names):
        options = sorted(frame[column].astype("string").fillna("(blank)").unique().tolist(), key=str.lower)
        picked = [item for item in args.getlist(f"flt_{index}") if item and item.lower() != "all"]
        if ready and picked and set(picked) != set(options):
            category_filters[column] = picked
            filters_on = True
        chosen = picked[0] if len(picked) == 1 and picked[0] in options else ""
        filter_ui.append({"index": index, "name": column, "options": options, "selected": chosen})

    filtered = filter_frame(
        frame,
        date_col=date_col if date_start is not None else None,
        start=date_start,
        end=date_end,
        category_filters=category_filters,
    )
    bits = [data["source"], working.profile, f"{len(frame):,} prepared rows"]
    if working.value_note:
        bits.append(working.value_note)

    kpis = [("Rows", f"{len(filtered):,}")]
    if metric and metric in filtered.columns and filtered[metric].notna().any():
        series = filtered[metric].dropna()
        shown = series.mean() if how == "mean" else series.sum()
        kpis.append((f"{'Average' if how == 'mean' else 'Total'} {metric}", fmt_num(shown)))
        kpis.append((f"Median {metric}", fmt_num(series.median())))
    if group:
        kpis.append((f"Distinct {group}", f"{filtered[group].nunique(dropna=True):,}"))

    return {
        "intro": " · ".join(bits),
        "form": {
            "metrics": numbers,
            "metric": metric or "",
            "aggregate": aggregate,
            "groups": categories,
            "group": group or "",
            "dates": dates,
            "date": date_col or "",
            "interval": freq,
            "x_options": numbers,
            "y_options": numbers,
            "x": x_name or "",
            "y": y_name or "",
            "colors": categories,
            "color": color or "",
            "filters": filter_ui,
            "date_form": date_form,
        },
        "filtered": filtered,
        "filters_on": filters_on,
        "metric": metric,
        "group": group,
        "how": how,
        "date_col": date_col,
        "freq": freq,
        "color": color,
        "x_name": x_name,
        "y_name": y_name,
        "kpis": kpis,
        "roles": roles,
        "working": working,
        "query_string": request.query_string.decode(),
        "empty": filtered.empty,
    }


def figure_html(fig) -> str | None:
    if fig is None:
        return None
    return fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"responsive": True, "displayModeBar": False},
    )


def table_html(frame: pd.DataFrame | None, limit: int | None = None) -> str | None:
    if frame is None or frame.empty:
        return None
    view = frame.copy() if limit is None else frame.head(limit).copy()
    for column in view.columns:
        if pd.api.types.is_datetime64_any_dtype(view[column]):
            view[column] = view[column].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].round(2)
    return view.to_html(index=False, classes="grid", border=0, na_rep="—")


def _chart_bundle(model: dict) -> dict:
    filtered = model["filtered"]
    metric = model["metric"]
    group = model["group"]
    how = model["how"]
    date_col = model["date_col"]
    bundle = {
        "trend": None,
        "trend_note": None,
        "trend_empty": "Mark a number column on the Load page to draw a trend.",
        "breakdown": None,
        "breakdown_note": None,
        "breakdown_empty": "Mark a number column on the Load page to see a breakdown.",
        "table": table_html(filtered, 20),
        "table_note": None,
    }
    if len(filtered) > 20:
        bundle["table_note"] = (
            f"Showing the first 20 of {len(filtered):,} rows. The download includes every filtered row."
        )
    if not metric:
        return bundle
    bundle["trend_empty"] = "Mark a date column on the Load page to draw a trend."
    bundle["breakdown_empty"] = "Choose a category in Group by to see a breakdown."
    if date_col:
        rule = auto_rule(filtered[date_col]) if model["freq"] == "Auto" else RULES[model["freq"]]
        bundle["trend"] = figure_html(trend_figure(filtered, date_col, metric, group, how, rule))
        bundle["trend_empty"] = "This date and metric have no overlapping values in the current rows."
    if group:
        figure, group_count = breakdown_figure(filtered, group, metric, how)
        bundle["breakdown"] = figure_html(figure)
        if group_count > 15:
            label = "highest averages" if how == "mean" else "largest groups"
            bundle["breakdown_note"] = f"Showing the 15 {label} of {group_count}."
        bundle["breakdown_empty"] = "This group and metric have no values in the current rows."
    return bundle


@app.get("/")
def home():
    return render_template("home.html")


@app.get("/load")
def load_page():
    data = get_data()
    if data is None:
        return render_template("load.html", data=None)
    raw = data["raw"]
    working = data["working"]
    quality = [
        ("Rows", f"{len(raw):,}"),
        ("Columns", f"{raw.shape[1]}"),
        ("Missing cells", f"{int(raw.isna().sum().sum()):,}"),
        ("Duplicate rows", f"{int(raw.duplicated().sum()):,}"),
    ]
    note_bits = [working.profile, f"{len(working.frame):,} prepared rows"]
    if working.value_note:
        note_bits.append(working.value_note)
    return render_template(
        "load.html",
        data=data,
        quality=quality,
        columns=data["profile"].to_dict("records"),
        roles=ROLES,
        excluded=data["excluded"],
        raw_table=table_html(raw, 15),
        prepared_table=table_html(working.frame, 12),
        prepared_note=" · ".join(note_bits),
    )


@app.post("/load")
def update_columns():
    data = get_data()
    if data is None:
        return redirect(url_for("load_page"))
    raw = data["raw"]
    edited = data["profile"].copy()
    for index, column in enumerate(raw.columns):
        use_name = request.form.get(f"use_name_{index}", column).strip() or column
        role = request.form.get(f"role_{index}", "text")
        edited.loc[edited["column"] == column, "use_name"] = use_name
        edited.loc[edited["column"] == column, "role"] = role
    excluded = request.form.getlist("exclude")
    try:
        working = build_working(raw, edited, excluded)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("load_page"))
    data["profile"] = edited
    data["working"] = working
    data["excluded"] = excluded
    session.pop("view_query", None)
    flash("Columns saved. Dashboard and Summary now use this setup.")
    return redirect(url_for("load_page"))


@app.post("/upload")
def upload():
    uploaded = request.files.get("csv")
    if uploaded is None or not uploaded.filename:
        flash("Choose a CSV file.")
        return redirect(request.referrer or url_for("home"))
    if not uploaded.filename.lower().endswith(".csv"):
        flash("Use a .csv file.")
        return redirect(request.referrer or url_for("home"))
    try:
        frame = read_table(uploaded)
        store_frame(frame, uploaded.filename)
    except Exception as exc:
        flash(f"Could not load that file. {exc}")
        return redirect(request.referrer or url_for("home"))
    return redirect(url_for("dashboard"))


@app.post("/sample/<kind>")
def use_sample(kind: str):
    sample = SAMPLES.get(kind)
    if sample is None:
        abort(404)
    source, path = sample
    try:
        store_frame(read_table(path), source)
    except Exception as exc:
        flash(f"Could not open that sample. {exc}")
        return redirect(url_for("home"))
    return redirect(url_for("dashboard"))


@app.get("/dashboard")
def dashboard():
    data = get_data()
    if data is None:
        return render_template("need_data.html", page="Dashboard")
    if request.args.get("ready") != "1":
        return redirect("/dashboard?" + default_query(data["working"]))
    session["view_query"] = request.query_string.decode()
    model = build_page_model(data, request.args)
    if model["empty"]:
        return render_template("dashboard.html", **model)
    model.update(_chart_bundle(model))
    return render_template("dashboard.html", **model)


@app.get("/summary")
def summary_page():
    data = get_data()
    if data is None:
        return render_template("need_data.html", page="Summary")
    if request.args.get("ready") != "1":
        saved = session.get("view_query") or default_query(data["working"])
        return redirect("/summary?" + saved)
    model = build_page_model(data, request.args)
    working = model["working"]
    report = build_summary(
        model["filtered"],
        working.roles,
        profile=working.profile,
        value_note=working.value_note,
        value_column=working.value_column,
        source_rows=len(working.frame),
        filters_on=model["filters_on"],
        metric=model["metric"],
        group=model["group"],
        how=model["how"],
        date_col=model["date_col"],
    )
    return render_template(
        "summary.html",
        filter_note=report.filter_note,
        overview=report.overview,
        highlights=report.highlights,
        health=report.health,
        relationships=report.relationships,
        next_looks=report.next_looks,
        snapshot=report.snapshot,
        top_table=table_html(report.top_table),
        outlier_table=table_html(report.outlier_table),
        missing_table=table_html(report.missing_table),
        corr_table=table_html(report.corr_table),
        numeric_profile=table_html(report.numeric_profile),
        category_profile=table_html(report.category_profile),
        query_string=request.query_string.decode(),
    )


@app.get("/download")
def download():
    data = get_data()
    if data is None:
        abort(404)
    if request.args.get("ready") == "1":
        args = request.args
    else:
        args = ImmutableMultiDict(parse_qsl(session.get("view_query", "")))
    model = build_page_model(data, args)
    payload = model["filtered"].to_csv(index=False).encode("utf-8")
    return Response(
        payload,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=filtered.csv"},
    )


@app.get("/plotly.js")
def plotly_js():
    script = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
    return send_file(script, mimetype="text/javascript")


@app.errorhandler(413)
def too_large(_exc):
    flash("That file is larger than 32 MB.")
    return redirect(url_for("load_page"))


def main() -> None:
    Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:8080")).start()
    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
