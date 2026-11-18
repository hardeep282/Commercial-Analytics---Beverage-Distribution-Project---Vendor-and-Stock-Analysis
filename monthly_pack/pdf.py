

"""Step 6, piece 2 - the PDF pack for management.

Everything in it was already computed by steps 1-5; this file only lays it out.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from monthly_pack.kpis import money

INK = colors.HexColor("#1f2937")
ACCENT = colors.HexColor("#0e7490")
GRID = colors.HexColor("#d1d5db")
BAND = colors.HexColor("#f3f4f6")

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["BodyText"], fontSize=9.5, leading=13, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10.5, textColor=colors.HexColor("#4b5563"))
H1 = ParagraphStyle("h1", parent=STYLES["Title"], fontSize=18, textColor=INK, alignment=0, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=STYLES["Heading2"], fontSize=12.5, textColor=ACCENT, spaceBefore=10, spaceAfter=4)


def markdown_line(line: str) -> str:
    """One line of the memo's Markdown as safe text for a PDF paragraph: **bold** becomes bold."""
    text = escape(line.strip())
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def table(rows: list[list], widths: list[float], header: bool = True) -> Table:
    t = Table(rows, colWidths=[w * mm for w in widths], hAlign="LEFT")
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BAND), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def trend_chart(trend: pd.Series) -> Drawing:
    """Monthly revenue from January to the reporting month, in $M."""
    drawing = Drawing(170 * mm, 55 * mm)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 12 * mm, 8 * mm, 150 * mm, 42 * mm
    chart.data = [[round(v / 1e6, 2) for v in trend.values]]
    chart.categoryAxis.categoryNames = [calendar.month_abbr[m] for m in trend.index]
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labelTextFormat = "$%dM"
    chart.bars[0].fillColor = ACCENT
    chart.bars[0].strokeColor = None
    chart.categoryAxis.labels.fontSize = 7.5
    chart.valueAxis.labels.fontSize = 7.5
    drawing.add(chart)
    return drawing


def write_pdf(pack: dict, month: int, memo_text: str | None, path: Path) -> Path:
    """Lay out the pack: data quality, this month, full year, plays, memo, notes."""
    k = pack["kpis"]
    m, y, c = k["monthly"], k["yearly"], k["concentration"]
    name = calendar.month_name[month]
    story = [
        Paragraph(f"Monthly management pack · {name} 2024", H1),
        Paragraph(f"Beverage distribution, 126 vendors. Built {date.today():%d %b %Y} from SQL Server. "
                  f"Monthly figures use January to {name} only; profitability is full-year 2024.", SMALL),
    ]

    # Data quality first: the reader should know whether to trust the rest.
    results = pack["results"]
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "WARN", "FAIL")}
    story += [Paragraph("Data quality", H2),
              Paragraph(f"{counts['PASS']} checks passed, {counts['WARN']} warnings, {counts['FAIL']} failed. "
                        "Gate open: the figures below may be used.", BODY)]
    story += [Paragraph(f"Warning: {escape(r.detail)}", SMALL) for r in results if r.status == "WARN"]

    # This month.
    change = "n/a (first month)" if m["change"] is None else f"{m['change_pct']:+.1f}% ({money(m['change'])})"
    story += [
        Paragraph(f"{name} at a glance", H2),
        table([["Revenue", "vs previous month", "Year to date", "Rank so far"],
               [money(m["revenue"]), change, money(m["ytd_revenue"]),
                f"{m['rank_so_far']} of {m['months_so_far']}"]], [40, 50, 40, 40]),
        Spacer(1, 3 * mm),
        trend_chart(pack["trend"]),
        table([["Top vendors this month", "Revenue", "Share"]]
              + [[r.VendorName, money(r.Revenue), f"{r.SharePct:.1f}%"]
                 for r in k["top_vendors"].itertuples()], [95, 35, 25]),
        Spacer(1, 3 * mm),
    ]
    movers = pack["movers"]
    if movers.empty:
        story.append(Paragraph("No vendor moved by $10,000 or more against the previous month.", BODY))
    else:
        rows = [["Material movers (at least $10,000)", "Change", "Change %"]]
        for r in movers.itertuples():
            pct = "new" if pd.isna(r.ChangePct) else f"{r.ChangePct:+.1f}%"
            rows.append([r.VendorName, money(r.Change), pct])
        story.append(table(rows, [95, 35, 25]))
        if (movers["Change"] < 0).sum() == 0:
            story.append(Paragraph("No material falls this month.", SMALL))

    # Full year.
    story += [
        Paragraph("Full-year 2024 profitability", H2),
        table([["Revenue", "Gross margin", "Net margin", "Excise (tax)", "Top 10 vendors"],
               [money(y["revenue"]), f"{y['gross_margin_pct']:.1f}%", f"{y['net_margin_pct']:.1f}%",
                money(y["excise"]), f"{c['top_10_share_pct']:.1f}% of revenue"]], [33, 30, 30, 33, 45]),
        Spacer(1, 3 * mm),
        table([["SKU health (cleaned base)", "SKUs", "% of SKUs", "% of revenue"]]
              + [[r.HealthStatus, f"{r.SKUs:,}", f"{r.SKUsPct:.1f}%", f"{r.RevenuePct:.1f}%"]
                 for r in k["sku_health"].itertuples()], [70, 25, 30, 30]),
    ]

    # Plays.
    from monthly_pack.plays import rank_plays

    ranked = rank_plays(pack["plays"])
    rows = [["#", "Play", "Cautious", "Base", "Stretch", "Kind"]]
    for r in ranked.itertuples():
        values = ["", "", ""] if pd.isna(r.Base) else [money(r.Cautious), money(r.Base), money(r.Stretch)]
        rows.append([r.Priority, r.Play, *values, r.Kind])
    story += [Paragraph("Recommended plays", H2),
              Paragraph("Cash freed once and profit every year are different kinds of value and are not "
                        "added together. Scenario values rest on the assumptions shown.", SMALL),
              table(rows, [12, 38, 22, 22, 22, 54])]
    for p in pack["plays"]:
        story += [Spacer(1, 2 * mm), Paragraph(f"<b>{escape(p.name)}</b> · {escape(p.kind)} · owner: {escape(p.owner)}", BODY),
                  Paragraph(f"Problem: {escape(p.problem)}", SMALL),
                  Paragraph(f"Action: {escape(p.action)}", SMALL),
                  Paragraph(f"Assumptions: {escape(' '.join(p.assumptions))}", SMALL)]

    # Memo.
    story.append(Paragraph("Board memo", H2))
    if memo_text:
        story.append(Paragraph("Written by AI from the figures above; every number was checked against them.", SMALL))
        for line in memo_text.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                story.append(Paragraph(markdown_line(line), BODY))
    else:
        story.append(Paragraph("Not generated for this pack (run without --no-ai to include it).", BODY))

    story += [Paragraph("Notes", H2),
              Paragraph("Data: one year of historical sales (2024); the pack is built as of the chosen month. "
                        "Monthly revenue comes from the monthly table and differs from the yearly views by "
                        "about 0.1%; the data-quality check measures this gap every run. "
                        "Unsold stock = 2024 purchases minus 2024 sales (no year-end stock count).", SMALL)]

    path.parent.mkdir(exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm,
                      title=f"Monthly management pack {name} 2024").build(story)
    return path