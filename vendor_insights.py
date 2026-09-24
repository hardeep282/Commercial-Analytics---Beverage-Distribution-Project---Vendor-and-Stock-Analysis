import os
import pyodbc
import anthropic
from dotenv import load_dotenv

load_dotenv()  # reads variables from the .env file in this folder

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY not found. Check your .env file.")

client = anthropic.Anthropic(api_key=api_key)


conn = pyodbc.connect(
    "DRIVER={SQL Server};"
    "SERVER=.\\SQLEXPRESS;"
    "DATABASE=Vendor_sales;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()


def pct(part, whole):
    """Percentage of whole, safe against division by zero."""
    return float(part) * 100.0 / float(whole) if whole else 0.0


# ---------------------------------------------------------------
# 1. Portfolio totals (all vendors) from vw_ProfitLeakage
# ---------------------------------------------------------------
cursor.execute("""
    SELECT
        COUNT(*)                     AS Vendors,
        SUM(TotalRevenue)            AS Revenue,
        SUM(TotalGrossProfit)        AS GrossProfit,
        SUM(NetProfitAfterAllCosts)  AS NetProfit,
        SUM(ExciseLeakage)           AS Excise,
        SUM(FreightLeakage)          AS Freight,
        SUM(LossMakingLeakage)       AS LossMaking,
        SUM(ControllableLeakage)     AS Controllable,
        SUM(TotalLeakageAmount)      AS TotalLeakage
    FROM dbo.vw_ProfitLeakage
""")
t = cursor.fetchone()
vendors, revenue, gross, net, excise, freight, lossmaking, controllable, total_leak = t

portfolio_data = (
    f"Vendors: {vendors}\n"
    f"Total revenue: ${revenue:,.0f}\n"
    f"Gross profit: ${gross:,.0f} ({pct(gross, revenue):.1f}% blended gross margin)\n"
    f"Net profit after COGS, freight and excise: ${net:,.0f} ({pct(net, revenue):.1f}% of revenue)\n"
    f"Total cost leakage: ${total_leak:,.0f} ({pct(total_leak, revenue):.2f}% of revenue)\n"
    f"  Non-controllable (excise tax, statutory): ${excise:,.0f} ({pct(excise, revenue):.2f}% of revenue)\n"
    f"  Controllable total: ${controllable:,.0f} ({pct(controllable, revenue):.2f}% of revenue)\n"
    f"    Freight: ${freight:,.0f}\n"
    f"    Losses on loss-making SKUs: ${lossmaking:,.0f}\n"
)


# ---------------------------------------------------------------
# 2. Top 10 vendors by revenue from vw_VendorRevenueSummary
# ---------------------------------------------------------------
cursor.execute("""
    SELECT TOP 10
        VendorName,
        NumberofSKUs,
        TotalRevenue,
        TotalGrossProfit,
        BlendedMarginPct,   -- total gross profit / total revenue (not a simple average)
        RevenueSharePct
    FROM dbo.vw_VendorRevenueSummary
    ORDER BY TotalRevenue DESC
""")
revenue_rows = cursor.fetchall()

revenue_data = ""
for i, row in enumerate(revenue_rows, start=1):
    revenue_data += (
        f"Revenue rank {i}: {row[0]} | SKUs: {row[1]} | Revenue: ${row[2]:,.0f} | "
        f"Gross profit: ${row[3]:,.0f} | Blended margin: {row[4]:.1f}% | "
        f"Revenue share: {row[5]:.2f}%\n"
    )

portfolio_margin = pct(gross, revenue)
below = [(row[0], row[4]) for row in revenue_rows if float(row[4]) < portfolio_margin]
revenue_data += (
    f"\nTop 10 revenue vendors below the portfolio blended gross margin "
    f"({portfolio_margin:.1f}%): {len(below)} vendors: "
    + ", ".join(f"{name} ({m:.1f}%)" for name, m in below) + "\n"
)


# ---------------------------------------------------------------
# 3. Top 10 vendors by controllable leakage from vw_ProfitLeakage
# ---------------------------------------------------------------
cursor.execute("""
    SELECT TOP 10
        VendorName,
        TotalRevenue,
        TotalSKUs,
        LossMakingSKUs,
        FreightLeakage,
        LossMakingLeakage,
        ControllableLeakage,
        ControllableLeakagePct,
        ControllableLeakageSeverity
    FROM dbo.vw_ProfitLeakage
    ORDER BY ControllableLeakage DESC
""")
leakage_rows = cursor.fetchall()

leakage_data = ""
for i, row in enumerate(leakage_rows, start=1):
    leakage_data += (
        f"Controllable leakage rank {i}: {row[0]} | Revenue: ${row[1]:,.0f} | "
        f"SKUs: {row[2]} ({row[3]} loss-making) | "
        f"Freight: ${row[4]:,.0f} ({pct(row[4], row[1]):.2f}% of its revenue) | "
        f"Losses on loss-making SKUs: ${row[5]:,.0f} ({pct(row[5], row[1]):.2f}% of its revenue) | "
        f"Controllable leakage (freight + losses): ${row[6]:,.0f} ({row[7]:.2f}% of its revenue; "
        f"{pct(row[6], controllable):.1f}% of total controllable leakage) | "
        f"Severity: {row[8]}\n"
    )

conn.close()

print("PORTFOLIO\n" + portfolio_data)
print("TOP 10 BY REVENUE\n" + revenue_data)
print("TOP 10 BY CONTROLLABLE LEAKAGE\n" + leakage_data)


# ---------------------------------------------------------------
# 4. Ask Claude for an evidence-based summary
# ---------------------------------------------------------------
system_prompt = """You are a commercial analyst writing for the management team of a beverage distributor.

Rules:
1. Use only the figures in the data provided. Do not invent numbers, benchmarks, time periods, or facts about vendors, brands or markets.
2. Every finding and every recommendation must cite the specific figures it is based on.
3. Recommend only actions the data directly supports. If the data cannot show whether an action would work (for example, switching suppliers or the outcome of a negotiation), do not recommend it.
4. State ranks exactly as given. The data does not state a time period, so do not call any figure annual.
5. Excise tax is statutory and non-controllable. Focus recovery recommendations on controllable leakage (freight and losses on loss-making SKUs).
6. Use plain markdown headings and text. Do not use emojis.
7. Each figure belongs only to the vendor on the same line. Never carry a figure (such as an SKU count) from one vendor to another. If a figure is not given for a vendor, say it is not available.
8. The vendor lists cover only the vendors shown. When comparing vendors, say "among the top 10 by revenue" or "among the top 10 by controllable leakage", never "in the portfolio", unless the figure is a portfolio total.
9. Where the data already gives a count or a list (such as the vendors below the portfolio margin), use it exactly rather than recounting.
10. Only state counts that appear in the data. Do not derive new counts (for example, how many vendors in a subset meet a condition); name the vendors instead.
11. When quoting a percentage, use the percentage attached to that exact figure in the data. Do not attach a percentage from one figure (such as controllable leakage) to a different figure (such as losses)."""

user_prompt = f"""Analyse this vendor data.

PORTFOLIO TOTALS
{portfolio_data}
TOP 10 VENDORS BY REVENUE
{revenue_data}
TOP 10 VENDORS BY CONTROLLABLE LEAKAGE
{leakage_data}
Structure the summary as:
1. Portfolio position (2-3 sentences)
2. Concentration risk
3. Margin position among the top 10 revenue vendors
4. Profit leakage: controllable vs non-controllable, and which vendors drive the controllable part
5. Top 3 recommendations. For each, add an "Evidence:" line quoting the figures behind it
6. Data limitations: what this data cannot tell management"""

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=2000,
    temperature=0,  # consistent, repeatable output for the same data
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}],
)

insight = message.content[0].text

print("\n--- AI COMMERCIAL INSIGHT ---\n")
print(insight)


# ---------------------------------------------------------------
# 5. Save to file (UTF-8 so any character can be written)
# ---------------------------------------------------------------
with open("vendor_insight_output.txt", "w", encoding="utf-8") as f:
    f.write("VENDOR PERFORMANCE AI INSIGHT\n")
    f.write("=" * 40 + "\n\n")
    f.write(insight)

print("\nInsight saved to vendor_insight_output.txt")
print("Done")