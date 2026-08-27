
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


# Pull top 10 vendors by revenue

cursor.execute("""
    SELECT TOP 10
        VendorName,
        NumberofSKUs,
        TotalRevenue,
        TotalGrossProfit,
        AvgMarginPct,
        RevenueSharePct
    FROM dbo.vw_VendorRevenueSummary
    ORDER BY TotalRevenue DESC
""")


rows = cursor.fetchall()

for row in rows:
    print(row)

# Prepare data for Claude

vendor_data = ""
for row in rows:
    vendor_data += f"Vendor: {row[0]}, SKUs: {row[1]}, Revenue: ${row[2]:,.0f}, Gross Profit: ${row[3]:,.0f}, Margin: {row[4]:.1f}%, Revenue Share: {row[5]:.1f}%\n"

# Send to Claude API
message = client.messages.create(
     model="claude-opus-4-5",
     max_tokens=1024,
     messages=[
          {
               "role": "user",
               "content": f"You are a commercial analyst. Analyse this beverage vendor performance data and give me a plain English summary highlighting concentration risk,margin concerns, and your top 3 recommendations:\n\n{vendor_data}"
          }
     ]
)

# Print Claude's response

insight = message.content[0].text

print("\n--- AI COMMERCIAL INSIGHT ---\n")
print(insight)

# save to file

with open("vendor_insight_output.txt", "w") as f:
    f.write("VENDOR PERFORMANCE AI INSIGHT\n")
    f.write("="*40 + "\n\n")
    f.write(insight)

print("\nInsight saved to vendor_insight_output.txt")          
      

conn.close()


print("Done")





