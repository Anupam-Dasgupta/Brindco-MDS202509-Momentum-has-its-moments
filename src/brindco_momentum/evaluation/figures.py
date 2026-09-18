"""Five compact, dependency-light PNG figures for the development evaluation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1800, 1040
LEFT, TOP, RIGHT, BOTTOM = 145, 215, 1660, 840
INK = "#17243A"
MUTED = "#66758A"
GRID = "#DFE6EF"
BG = "#F6F8FB"
COLORS = {"MOM": "#DB704A", "VM": "#187C85", "FIX": "#7359B2",
          "FIXVOL": "#D39B34", "NIFTY 500 TRI": "#71849B"}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (["C:/Windows/Fonts/segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else
             ["C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((44, 42, WIDTH - 44, HEIGHT - 42), radius=26, fill="white")
    draw.text((LEFT, 82), title, font=font(47, True), fill=INK)
    draw.text((LEFT, 149), subtitle, font=font(24), fill=MUTED)
    return image, draw


def axes(draw: ImageDraw.ImageDraw, low: float, high: float, years: list[str],
         y_label, year_dates: pd.Series) -> tuple[callable, callable]:
    if high <= low:
        high = low + 1
    for fraction in np.linspace(0, 1, 6):
        y = round(BOTTOM - fraction * (BOTTOM - TOP))
        draw.line((LEFT, y, RIGHT, y), fill=GRID, width=2)
        label = y_label(low + fraction * (high - low))
        draw.text((LEFT - 20, y), label, font=font(21), fill=MUTED, anchor="rm")
    dates = pd.to_datetime(year_dates)
    first, last = dates.iloc[0], dates.iloc[-1]
    def x_for_date(day) -> float:
        return LEFT + (pd.Timestamp(day) - first).days / (last - first).days * (RIGHT - LEFT)
    for year in years:
        day = pd.Timestamp(f"{year}-01-01")
        x = round(x_for_date(day))
        if LEFT < x < RIGHT:
            draw.line((x, TOP, x, BOTTOM), fill="#EFF2F6", width=2)
            draw.text((x, BOTTOM + 26), year, font=font(21), fill=MUTED, anchor="mt")
    return x_for_date, lambda value: BOTTOM - (value - low) / (high - low) * (BOTTOM - TOP)


def legend(draw: ImageDraw.ImageDraw, labels: list[str], y: int = 925) -> None:
    x = LEFT
    for label in labels:
        draw.line((x, y + 12, x + 39, y + 12), fill=COLORS[label], width=7)
        draw.text((x + 52, y), label, font=font(23, True), fill=INK)
        x += 52 + int(draw.textlength(label, font=font(23, True))) + 57


def plot_line(draw: ImageDraw.ImageDraw, dates: pd.Series, values,
              x_for_date, y_for_value, color: str, width: int = 5) -> None:
    points = [(round(x_for_date(day)), round(y_for_value(value)))
              for day, value in zip(dates, values)]
    draw.line(points, fill=color, width=width, joint="curve")


def make_figures(folder: Path, daily: pd.DataFrame, summary: pd.DataFrame,
                 tri: pd.DataFrame, overlay: pd.DataFrame, costs: pd.DataFrame) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    years = [str(year) for year in range(2016, 2024)]
    ordered = {name: daily.loc[daily.strategy.eq(name)].sort_values("date")
               for name in ("MOM", "VM", "FIX", "FIXVOL")}
    dates = ordered["MOM"].date.reset_index(drop=True)
    initial = float(summary.start_nav.iloc[0])

    image, draw = canvas("Cumulative wealth", "Development period · after-cost, after-tax accounts; published TRI for context")
    series = {name: frame.after_tax_nav.to_numpy() / initial for name, frame in ordered.items()}
    series["NIFTY 500 TRI"] = tri.tri_wealth_from_development_anchor.to_numpy() / initial
    high = np.ceil(max(float(np.max(values)) for values in series.values()) * 1.08 * 2) / 2
    low = min(0.0, np.floor(min(float(np.min(values)) for values in series.values()) * 2) / 2)
    x, y = axes(draw, low, high, years, lambda value: f"{value:.1f}×", dates)
    for name in ("NIFTY 500 TRI", "FIX", "FIXVOL", "MOM", "VM"):
        plot_line(draw, dates, series[name], x, y, COLORS[name], 4 if name == "NIFTY 500 TRI" else 5)
    legend(draw, ["MOM", "VM", "FIX", "FIXVOL", "NIFTY 500 TRI"])
    image.save(folder / "cumulative_wealth.png")

    image, draw = canvas("Drawdown comparison", "Frozen executable accounts · daily peak-to-trough losses")
    drawdowns = {}
    for name in ("MOM", "VM"):
        values = ordered[name].after_tax_nav.to_numpy()
        drawdowns[name] = values / np.maximum.accumulate(np.r_[initial, values])[1:] - 1
    low = np.floor(min(float(np.min(values)) for values in drawdowns.values()) * 1.12 * 10) / 10
    x, y = axes(draw, low, 0, years, lambda value: f"{value:.0%}", dates)
    for name in ("MOM", "VM"):
        plot_line(draw, dates, drawdowns[name], x, y, COLORS[name])
    legend(draw, ["MOM", "VM"])
    image.save(folder / "drawdown_mom_vm.png")

    image, draw = canvas("VM target equity exposure", "Frozen monthly 12% volatility-target overlay · 96 development months")
    months = pd.to_datetime(overlay.holding_month.astype(str) + "-01")
    x, y = axes(draw, 0, 1, years, lambda value: f"{value:.0%}", dates)
    points = []
    for i, (day, value) in enumerate(zip(months, overlay.exposure)):
        xx = max(LEFT, min(RIGHT, round(x(day))))
        yy = round(y(value))
        if i:
            points.append((xx, points[-1][1]))
        points.append((xx, yy))
    points.append((RIGHT, points[-1][1]))
    draw.line(points, fill=COLORS["VM"], width=6, joint="curve")
    draw.text((LEFT, 917), "Target exposure is fixed before the holding month; realised exposure can drift.",
              font=font(24), fill=MUTED)
    image.save(folder / "vm_target_exposure.png")

    image, draw = canvas("Return and risk", "Frozen after-cost, after-tax accounts · Sharpe uses 0% cash and 252 sessions")
    xmin = max(0, float(summary.annualised_volatility.min()) * .85)
    xmax = float(summary.annualised_volatility.max()) * 1.17
    ymin = min(0, float(summary.cagr.min()) - .03)
    ymax = max(.03, float(summary.cagr.max()) + .04)
    for fraction in np.linspace(0, 1, 6):
        xx = LEFT + fraction * (RIGHT - LEFT)
        yy = BOTTOM - fraction * (BOTTOM - TOP)
        draw.line((round(xx), TOP, round(xx), BOTTOM), fill=GRID, width=2)
        draw.line((LEFT, round(yy), RIGHT, round(yy)), fill=GRID, width=2)
        draw.text((round(xx), BOTTOM + 25), f"{xmin + fraction * (xmax - xmin):.0%}",
                  font=font(21), fill=MUTED, anchor="mt")
        draw.text((LEFT - 17, round(yy)), f"{ymin + fraction * (ymax - ymin):.0%}",
                  font=font(21), fill=MUTED, anchor="rm")
    for row in summary.itertuples():
        xx = round(LEFT + (row.annualised_volatility - xmin) / (xmax - xmin) * (RIGHT - LEFT))
        yy = round(BOTTOM - (row.cagr - ymin) / (ymax - ymin) * (BOTTOM - TOP))
        draw.ellipse((xx - 13, yy - 13, xx + 13, yy + 13), fill=COLORS[row.strategy],
                     outline="white", width=4)
        label_y = yy + 18 if row.strategy == "FIX" else yy - 25
        draw.text((xx + 21, label_y), f"{row.strategy} · Sharpe {row.sharpe_0pct_cash:.2f}",
                  font=font(24, True), fill=COLORS[row.strategy])
    draw.text(((LEFT + RIGHT) / 2, 926), "Annualised volatility", font=font(24), fill=MUTED, anchor="mm")
    draw.text((LEFT, 185), "CAGR", font=font(22), fill=MUTED)
    image.save(folder / "risk_return.png")

    image, draw = canvas("Implementation and tax drag", "Annualised CAGR-point drag · matched executed-share paths")
    top = 252
    max_value = float(costs[["annualised_implementation_cost_drag", "annualised_tax_drag"]].sum(axis=1).max())
    scale = (RIGHT - LEFT - 270) / max(max_value * 1.18, .01)
    draw.text((LEFT, 199), "Cost", font=font(20, True), fill=COLORS["VM"])
    draw.text((LEFT + 110, 199), "Tax", font=font(20, True), fill=COLORS["MOM"])
    for i, row in enumerate(costs.itertuples()):
        yy = top + i * 140
        draw.text((LEFT, yy + 17), row.strategy, font=font(29, True), fill=INK)
        x0 = LEFT + 185
        w_cost = round(row.annualised_implementation_cost_drag * scale)
        w_tax = round(row.annualised_tax_drag * scale)
        draw.rounded_rectangle((x0, yy, x0 + max(1, w_cost), yy + 27), radius=8, fill=COLORS["VM"])
        draw.rounded_rectangle((x0, yy + 43, x0 + max(1, w_tax), yy + 70), radius=8, fill=COLORS["MOM"])
        draw.text((x0 + w_cost + 14, yy - 2), f"{row.annualised_implementation_cost_drag:.2%}",
                  font=font(22), fill=MUTED)
        draw.text((x0 + w_tax + 14, yy + 42), f"{row.annualised_tax_drag:.2%}",
                  font=font(22), fill=MUTED)
        if i < 3:
            draw.line((LEFT, yy + 104, RIGHT, yy + 104), fill=GRID, width=2)
    draw.text((LEFT, 904), "Fee + participation impact and tax are separated; execution-path differences remain outside these bars.",
              font=font(21), fill=MUTED)
    image.save(folder / "cost_tax_drag.png")
