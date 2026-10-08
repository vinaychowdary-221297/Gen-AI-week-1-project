"""Plotly figures for the dashboard page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from analysis import aggregate_groups, floor_period

COLORS = ["#0F6E6E", "#E07A3D", "#1F4E79", "#6B4C9A", "#2E7D4F", "#B4533A"]
SURFACE = "#ffffff"


def _style(fig, title: str):
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left"),
        template="plotly_white",
        height=400,
        margin=dict(l=8, r=8, t=56, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color="#1B2424", family="sans serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        colorway=COLORS,
    )
    fig.update_xaxes(gridcolor="#E1E4DE", zerolinecolor="#E1E4DE")
    fig.update_yaxes(gridcolor="#E1E4DE", zerolinecolor="#E1E4DE")
    return fig


def trend_figure(
    frame: pd.DataFrame,
    date_col: str,
    metric: str,
    group: str | None,
    how: str,
    rule: str,
):
    data = frame.dropna(subset=[date_col, metric]).copy()
    if data.empty:
        return None
    data["_period"] = floor_period(data[date_col], rule)
    agg_name = "mean" if how == "mean" else "sum"
    word = "Average" if how == "mean" else "Total"
    if group:
        data[group] = data[group].astype("string").fillna("(blank)")
        grouped = data.groupby(["_period", group], as_index=False)[metric].agg(agg_name)
        fig = px.line(
            grouped,
            x="_period",
            y=metric,
            color=group,
            markers=True,
            color_discrete_sequence=COLORS,
        )
    else:
        grouped = data.groupby("_period", as_index=False)[metric].agg(agg_name)
        fig = px.line(
            grouped,
            x="_period",
            y=metric,
            markers=True,
            color_discrete_sequence=COLORS,
        )
    fig.update_xaxes(title=date_col)
    fig.update_yaxes(title=metric)
    return _style(fig, f"{word} {metric} by {date_col}")


def breakdown_figure(frame: pd.DataFrame, group: str, metric: str, how: str):
    ranked = aggregate_groups(frame, group, metric, how)
    if ranked.empty:
        return None, 0
    shown = ranked.head(15)
    plot = shown.rename("_measure").reset_index()
    word = "Average" if how == "mean" else "Total"
    fig = px.bar(plot, x="_measure", y=group, orientation="h")
    fig.update_traces(marker_color=COLORS[0])
    fig.update_yaxes(title=group)
    fig.update_xaxes(title=metric)
    fig = _style(fig, f"{word} {metric} by {group}")
    fig.update_yaxes(categoryorder="total ascending")
    return fig, len(ranked)


def histogram_figure(frame: pd.DataFrame, metric: str):
    data = frame.dropna(subset=[metric])
    if data.empty:
        return None
    bins = min(40, max(8, int(len(data) ** 0.5)))
    fig = px.histogram(data, x=metric, nbins=bins)
    fig.update_traces(marker_color=COLORS[0])
    fig.update_xaxes(title=metric)
    fig.update_yaxes(title="Rows")
    return _style(fig, f"Distribution of {metric}")


def scatter_figure(
    frame: pd.DataFrame,
    x: str,
    y: str,
    color: str | None,
    hover: list[str],
):
    if x == y:
        return None
    columns = [x, y]
    data = frame.dropna(subset=columns).copy()
    if data.empty:
        return None
    hover_data = [column for column in hover if column in data.columns and column not in columns][:3]
    if color:
        data[color] = data[color].astype("string").fillna("(blank)")
    fig = px.scatter(
        data,
        x=x,
        y=y,
        color=color,
        hover_data=hover_data or None,
        color_discrete_sequence=COLORS,
    )
    fig.update_xaxes(title=x)
    fig.update_yaxes(title=y)
    return _style(fig, f"{y} vs {x}")
