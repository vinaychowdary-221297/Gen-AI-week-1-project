"""Column inference, preparation, and local summaries for CSV Studio."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
from pandas.api.types import (
    DatetimeTZDtype,
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

ROLES = ("number", "date", "category", "text")
QTY_ORDER = ("quantity", "qty", "units", "on_hand", "stock", "shares")
PRICE_ORDER = ("unit_price", "price", "close", "last_price")
VALUE_NAMES = {"line_value", "position_value", "line_value_calc", "position_value_calc"}
GROUP_NAMES = {
    "category",
    "sector",
    "warehouse",
    "region",
    "department",
    "type",
    "segment",
    "industry",
}
DATE_HINTS = ("date", "time", "timestamp", "restock", "as_of", "day", "month")
ID_NAMES = {
    "sku",
    "id",
    "code",
    "ticker",
    "symbol",
    "asin",
    "upc",
    "isin",
    "zip",
    "phone",
    "postal",
    "postal_code",
}
LABEL_HINTS = ("product", "name", "item", "title", "ticker", "sku", "symbol", "description")
MEAN_HINTS = ("price", "rate", "percent", "pct", "avg", "average", "ratio", "yield", "cost_basis", "close")
FLAG_VALUES = {"yes", "no", "y", "n", "true", "false", "t", "f"}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def is_identifier(name: str) -> bool:
    key = normalize(name)
    return key in ID_NAMES or key == "id" or key.endswith("_id")


def clean_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.copy()
    renamed.columns = [str(column).strip() or "column" for column in renamed.columns]
    unnamed = [
        column
        for column in renamed.columns
        if column.startswith("Unnamed") and renamed[column].isna().all()
    ]
    if unnamed:
        renamed = renamed.drop(columns=unnamed)
    seen: dict[str, int] = {}
    unique: list[str] = []
    for column in renamed.columns:
        count = seen.get(column, 0)
        seen[column] = count + 1
        unique.append(column if count == 0 else f"{column}_{count + 1}")
    renamed.columns = unique
    if renamed.shape[1] == 0:
        raise ValueError("No columns found. Include a header row.")
    return renamed


def read_table(source) -> pd.DataFrame:
    """Read a CSV from a path or file object, trying common encodings and delimiters."""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        for separator in (None, ","):
            if hasattr(source, "seek"):
                source.seek(0)
            kwargs: dict = {"encoding": encoding}
            if separator is None:
                kwargs["sep"] = None
                kwargs["engine"] = "python"
            try:
                frame = pd.read_csv(source, **kwargs)
            except UnicodeDecodeError as exc:
                last_error = exc
                break
            except pd.errors.EmptyDataError as exc:
                raise ValueError("This file has no rows or header.") from exc
            except Exception as exc:
                last_error = exc
                continue
            if frame.shape[1] == 0:
                continue
            return clean_columns(frame)
    raise ValueError(
        "Could not read this file as CSV. Use a header row and a comma, tab, or similar delimiter."
    ) from last_error


def _numeric_series(series: pd.Series) -> pd.Series:
    if is_numeric_dtype(series) and not is_bool_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip()
    text = text.str.replace(r"[\$%,]", "", regex=True)
    text = text.str.replace(r"^\((.+)\)$", r"-\1", regex=True)
    return pd.to_numeric(text, errors="coerce")


def _looks_like_dates(name: str, series: pd.Series) -> bool:
    filled = int(series.notna().sum())
    if filled == 0:
        return False
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        parsed = pd.to_datetime(series, errors="coerce")
    if float(parsed.notna().sum() / filled) < 0.8:
        return False
    if any(hint in normalize(name) for hint in DATE_HINTS):
        return True
    text = series.dropna().astype("string")
    patterned = text.str.contains(
        r"\d{4}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}",
        regex=True,
        na=False,
    )
    return float(patterned.mean()) >= 0.8


def infer_role(name: str, series: pd.Series) -> str:
    if int(series.notna().sum()) == 0:
        return "text"
    if is_bool_dtype(series):
        return "category"
    if is_datetime64_any_dtype(series):
        return "date"
    distinct = int(series.nunique(dropna=True))
    if is_numeric_dtype(series):
        if is_identifier(name) and distinct > 20:
            return "text"
        return "number"

    flags = set(series.dropna().astype(str).str.strip().str.lower().unique())
    if flags and flags <= FLAG_VALUES:
        return "category"
    if _looks_like_dates(name, series):
        return "date"

    parsed = _numeric_series(series)
    filled = int(series.notna().sum())
    if filled and float(parsed.notna().sum() / filled) >= 0.85:
        if is_identifier(name) and distinct > 20:
            return "text"
        return "number"

    if distinct <= 1:
        return "category"
    if is_identifier(name) and distinct > 15:
        return "text"
    # Nearly unique values are labels, even in a short file.
    if filled and distinct / filled >= 0.8 and distinct > 6:
        return "text"
    if distinct <= 25 or (distinct <= 40 and distinct / filled <= 0.3):
        return "category"
    return "text"


def infer_roles(frame: pd.DataFrame) -> dict[str, str]:
    return {column: infer_role(column, frame[column]) for column in frame.columns}


def profile_table(frame: pd.DataFrame) -> pd.DataFrame:
    roles = infer_roles(frame)
    rows = []
    for column in frame.columns:
        series = frame[column]
        sample = series.dropna()
        example = ""
        if not sample.empty:
            example = str(sample.iloc[0])
            if len(example) > 48:
                example = example[:45] + "..."
        rows.append(
            {
                "column": column,
                "use_name": column,
                "role": roles[column],
                "missing": int(series.isna().sum()),
                "distinct": int(series.nunique(dropna=True)),
                "example": example,
            }
        )
    return pd.DataFrame(rows)


def _cast_series(series: pd.Series, role: str) -> pd.Series:
    if role == "number":
        return _numeric_series(series)
    if role == "date":
        if is_datetime64_any_dtype(series):
            parsed = series
        else:
            try:
                parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            except (TypeError, ValueError):
                parsed = pd.to_datetime(series, errors="coerce")
        if isinstance(parsed.dtype, DatetimeTZDtype):
            parsed = parsed.dt.tz_convert(None)
        return parsed
    return series.astype("string")


def pick_column(columns: list[str], order: tuple[str, ...]) -> str | None:
    lookup = {normalize(column): column for column in columns}
    for name in order:
        if name in lookup:
            return lookup[name]
    return None


def guess_profile(columns: list[str]) -> str:
    names = {normalize(column) for column in columns}
    if names & {"ticker", "symbol"}:
        return "Portfolio"
    if names & {"sku", "asin", "upc", "warehouse"}:
        return "Inventory"
    return "General table"


def _add_value_column(
    frame: pd.DataFrame, roles: dict[str, str]
) -> tuple[pd.DataFrame, dict[str, str], str | None, str | None]:
    numbers = [column for column, role in roles.items() if role == "number"]
    quantity = pick_column(numbers, QTY_ORDER)
    price = pick_column(numbers, PRICE_ORDER)
    if not quantity or not price or quantity == price:
        return frame, roles, None, None
    name = "position_value" if normalize(quantity) == "shares" else "line_value"
    if name in frame.columns:
        name = f"{name}_calc"
    prepared = frame.copy()
    prepared[name] = prepared[quantity] * prepared[price]
    return prepared, {**roles, name: "number"}, f"{name} = {quantity} × {price}", name


@dataclass
class WorkingSet:
    frame: pd.DataFrame
    roles: dict[str, str]
    value_note: str | None
    value_column: str | None
    profile: str


def build_working(raw: pd.DataFrame, profile: pd.DataFrame, excluded: list[str]) -> WorkingSet:
    excluded_names = set(excluded)
    kept = [column for column in raw.columns if column not in excluded_names]
    if not kept:
        raise ValueError("Keep at least one column.")

    rename: dict[str, str] = {}
    roles: dict[str, str] = {}
    for column in kept:
        matches = profile.loc[profile["column"] == column]
        if matches.empty:
            new_name = column
            role = infer_role(column, raw[column])
        else:
            row = matches.iloc[0]
            raw_name = "" if pd.isna(row["use_name"]) else str(row["use_name"]).strip()
            new_name = raw_name or column
            role = "" if pd.isna(row["role"]) else str(row["role"]).strip().lower()
            if role not in ROLES:
                role = infer_role(column, raw[column])
        rename[column] = new_name
        roles[new_name] = role

    if len(set(rename.values())) != len(rename):
        raise ValueError("Two columns share the same name. Rename one on the Load tab.")

    renamed = raw.loc[:, kept].copy().rename(columns=rename)
    casted = pd.DataFrame(
        {name: _cast_series(renamed[name], roles[name]) for name in renamed.columns}
    )
    casted.index = renamed.index
    prepared, roles, note, value_column = _add_value_column(casted, roles)
    return WorkingSet(
        frame=prepared,
        roles=roles,
        value_note=note,
        value_column=value_column,
        profile=guess_profile(kept),
    )


def choose_default_metric(roles: dict[str, str]) -> str | None:
    numbers = [column for column, role in roles.items() if role == "number"]
    preferred = (
        "position_value",
        "line_value",
        "position_value_calc",
        "line_value_calc",
        *QTY_ORDER,
        *PRICE_ORDER,
    )
    return pick_column(numbers, preferred) or (numbers[0] if numbers else None)


def choose_default_group(roles: dict[str, str]) -> str | None:
    categories = [column for column, role in roles.items() if role == "category"]
    found = pick_column(
        categories,
        (
            "category",
            "sector",
            "warehouse",
            "region",
            "department",
            "type",
            "segment",
            "industry",
        ),
    )
    return found or (categories[0] if categories else None)


def choose_default_date(frame: pd.DataFrame, roles: dict[str, str]) -> str | None:
    dates = [
        column
        for column, role in roles.items()
        if role == "date" and column in frame.columns and frame[column].notna().any()
    ]
    hinted = [column for column in dates if any(hint in normalize(column) for hint in DATE_HINTS)]
    if hinted:
        return hinted[0]
    return dates[0] if dates else None


def default_agg(metric: str) -> str:
    name = normalize(metric)
    if any(hint in name for hint in MEAN_HINTS):
        return "mean"
    return "sum"


def default_axes(roles: dict[str, str]) -> tuple[str | None, str | None]:
    numbers = [column for column, role in roles.items() if role == "number"]
    base = [column for column in numbers if column not in VALUE_NAMES]
    pool = base if len(base) >= 2 else numbers
    quantity = pick_column(pool, QTY_ORDER)
    price = pick_column(pool, PRICE_ORDER)
    if quantity and price and quantity != price:
        return quantity, price
    if len(pool) >= 2:
        return pool[0], pool[1]
    return None, None


def category_filter_columns(frame: pd.DataFrame, roles: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    for column, role in roles.items():
        if role != "category" or column not in frame.columns:
            continue
        labels = frame[column].astype("string").fillna("(blank)")
        distinct = int(labels.nunique())
        if 2 <= distinct <= 20:
            candidates.append(column)

    def sort_key(column: str) -> tuple[int, int, str]:
        rank = 0 if normalize(column) in GROUP_NAMES else 1
        distinct = int(frame[column].astype("string").fillna("(blank)").nunique())
        return rank, distinct, column

    candidates.sort(key=sort_key)
    preferred = [column for column in candidates if normalize(column) in GROUP_NAMES]
    return (preferred or candidates)[:3]


def filter_frame(
    frame: pd.DataFrame,
    *,
    date_col: str | None,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    category_filters: dict[str, list[str]],
) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    if date_col and start is not None and end is not None and date_col in frame.columns:
        mask &= frame[date_col].between(start, end)
    for column, selected in category_filters.items():
        labels = frame[column].astype("string").fillna("(blank)")
        mask &= labels.isin(selected)
    return frame.loc[mask].copy()


def aggregate_groups(frame: pd.DataFrame, group: str, metric: str, how: str) -> pd.Series:
    labels = frame[group].astype("string").fillna("(blank)")
    grouped = frame.assign(**{group: labels}).groupby(group, dropna=False)[metric]
    if how == "mean":
        result = grouped.mean()
    else:
        result = grouped.sum(min_count=1)
    return result.dropna().sort_values(ascending=False)


def auto_rule(dates: pd.Series) -> str:
    clean = dates.dropna().sort_values().drop_duplicates()
    if len(clean) <= 1:
        return "D"
    gaps = clean.diff().dt.days.dropna()
    median_gap = float(gaps.median()) if not gaps.empty else 0
    if median_gap >= 20:
        return "M"
    if median_gap >= 5:
        return "W"
    return "D"


def floor_period(series: pd.Series, rule: str) -> pd.Series:
    if rule == "D":
        return series.dt.floor("D")
    if rule == "W":
        return series.dt.to_period("W-SUN").dt.to_timestamp()
    return series.dt.to_period("M").dt.to_timestamp()


def fmt_num(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if abs(number) >= 10:
        return f"{number:,.1f}"
    return f"{number:,.2f}"


def fmt_date(value) -> str:
    return pd.Timestamp(value).strftime("%d %b %Y")


def _fmt_pct(value: float) -> str:
    if value != 0 and abs(value) < 1:
        return "<1%"
    return f"{value:.0f}%"


def _label_column(frame: pd.DataFrame, roles: dict[str, str]) -> str:
    candidates = [
        column
        for column, role in roles.items()
        if role in {"text", "category", "date"} and column in frame.columns
    ]
    found = pick_column(candidates, LABEL_HINTS)
    return found or (candidates[0] if candidates else frame.columns[0])


def _role_mix(roles: dict[str, str]) -> str:
    labels = {
        "number": ("number column", "number columns"),
        "date": ("date column", "date columns"),
        "category": ("category column", "category columns"),
        "text": ("text column", "text columns"),
    }
    parts = []
    for role, (singular, plural) in labels.items():
        count = sum(1 for item in roles.values() if item == role)
        if count:
            parts.append(f"{count} {singular if count == 1 else plural}")
    return ", ".join(parts)


def _find_outliers(frame: pd.DataFrame, metric: str) -> pd.DataFrame:
    series = frame[metric].dropna()
    if len(series) < 8:
        return frame.iloc[0:0]
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    spread = q3 - q1
    if pd.isna(spread) or spread == 0:
        return frame.iloc[0:0]
    low = q1 - 1.5 * spread
    high = q3 + 1.5 * spread
    mask = frame[metric].notna() & ((frame[metric] < low) | (frame[metric] > high))
    return frame.loc[mask]


@dataclass
class SummaryReport:
    filter_note: str
    overview: str
    highlights: list[str]
    health: list[str]
    relationships: list[str]
    next_looks: list[str]
    snapshot: list[tuple[str, str]]
    top_table: pd.DataFrame | None
    outlier_table: pd.DataFrame | None
    missing_table: pd.DataFrame | None
    corr_table: pd.DataFrame | None
    numeric_profile: pd.DataFrame | None
    category_profile: pd.DataFrame | None


def build_summary(
    frame: pd.DataFrame,
    roles: dict[str, str],
    *,
    profile: str,
    value_note: str | None,
    value_column: str | None,
    source_rows: int,
    filters_on: bool,
    metric: str | None,
    group: str | None,
    how: str,
    date_col: str | None,
) -> SummaryReport:
    if filters_on:
        note = f"Based on {len(frame):,} of {source_rows:,} prepared rows after the dashboard filters."
    else:
        note = f"Based on all {len(frame):,} prepared rows."

    empty_overview = (
        "The current filters match no rows."
        if filters_on
        else "The prepared table has column names and no data rows."
    )
    empty = SummaryReport(
        filter_note=note,
        overview=empty_overview,
        highlights=[],
        health=[],
        relationships=[],
        next_looks=[],
        snapshot=[],
        top_table=None,
        outlier_table=None,
        missing_table=None,
        corr_table=None,
        numeric_profile=None,
        category_profile=None,
    )
    if frame.empty:
        return empty

    overview_parts = [
        f"This {profile.lower()} has {len(frame):,} rows and {frame.shape[1]} columns.",
        f"Column mix: {_role_mix(roles)}.",
    ]
    if value_note:
        overview_parts.append(f"Calculated column: {value_note}.")
    if date_col and date_col in frame.columns and frame[date_col].notna().any():
        span = frame[date_col].dropna()
        start, end = span.min(), span.max()
        if pd.Timestamp(start).normalize() == pd.Timestamp(end).normalize():
            overview_parts.append(f"{date_col} is a single day, {fmt_date(start)}.")
        else:
            overview_parts.append(f"{date_col} runs from {fmt_date(start)} to {fmt_date(end)}.")

    highlights: list[str] = []
    top_table = None
    outlier_table = None
    snapshot: list[tuple[str, str]] = [("Rows", f"{len(frame):,}")]

    if metric and metric in frame.columns and frame[metric].notna().any():
        series = frame[metric].dropna()
        if how == "mean":
            snapshot.append((f"Average {metric}", fmt_num(series.mean())))
        else:
            snapshot.append((f"Total {metric}", fmt_num(series.sum())))
        snapshot.append((f"Median {metric}", fmt_num(series.median())))
        label_col = _label_column(frame, roles)
        top_row = frame.loc[[series.idxmax()]].iloc[0]
        identifiers = [column for column in frame.columns if is_identifier(column)]
        detail_cols = []
        for column in (label_col, *identifiers):
            if column not in detail_cols and column != metric and column in top_row.index:
                detail_cols.append(column)
        detail = ", ".join(
            f"{column} {top_row[column] if pd.notna(top_row[column]) else '(blank)'}"
            for column in detail_cols[:2]
        )
        if detail:
            highlights.append(f"Highest {metric} row: {fmt_num(top_row[metric])} ({detail}).")
        else:
            highlights.append(f"Highest {metric} row: {fmt_num(top_row[metric])}.")

        if group and group in frame.columns:
            ranked = aggregate_groups(frame, group, metric, how)
            named = ranked[ranked.index.astype(str) != "(blank)"]
            ranked_for_story = named if len(named) >= 2 else ranked
            if len(ranked_for_story) >= 2:
                value_name = metric if metric != group else f"{metric} value"
                top_table = ranked.head(8).rename(value_name).reset_index()
                if how == "sum":
                    total = float(ranked.sum())
                    if total:
                        shares = (ranked.head(8) / total * 100).round(1)
                        top_table["share_pct"] = shares.values
                def shown(name: str) -> str:
                    return f"rows with no {group}" if str(name) == "(blank)" else str(name)

                leader, leader_value = ranked_for_story.index[0], ranked_for_story.iloc[0]
                if how == "sum" and float(ranked.sum()):
                    highlights.append(
                        f"Largest {group} by {metric}: {shown(leader)} at {fmt_num(leader_value)} "
                        f"({_fmt_pct(100 * float(leader_value) / float(ranked.sum()))})."
                    )
                else:
                    highlights.append(
                        f"Highest average {metric} is {shown(leader)} ({group}) at {fmt_num(leader_value)}."
                    )
                if len(ranked_for_story) >= 3:
                    trailer, trailer_value = ranked_for_story.index[-1], ranked_for_story.iloc[-1]
                    if how == "sum" and float(ranked.sum()):
                        highlights.append(
                            f"Smallest {group} by {metric}: {shown(trailer)} at {fmt_num(trailer_value)} "
                            f"({_fmt_pct(100 * float(trailer_value) / float(ranked.sum()))})."
                        )
                    else:
                        highlights.append(
                            f"Lowest average {metric} is {shown(trailer)} ({group}) at {fmt_num(trailer_value)}."
                        )
            snapshot.append((f"Distinct {group}", f"{frame[group].nunique(dropna=True):,}"))

        outliers = _find_outliers(frame, metric)
        if len(series) >= 8 and outliers.empty:
            highlights.append(f"{metric} stays inside the usual spread. No IQR outliers.")
        elif not outliers.empty:
            highlights.append(
                f"{metric} has {len(outliers)} outlier value{'s' if len(outliers) != 1 else ''} "
                "outside the usual spread."
            )
            show = []
            for column in (label_col, *identifiers, metric):
                if column in outliers.columns and column not in show:
                    show.append(column)
            ordered = outliers.assign(_rank=outliers[metric].abs()).sort_values(
                "_rank", ascending=False
            )
            outlier_table = ordered.loc[:, show].head(5)

    health: list[str] = []
    duplicates = int(frame.duplicated().sum())
    if duplicates == 0:
        health.append("No exact duplicate rows.")
    elif duplicates == 1:
        health.append("1 exact duplicate row.")
    else:
        health.append(f"{duplicates:,} exact duplicate rows.")

    missing_rows = []
    for column in frame.columns:
        missing = int(frame[column].isna().sum())
        if missing:
            percent = 100 * missing / len(frame)
            missing_rows.append(
                {"column": column, "missing": missing, "percent": round(percent, 1)}
            )
            health.append(f"{column} is missing {missing:,} value{'s' if missing != 1 else ''} ({percent:.0f}%).")
    if not missing_rows:
        health.append("No missing values.")
    missing_table = pd.DataFrame(missing_rows) if missing_rows else None

    for column, role in roles.items():
        if role not in {"category", "text"} or column not in frame.columns or len(frame) < 5:
            continue
        filled = frame[column].dropna()
        if filled.empty or filled.nunique() > 1:
            continue
        health.append(f"{column} has only one value: {filled.iloc[0]}.")

    relationships, corr_table = _relationships(frame, roles, value_column, value_note)
    next_looks = _next_looks(frame, roles, metric, group, date_col, value_column)

    numeric_profile = None
    number_cols = [column for column, role in roles.items() if role == "number" and column in frame.columns]
    if number_cols:
        described = frame[number_cols].describe().T
        described.index.name = "column"
        numeric_profile = described.reset_index()
        for column in numeric_profile.columns:
            if column != "column" and is_numeric_dtype(numeric_profile[column]):
                numeric_profile[column] = numeric_profile[column].round(2)

    category_rows = []
    for column, role in roles.items():
        if role != "category" or column not in frame.columns:
            continue
        labels = frame[column].astype("string").fillna("(blank)")
        counts = labels.value_counts()
        if counts.empty:
            continue
        category_rows.append(
            {
                "column": column,
                "distinct": int(frame[column].nunique(dropna=True)),
                "most_common": counts.index[0],
                "rows": int(counts.iloc[0]),
                "share_pct": round(100 * counts.iloc[0] / len(frame), 1),
            }
        )
    category_profile = pd.DataFrame(category_rows) if category_rows else None

    return SummaryReport(
        filter_note=note,
        overview=" ".join(overview_parts),
        highlights=highlights,
        health=health,
        relationships=relationships,
        next_looks=next_looks,
        snapshot=snapshot,
        top_table=top_table,
        outlier_table=outlier_table,
        missing_table=missing_table,
        corr_table=corr_table,
        numeric_profile=numeric_profile,
        category_profile=category_profile,
    )


def _relationships(
    frame: pd.DataFrame,
    roles: dict[str, str],
    value_column: str | None,
    value_note: str | None,
) -> tuple[list[str], pd.DataFrame | None]:
    lines: list[str] = []
    if value_note:
        lines.append(f"Left out of the correlations because it is calculated: {value_note}.")
    columns = [
        column
        for column, role in roles.items()
        if role == "number" and column in frame.columns and column != value_column
    ]
    numbers = frame[columns]
    if not numbers.empty:
        varied = [column for column in numbers.columns if numbers[column].nunique(dropna=True) > 1]
        numbers = numbers[varied]
    if numbers.shape[1] < 2:
        lines.append("At least two independent number columns are needed before a correlation shows up.")
        return lines, None

    matrix = numbers.corr(numeric_only=True)
    pairs = []
    names = list(matrix.columns)
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            score = matrix.loc[left, right]
            if pd.notna(score):
                pairs.append((abs(float(score)), float(score), left, right))
    pairs.sort(reverse=True)
    if not pairs:
        lines.append("These number columns do not overlap enough to compare.")
        return lines, None

    def phrase(score: float, left: str, right: str) -> str:
        shown = f"r = {score:.2f}"
        if score >= 0.7:
            return f"{left} and {right} move together ({shown})."
        if score >= 0.4:
            return f"{left} and {right} tend to move together ({shown})."
        if score >= 0.2:
            return f"{left} and {right} have a mild positive link ({shown})."
        if score <= -0.7:
            return f"{left} and {right} move in opposite directions ({shown})."
        if score <= -0.4:
            return f"{left} and {right} tend to move in opposite directions ({shown})."
        if score <= -0.2:
            return f"{left} and {right} have a mild negative link ({shown})."
        return f"{left} and {right} have little linear relationship ({shown})."

    notable = [item for item in pairs if item[0] >= 0.2][:3]
    chosen = notable or pairs[:1]
    if not notable:
        lines.append("Number columns move mostly on their own.")
    lines.extend(phrase(score, left, right) for _, score, left, right in chosen)
    corr_table = pd.DataFrame(
        [
            {"column_a": left, "column_b": right, "r": round(score, 2)}
            for _, score, left, right in pairs[:12]
        ]
    )
    return lines, corr_table


def _next_looks(
    frame: pd.DataFrame,
    roles: dict[str, str],
    metric: str | None,
    group: str | None,
    date_col: str | None,
    value_column: str | None,
) -> list[str]:
    looks: list[str] = []
    if metric and group:
        looks.append(f"On Dashboard, keep Breakdown on {metric} grouped by {group}.")
    if metric and date_col:
        looks.append(f"On Dashboard, plot {metric} across {date_col}.")
    numbers = [
        column
        for column, role in roles.items()
        if role == "number" and column != value_column
    ]
    quantity = pick_column(numbers, QTY_ORDER)
    price = pick_column(numbers, PRICE_ORDER)
    if quantity and price and quantity != price:
        color = f", colored by {group}" if group else ""
        looks.append(f"On Dashboard, scatter {quantity} against {price}{color}.")
    missing = []
    for column in frame.columns:
        count = int(frame[column].isna().sum())
        if count:
            missing.append((count, column))
    if missing:
        missing.sort(reverse=True)
        count, column = missing[0]
        looks.append(f"On Load, review {column}. It is missing {count:,} value{'s' if count != 1 else ''} in this view.")
    return looks[:4]
