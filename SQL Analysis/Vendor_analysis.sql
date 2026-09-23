/* ==========================================================================
   Beverage Distribution — Commercial Performance Analytics, Sales Planning
   and KPI Reporting
   Author: Hardeep Bamrah
   Database: Vendor_sales (SQL Server Express)

   Structure
   1. Data profiling on the raw table (dbo.vendor_sales_summary)
   2. vw_VendorSalesBase: one canonical name per vendor number
   3. Analytical views: revenue, tiering, portfolio health, loss-making SKUs,
      logistics costs, rankings, pricing, full-cost analysis, clean SKU set,
      Pareto concentration and profit leakage
   4. Data checks and validation

   Conventions
   - Vendor margins are blended from totals (gross profit / revenue). The
     simple SKU-average columns (AvgMargin, AvgMarginPct) are kept for
     comparison only.
   - Freight is one repeated value per vendor, so it is taken with MAX.
   - Vendors with revenue under $10K are treated as micro-vendors: they are
     excluded from margin benchmarks and margin rankings.
   - Portfolio health metrics exclude SKUs with StockTurnover above 10;
     vendor-level views use all rows.
   ========================================================================== */


-- Selecting the raw table for profiling

USE Vendor_sales;


--- Understanding rows and previewing data

SELECT count(*) AS TotalRows 
FROM dbo.vendor_sales_summary;


SELECT * FROM dbo.vendor_sales_summary;

SELECT 
     VendorName,
     Brand,
     SUM(TotalSalesDollars) AS TotalRevenue,
     SUM(FreightCost)   AS TotalFreight,
     SUM(TotalExciseTax) AS TotalExcise,
     COUNT(Description)    AS TotalSKUs


     FROM dbo.vendor_sales_summary
     
     WHERE VendorName = 'DIAGEO NORTH AMERICA INC' AND Brand = '4261'
     GROUP BY VendorName, Brand;




SELECT
    VendorName,
    ROUND(SUM(TotalSalesQuantity), 0) AS AnnualUnits,
    ROUND(SUM(TotalSalesDollars), 2)  AS AnnualRevenue
FROM dbo.vendor_sales_summary
WHERE VendorName = 'DIAGEO NORTH AMERICA INC'
GROUP BY VendorName;



-- Testing rows at granular level to understand how a freight cost is distributed --

SELECT 
     VendorName,
     Brand,             
     SUM(TotalSalesDollars)   AS Revenue,
     SUM(FreightCost)         AS Freight,   
     SUM(TotalExciseTax)      AS Excise, 
     COUNT(Description)       AS SKUCount      
FROM dbo.vendor_sales_summary
WHERE VendorName = 'MARTIGNETTI COMPANIES'
GROUP BY VendorName, Brand;
     







-- =============================================
-- VIEW: dbo.vw_VendorSalesBase
-- PURPOSE: One name per vendor. Two vendor numbers appear under two names each
--          (VendorNumber 2000: SOUTHERN WINE & SPIRITS NE / SOUTHERN GLAZERS W&S OF NE;
--           VendorNumber 1587: VINEYARD BRANDS INC / VINEYARD BRANDS LLC).
--          Freight is recorded per VendorNumber, so analysing by name would count
--          their freight twice. Canonical name = the name with the most SKU rows
--          for that VendorNumber.
-- FEEDS: every analytical view below
-- =============================================


IF OBJECT_ID('dbo.vw_VendorSalesBase', 'V') IS NOT NULL
    DROP VIEW dbo.vw_VendorSalesBase;
GO

CREATE VIEW dbo.vw_VendorSalesBase AS
WITH NameCounts AS (
    SELECT
        VendorNumber,
        VendorName,
        ROW_NUMBER() OVER (PARTITION BY VendorNumber
                           ORDER BY COUNT(*) DESC, VendorName) AS NameRank
    FROM dbo.vendor_sales_summary
    GROUP BY VendorNumber, VendorName
)
SELECT
    s.VendorNumber,
    n.VendorName,
    s.Brand,
    s.Description,
    s.PurchasePrice,
    s.ActualPrice,
    s.Volume,
    s.TotalPurchaseQuantity,
    s.TotalPurchaseDollars,
    s.TotalSalesQuantity,
    s.TotalSalesDollars,
    s.TotalSalesPrice,
    s.TotalExciseTax,
    s.FreightCost,
    s.GrossProfit,
    s.ProfitMargin,
    s.StockTurnover,
    s.SalesToPurchaseRatio
FROM dbo.vendor_sales_summary s
JOIN NameCounts n
  ON n.VendorNumber = s.VendorNumber
 AND n.NameRank = 1;
GO




-- =============================================
-- VIEW: dbo.vw_VendorRevenueSummary
-- PURPOSE: Revenue and profit KPIs by vendor
-- =============================================

IF OBJECT_ID('dbo.vw_VendorRevenueSummary', 'V') IS NOT NULL
    DROP VIEW dbo.vw_VendorRevenueSummary;
GO


CREATE VIEW dbo.vw_VendorRevenueSummary AS
SELECT
    VendorName,
    COUNT(Description)                        AS NumberOfSKUs,
    ROUND(SUM(TotalSalesDollars), 2)          AS TotalRevenue,
    ROUND(SUM(GrossProfit), 2)                AS TotalGrossProfit,
    ROUND(AVG(ProfitMargin), 2)               AS AvgMarginPct,
    ROUND(SUM(TotalPurchaseDollars), 2)       AS TotalPurchaseCost,
    ROUND(SUM(TotalSalesDollars) * 100.0
          / SUM(SUM(TotalSalesDollars)) OVER(), 2) AS RevenueSharePct,
    ROUND(SUM(GrossProfit) * 100.0
          / NULLIF(SUM(TotalSalesDollars), 0), 2)  AS BlendedMarginPct
FROM dbo.vw_VendorSalesBase
GROUP BY VendorName;
GO




SELECT 
    SUM(TotalRevenue)      AS TotalRevenue,
    SUM(TotalGrossProfit)  AS TotalGrossProfit,
    SUM(TotalPurchaseCost) AS TotalPurchaseCost,
    ROUND(SUM(TotalGrossProfit) * 100.0 / 
          SUM(TotalRevenue), 2) AS BlendedMarginPct
FROM dbo.vw_VendorRevenueSummary;



-- CHECK AFTER CREATING:
SELECT * FROM dbo.vw_VendorRevenueSummary ORDER BY TotalRevenue DESC;
GO


-- Check the distribution of profit margins
-- to find outliers pulling averages off
SELECT
    MIN(ProfitMargin)                    AS MinMargin,
    MAX(ProfitMargin)                    AS MaxMargin,
    AVG(ProfitMargin)                    AS AvgMargin,
    -- How many SKUs have extreme negative margins
    SUM(CASE WHEN ProfitMargin < -100 THEN 1 ELSE 0 END) AS ExtremeNegativeCount,                     
    SUM(CASE WHEN ProfitMargin > 100 THEN 1 ELSE 0 END) AS ExtremePositiveCount,
    COUNT(*)                             AS TotalSKUs
FROM dbo.vendor_sales_summary;



-- Assessing ProfitMargin distribution before vendor-level analysis.
-- A review of margin values showed a small number of SKUs with extremely
-- negative margins, far below normal business ranges.
-- These outliers materially skew the overall average margin and can lead
-- to misleading conclusions when comparing vendor performance.
-- SKUs with ProfitMargin below -100% are flagged here for review (possible
-- returns, credits, pricing anomalies or data quality issues). They are NOT
-- filtered out of the views: vendor-level margins are blended from totals,
-- which limits their distortion, and vw_CleanAnalysis restricts margins to
-- the 0-100% range for pricing analysis.




SELECT TOP 20
    Description,
    VendorName,
    TotalSalesDollars,
    GrossProfit,
    ProfitMargin
FROM dbo.vendor_sales_summary
WHERE ProfitMargin < -100
ORDER BY ProfitMargin ASC;





-- ================================================
-- CREATE VIEW: vw_VendorTiering
-- Purpose: Segments vendors into revenue tiers
-- Used in: Power BI Page 2 (Commercial Deep Dive)
-- ================================================

IF OBJECT_ID('dbo.vw_VendorTiering', 'V') IS NOT NULL
    DROP VIEW dbo.vw_VendorTiering;
GO


CREATE VIEW dbo.vw_VendorTiering AS
WITH VendorRevenue AS (
    SELECT
        VendorName,
        ROUND(SUM(TotalSalesDollars), 2)   AS TotalRevenue,
        ROUND(SUM(GrossProfit), 2)         AS TotalProfit,
        ROUND(AVG(ProfitMargin), 2)        AS AvgMargin,
        ROUND(AVG(StockTurnover), 3)       AS AvgTurnover,
        COUNT(Description)                 AS SKUCount,
        ROUND(SUM(GrossProfit) * 100.0
              / NULLIF(SUM(TotalSalesDollars), 0), 2) AS BlendedMargin
    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName
)
SELECT
    VendorName,
    TotalRevenue,
    TotalProfit,
    AvgMargin,
    AvgTurnover,
    SKUCount,
    NTILE(4) OVER (ORDER BY TotalRevenue DESC) AS RevenueTier,
    CASE NTILE(4) OVER (ORDER BY TotalRevenue DESC)
        WHEN 1 THEN 'Tier 1 — Premium'
        WHEN 2 THEN 'Tier 2 — Core'
        WHEN 3 THEN 'Tier 3 — Standard'
        WHEN 4 THEN 'Tier 4 — Tail'
    END AS TierLabel,
    ROUND(TotalRevenue * 100.0 / SUM(TotalRevenue) OVER(), 2) AS RevenueSharePct,
    BlendedMargin
FROM VendorRevenue;
GO

-- CHECK AFTER CREATING:
SELECT * FROM dbo.vw_VendorTiering;
GO





-- ================================================
-- CREATE VIEW: vw_PortfolioHealth
-- Purpose: Composite health classification per SKU
-- Used in: Power BI Page 3 (Risk Dashboard)
-- ================================================



IF OBJECT_ID('dbo.vw_PortfolioHealth', 'V') IS NOT NULL
    DROP VIEW dbo.vw_PortfolioHealth;
GO

CREATE VIEW dbo.vw_PortfolioHealth AS
SELECT
    VendorName,
    VendorNumber,
    Brand,
    Description,
    PurchasePrice,
    ActualPrice,
    Volume,
    TotalPurchaseQuantity,
    TotalPurchaseDollars,
    TotalSalesQuantity,
    TotalSalesDollars,
    TotalSalesPrice,
    TotalExciseTax,
    FreightCost,
    GrossProfit,
    ProfitMargin,
    StockTurnover,
    SalesToPurchaseRatio,

    -- Markup %
    ROUND((ActualPrice - PurchasePrice)/ NULLIF(PurchasePrice, 0) * 100, 2) AS MarkupPct,
        

    -- Freight burden % = vendor freight / vendor revenue
    -- Freight repeats on every SKU row for a vendor, so MAX takes it once

    ROUND(MAX(FreightCost) OVER(PARTITION BY VendorName) 
             / NULLIF( SUM(TotalSalesDollars) OVER(PARTITION BY VendorName), 0) * 100, 2) AS FreightBurdenPct,


    -- Excise burden % (SKU-level cost)
    ROUND(TotalExciseTax / NULLIF(TotalSalesDollars, 0) * 100,
    2) AS ExciseBurdenPct,
   
   
    -- Net profit after excise
    ROUND(GrossProfit - TotalExciseTax, 2) AS NetProfitAfterExcise,


    -- Net margin after excise %
    ROUND((GrossProfit - TotalExciseTax)/ NULLIF(TotalSalesDollars, 0) * 100, 2) AS NetMarginAfterExcisePct,


    -- Composite status of SKUs based on stockTurnover, GrossProfit, ProfitMargin --
    -- Threshold of 20 is taken as to categorise SKUs --

    CASE
        WHEN GrossProfit < 0 THEN 'Loss Making'     
        WHEN ProfitMargin >= 20 AND StockTurnover >= 1.0 THEN 'Healthy'       
        WHEN ProfitMargin >= 20 AND StockTurnover < 1.0 THEN 'Profitable but Slow'           
        WHEN ProfitMargin >= 0 AND ProfitMargin < 20 AND StockTurnover >= 1.0 THEN 'Selling but Thin Margin'
        ELSE 'At Risk'                                                                         
    END AS HealthStatus,

    -- Margin category --
    CASE
        WHEN GrossProfit < 0    THEN 'Loss Making'
        WHEN ProfitMargin < 10  THEN 'Very Low Margin'
        WHEN ProfitMargin < 20  THEN 'Low Margin'
        WHEN ProfitMargin < 30  THEN 'Healthy'
        ELSE                         'High Margin'
    END AS MarginCategory,


    -- Turnover category
    CASE
        WHEN StockTurnover < 1.0 THEN 'Dead Stock Risk'           
        WHEN StockTurnover >= 1.0 AND StockTurnover < 1.5 THEN 'Slow Moving'          
        WHEN StockTurnover >= 1.5 AND StockTurnover < 3.0 THEN 'Healthy Turnover'           
        ELSE 'Fast Moving' 
    END AS TurnoverCategory,


    -- Volume category is being used basically to categorised and to understand which of the  
    -- vendors or products are in which category, which will help comparison easier.
    CASE
        WHEN Volume >= 1750 THEN 'Large Format'
        WHEN Volume >= 1000 THEN 'Standard Plus'
        WHEN Volume >= 750  THEN 'Standard'
        ELSE                     'Small Format'
    END AS VolumeCategory

FROM dbo.vw_VendorSalesBase
WHERE StockTurnover <= 10.0 OR StockTurnover IS NULL;
  
GO
         

SELECT * FROM dbo.vw_PortfolioHealth;
GO



-- Understanding particular Vendor at Granular level

SELECT TOP 5
    VendorName,
    Description,
    FreightCost,
    TotalSalesDollars,
    FreightBurdenPct
FROM dbo.vw_PortfolioHealth
WHERE VendorName = 'DIAGEO NORTH AMERICA INC'
ORDER BY FreightBurdenPct DESC;

GO



SELECT 
     HealthStatus,
     MarginCategory,
     TurnoverCategory,
     COUNT(*) AS  SKUCount
FROM dbo.vw_PortfolioHealth
GROUP BY HealthStatus, MarginCategory, TurnoverCategory
ORDER BY SKUCount DESC;





SELECT
    MarginCategory,
    COUNT(*)                            AS SKUCount,
    ROUND(COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER(), 2)      AS PctOfPortfolio,

    -- Simple average of SKU markups (shown for comparison; extreme SKUs distort it)
    ROUND(AVG(MarkupPct), 2)            AS AvgMarkupPct,

    -- Blended markup from totals (the reliable measure)
    ROUND(
        SUM(GrossProfit) * 100.0
        / NULLIF(SUM(TotalPurchaseDollars), 0),
    2)                                  AS BlendedMarkupPct,

    -- Blended margin from totals
    ROUND(
        SUM(GrossProfit) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                  AS BlendedMarginPct

FROM dbo.vw_PortfolioHealth
GROUP BY MarginCategory
ORDER BY BlendedMarginPct DESC;





-- ================================================
-- CREATE VIEW: vw_LossMakingAnalysis 
-- Purpose: Identifies vendors with loss-making products
-- Used in: Power BI Page 3 (Risk Dashboard)
-- ================================================



IF OBJECT_ID('dbo.vw_LossMakingAnalysis', 'V') IS NOT NULL
    DROP VIEW dbo.vw_LossMakingAnalysis;
GO

CREATE VIEW dbo.vw_LossMakingAnalysis AS
SELECT
    VendorName,
    Description,
    TotalSalesDollars,
    TotalPurchaseDollars,
    GrossProfit,
    ProfitMargin,
    StockTurnover,
    MarkupPct,
    FreightBurdenPct,
    ExciseBurdenPct,
    NetMarginAfterExcisePct,

    -- Pulled directly from vw_PortfolioHealth
    -- No recalculation needed
    MarginCategory,
    TurnoverCategory,
    HealthStatus

FROM dbo.vw_PortfolioHealth

-- Filter to only problematic SKUs
-- This is the purpose of this view
WHERE GrossProfit < 0
   OR ProfitMargin < 20
   OR TurnoverCategory = 'Dead Stock Risk';
GO


-- CHECK AFTER CREATING:
SELECT * FROM dbo.vw_LossMakingAnalysis;
GO




-- Finding exact HealthStatus values in data
-- These are exact SKUs including spaces and capitalisation
SELECT 
    HealthStatus,
    COUNT(*) AS SKUCount,
    MIN(StockTurnover) AS Minimum_Value,
    MAX(StockTurnover) AS Maximum_Value,
    AVG(StockTurnover) AS Average_Value
FROM dbo.vw_PortfolioHealth
GROUP BY HealthStatus
ORDER BY SKUCount DESC;


-- ================================================
-- CREATE VIEW: vw_LogisticsCostSummary
-- Purpose: Freight, excise and COGS by vendor
-- Will be Used in: Power BI Page 2 (Commercial Deep Dive)  
-- The COGS ratio (Cost of Goods Sold to Sales) measures the 
-- percentage of revenue consumed by the direct costs of producing goods or services, 
-- calculated as  
-- (COGS / Revenue * 100)
-- (Cost of Goods Sold / Net Sales) * 100  
-- ================================================


IF OBJECT_ID('dbo.vw_LogisticsCostSummary', 'V') IS NOT NULL
    DROP VIEW dbo.vw_LogisticsCostSummary;
GO

CREATE VIEW dbo.vw_LogisticsCostSummary AS

SELECT
    VendorName,
    VendorNumber,
    ROUND(SUM(TotalSalesDollars), 2)        AS TotalRevenue,
    ROUND(SUM(TotalPurchaseDollars), 2)     AS TotalCOGS,
    ROUND(SUM(TotalExciseTax), 2)           AS TotalExciseTax,

    -- Freight repeats across all SKUs per vendor,
    -- so MAX takes the vendor's freight once
    ROUND(MAX(FreightCost), 2)              AS TotalFreight,

    -- COGS as % of revenue
    ROUND(
        SUM(TotalPurchaseDollars) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                      AS COGSRatioPct,

    -- Freight as % of revenue
    ROUND(
        MAX(FreightCost) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                      AS FreightPctOfRevenue,

    -- Excise as % of revenue (SKU-level cost)
    ROUND(
        SUM(TotalExciseTax) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                      AS ExcisePctOfRevenue,

    -- Net margin after ALL costs
    ROUND(
        (SUM(TotalSalesDollars)
        - SUM(TotalPurchaseDollars)
        - MAX(FreightCost)
        - SUM(TotalExciseTax)) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                      AS NetMarginAfterAllCostsPct,

    -- Total cost burden %
    ROUND(
        (SUM(TotalPurchaseDollars)
        + MAX(FreightCost)
        + SUM(TotalExciseTax)) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2)                                      AS TotalCostBurdenPct,

    COUNT(Description)                      AS TotalSKUs

FROM dbo.vw_VendorSalesBase
GROUP BY VendorName, VendorNumber;
GO


-- Net margin spread across all vendors (includes micro-vendors)
SELECT
    AVG(NetMarginAfterAllCostsPct)  AS AvgNetMargin,
    MIN(NetMarginAfterAllCostsPct)  AS MinNetMargin,
    MAX(NetMarginAfterAllCostsPct)  AS MaxNetMargin,
    COUNT(*)                        AS VendorCount
FROM dbo.vw_LogisticsCostSummary;


-- DIAGEO specifically
SELECT
    VendorName,
    TotalRevenue,
    TotalCOGS,
    TotalFreight,
    TotalExciseTax,
    ROUND(TotalRevenue
          - TotalCOGS
          - TotalFreight
          - TotalExciseTax, 2)     AS NetProfit,
    NetMarginAfterAllCostsPct
FROM dbo.vw_LogisticsCostSummary
WHERE VendorName = 'DIAGEO NORTH AMERICA INC';

-- Portfolio average excluding micro-vendors
SELECT
    ROUND(AVG(NetMarginAfterAllCostsPct), 2)  AS AvgNetMargin,
    COUNT(*)                                   AS VendorCount,
    MIN(NetMarginAfterAllCostsPct)             AS MinMargin,
    MAX(NetMarginAfterAllCostsPct)             AS MaxMargin
FROM dbo.vw_LogisticsCostSummary
WHERE TotalRevenue >= 10000;





SELECT * FROM dbo.vw_LogisticsCostSummary;


SELECT TOP 5
    VendorName,
    TotalRevenue,
    TotalFreight,
    FreightPctOfRevenue,
    ExcisePctOfRevenue,
    NetMarginAfterAllCostsPct
FROM dbo.vw_LogisticsCostSummary
ORDER BY TotalRevenue DESC;





SELECT 
    VendorName,
    VendorNumber,
    ROUND(SUM(TotalPurchaseDollars),2) AS COGS

    FROM dbo.vendor_sales_summary
    GROUP BY VendorName, VendorNumber;





-- Testing  each view to ensure if the desired outputs are there.
--===============================================================

SELECT * FROM vw_VendorRevenueSummary
ORDER BY TotalRevenue DESC;

SELECT * FROM vw_LossMakingAnalysis
WHERE GrossProfit < 0
ORDER BY GrossProfit ASC;

SELECT * FROM vw_VendorTiering
ORDER BY RevenueTier, TotalRevenue DESC;

SELECT * FROM vw_PortfolioHealth
ORDER BY HealthStatus, GrossProfit ASC;

SELECT * FROM vw_LogisticsCostSummary
ORDER BY NetMarginAfterAllCostsPct ASC;

--===============================================================






-- ================================================
-- Vendor ranking by revenue and margin
-- Business question: Where does each vendor sit
-- in the performance league table?
-- ================================================



-- Margin is ranked on blended margin among vendors with revenue >= $10K.
-- Micro-vendors get a NULL MarginRank, so their CompositePerformanceScore is
-- also NULL: a vendor with a few thousand dollars of sales shouldn't top or
-- bottom a margin league table.

IF OBJECT_ID('dbo.vw_VendorRankings', 'V') IS NOT NULL
   DROP VIEW dbo.vw_VendorRankings;
GO


CREATE VIEW dbo.vw_VendorRankings AS
WITH VendorSummary AS (
    SELECT
        VendorName,
        ROUND(SUM(TotalSalesDollars), 2)   AS TotalRevenue,
        ROUND(SUM(GrossProfit), 2)         AS TotalProfit,
        ROUND(AVG(ProfitMargin), 2)        AS AvgMargin,
        ROUND(AVG(StockTurnover), 3)       AS AvgTurnover,
        COUNT(Description)                 AS SKUCount,
        ROUND(SUM(GrossProfit) * 100.0
              / NULLIF(SUM(TotalSalesDollars), 0), 2) AS BlendedMargin,
        CASE WHEN SUM(TotalSalesDollars) < 10000 THEN 1 ELSE 0 END AS IsMicroVendor
    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName
),
Ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (ORDER BY TotalRevenue DESC) AS RevenueRank,
        CASE WHEN IsMicroVendor = 0 THEN
            DENSE_RANK() OVER (PARTITION BY IsMicroVendor ORDER BY BlendedMargin DESC)
        END                                            AS MarginRank,
        DENSE_RANK() OVER (ORDER BY AvgTurnover DESC)  AS TurnoverRank
    FROM VendorSummary
)
SELECT
    VendorName,
    TotalRevenue,
    TotalProfit,
    AvgMargin,
    AvgTurnover,
    SKUCount,
    RevenueRank,
    MarginRank,
    TurnoverRank,
    ROUND((RevenueRank + MarginRank + TurnoverRank) / 3.0, 1) AS CompositePerformanceScore,
    BlendedMargin,
    IsMicroVendor
FROM Ranked;
GO


SELECT *
FROM dbo.vw_VendorRankings;


-- Vendors where revenue rank and margin rank are far apart
-- (big gap = revenue and profitability are misaligned)
SELECT
    VendorName,
    TotalRevenue,
    BlendedMargin,
    RevenueRank,
    MarginRank,
    ABS(RevenueRank - MarginRank) AS RankGap,
    CompositePerformanceScore
FROM dbo.vw_VendorRankings
WHERE IsMicroVendor = 0
ORDER BY RankGap DESC;
    
  

-- ================================================
-- Price gap analysis -- discount identification
-- Business question: Which products have the biggest
-- gap between listed price and purchase cost?
-- ================================================

IF OBJECT_ID('dbo.vw_PricingAnalysis', 'V') IS NOT NULL
    DROP VIEW dbo.vw_PricingAnalysis;
GO

CREATE VIEW dbo.vw_PricingAnalysis AS

WITH ProductPricing AS (
    SELECT
        VendorName,
        Description,
        PurchasePrice,
        ActualPrice,
        Volume,
        TotalSalesQuantity,
        TotalSalesDollars,
        GrossProfit,
        ProfitMargin,

        -- Feature engineering: Markup in dollars per unit
        ROUND(ActualPrice - PurchasePrice, 2) AS MarkupPerUnit,

        -- Feature engineering: Markup as percentage
        -- Formula: (Sell - Cost) / Cost x 100
        ROUND(
            ((ActualPrice - PurchasePrice) / NULLIF(PurchasePrice, 0)) * 100,
            2
        ) AS MarkupPct,

        -- Feature engineering: Gross margin %
        -- Margin uses selling price as denominator
        -- Markup uses cost price as denominator
        -- Markup and margin use different denominators, so they are not interchangeable
        ROUND(
            ((ActualPrice - PurchasePrice) / NULLIF(ActualPrice, 0)) * 100,
            2
        ) AS GrossMarginPct,

        -- Revenue potential if sold at full price
        ROUND(ActualPrice * TotalSalesQuantity, 2) AS FullPriceRevenuePotential

    FROM dbo.vw_VendorSalesBase
    WHERE PurchasePrice > 0
      AND ActualPrice > 0
),

RankedByMarkup AS (
    SELECT *,
        -- Rank products within each vendor by markup %
        -- PARTITION BY VendorName = ranking separately per vendor
        -- PARTITION BY ranks products within each vendor rather than globally
        -- Without PARTITION: one global rank across all products
        -- With PARTITION: separate rank for each vendor's products
        DENSE_RANK() OVER (
            PARTITION BY VendorName
            ORDER BY MarkupPct DESC
        ) AS MarkupRankWithinVendor,

        -- LAG() brings the previous row's markup into this row
        -- PARTITION BY VendorName = restart for each vendor
        -- ORDER BY MarkupPct DESC = ordered highest to lowest
        LAG(MarkupPct) OVER (
            PARTITION BY VendorName
            ORDER BY MarkupPct DESC
        ) AS PreviousProductMarkup

    FROM ProductPricing
)
SELECT
    VendorName,
    Description,
    PurchasePrice,
    ActualPrice,
    MarkupPerUnit,
    MarkupPct,
    GrossMarginPct,
    TotalSalesQuantity,
    TotalSalesDollars,
    MarkupRankWithinVendor,
    PreviousProductMarkup,

    -- Gap between this product markup and the one above it
    -- If this is large = big pricing inconsistency within vendor
    ROUND(
        PreviousProductMarkup - MarkupPct,
        2
    ) AS MarkupDropFromPrevious

FROM RankedByMarkup;
GO


-- PARTITION BY = restarts the window function per group
--   Without it: rank all 10692 rows together
--   With it: rank each vendors products separately
-- LAG(column) OVER(...) = bring previous rows value forward
--   NULL for the first row in each partition (nothing before it)
-- MarkupDropFromPrevious shows pricing inconsistency
--   A vendor where one product has 60% markup and the
--   next has 20% = inconsistent pricing strategy = finding

SELECT * FROM vw_PricingAnalysis;


-- Find products with the highest markup
-- and which vendor they belong to
SELECT TOP 20
    VendorName,
    Description,
    PurchasePrice,
    ActualPrice,
    MarkupPct,
    GrossMarginPct
FROM vw_PricingAnalysis
ORDER BY MarkupPct DESC;

-- Find vendors with biggest pricing inconsistency
SELECT
    VendorName,
    COUNT(*) AS ProductCount,
    ROUND(MAX(MarkupPct), 1) AS HighestMarkup,
    ROUND(MIN(MarkupPct), 1) AS LowestMarkup,
    ROUND(MAX(MarkupPct) - MIN(MarkupPct), 1) AS MarkupRange
FROM vw_PricingAnalysis
GROUP BY VendorName
ORDER BY MarkupRange DESC;





-- ================================================
-- Full logistics and cost analysis
-- Business question: After ALL costs -- freight,
-- excise, COGS -- which vendors are truly profitable?
-- Techniques: subqueries, COALESCE, NULLIF
-- ================================================




IF OBJECT_ID('dbo.vw_FullCostAnalysis', 'V') IS NOT NULL
    DROP VIEW dbo.vw_FullCostAnalysis;
GO

CREATE VIEW dbo.vw_FullCostAnalysis AS

SELECT
    VendorName,
    NumberOfSKUs,
    TotalRevenue,
    TotalCOGS,
    TotalFreight,
    TotalExciseTax,
    TotalGrossProfit,

    COALESCE(TotalFreight, 0)               AS FreightSafe,

    -- COGS ratio %
    ROUND(
        TotalCOGS * 100.0
        / NULLIF(TotalRevenue, 0),
    2)                                      AS COGSRatioPct,

    -- Freight burden %
    ROUND(
        TotalFreight * 100.0
        / NULLIF(TotalRevenue, 0),
    2)                                      AS FreightBurdenPct,

    -- Excise burden %
    ROUND(
        TotalExciseTax * 100.0
        / NULLIF(TotalRevenue, 0),
    2)                                      AS ExciseBurdenPct,

    -- Total cost burden
    ROUND(
        TotalCOGS + TotalFreight + TotalExciseTax,
    2)                                      AS TotalAllCosts,

    -- Net profit after all costs
    ROUND(
        TotalRevenue - TotalCOGS
        - TotalFreight - TotalExciseTax,
    2)                                      AS NetProfitAfterAllCosts,

    -- Net margin % after all costs
    ROUND(
        (TotalRevenue - TotalCOGS
         - TotalFreight - TotalExciseTax)
        * 100.0
        / NULLIF(TotalRevenue, 0),
    2)                                      AS NetMarginPct,

    -- Performance vs portfolio average net margin
    -- Benchmark = average net margin of vendors with revenue >= $10K,
    -- calculated the same way as the main query (MAX freight per vendor)
    CASE
        -- Micro-vendors (< $10K revenue) are not benchmarked
        WHEN TotalRevenue < 10000 THEN 'Micro Vendor (not benchmarked)'
        WHEN
            ROUND(
                (TotalRevenue - TotalCOGS
                 - TotalFreight - TotalExciseTax)
                * 100.0
                / NULLIF(TotalRevenue, 0), 2)
            >
            (SELECT AVG(NetMargin)
             FROM (
                 SELECT
                     VendorName,
                     ROUND(
                         (SUM(TotalSalesDollars)
                          - SUM(TotalPurchaseDollars)
                          - MAX(FreightCost)
                          - SUM(TotalExciseTax))
                         * 100.0
                         / NULLIF(SUM(TotalSalesDollars), 0),
                     2) AS NetMargin
                 FROM dbo.vw_VendorSalesBase
                 GROUP BY VendorName
                 HAVING SUM(TotalSalesDollars) >= 10000
             ) AS VendorMargins)
        THEN 'Above Average'
        ELSE 'Below Average'
    END                                     AS PerformanceVsAverage

FROM (
    SELECT
        VendorName,
        COUNT(Description)                  AS NumberOfSKUs,
        ROUND(SUM(TotalSalesDollars), 2)    AS TotalRevenue,
        ROUND(SUM(TotalPurchaseDollars), 2) AS TotalCOGS,

        -- Freight taken once per vendor
        ROUND(MAX(FreightCost), 2)          AS TotalFreight,

        ROUND(SUM(TotalExciseTax), 2)       AS TotalExciseTax,
        ROUND(SUM(GrossProfit), 2)          AS TotalGrossProfit
    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName
) AS VendorAggregated;
GO


SELECT * FROM vw_FullCostAnalysis;

-- This Query is built to understand only Non negative 
-- gross profit values
-- NULLIF(value, 0): if value = 0 return NULL instead
--   prevents divide by zero errors crashing the query
-- COALESCE(value, 0): if value is NULL return 0 instead
--   prevents NULL values propagating through calculations
-- Subquery in FROM clause: pre-aggregate data cleanly
--   then SELECT from the result as if it were a table
-- Subquery in WHERE/CASE: calculate a single comparison
--   value on the fly without needing a CTE
-- The combination of NULLIF and COALESCE is used for data quality
--   protection 


-- =====================================================
-- 
-- VIEW: dbo.vw_CleanAnalysis
-- PURPOSE: Viable SKUs only for pricing and margin
--          analysis where outliers distort averages
-- FILTER LOGIC:
--   GrossProfit > 0 = only profitable SKUs
--   ProfitMargin BETWEEN 0 AND 100 = realistic margins
--   TotalSalesQuantity > 0 = only SKUs that sold
--   TotalSalesDollars > 0  = only SKUs with revenue
-- NOTE: Loss-making SKUs deliberately excluded here
--       They are fully analysed in vw_fullcostanalysis
--       and vw_PortfolioHealth views
--       This view exists ONLY for pricing and margin
--       distribution analysis without outlier distortion
-- FEEDS: Excel pricing tab, Power BI Page 2 margin charts
-- =====================================================




IF OBJECT_ID('dbo.vw_CleanAnalysis', 'V') IS NOT NULL
    DROP VIEW dbo.vw_CleanAnalysis;
GO

CREATE VIEW dbo.vw_CleanAnalysis AS
SELECT
    VendorName,
    VendorNumber,
    Brand,
    Description,
    PurchasePrice,
    ActualPrice,
    Volume,
    TotalPurchaseQuantity,
    TotalPurchaseDollars,
    TotalSalesQuantity,
    TotalSalesDollars,
    TotalSalesPrice,
    TotalExciseTax,
    FreightCost,
    GrossProfit,
    ProfitMargin,
    StockTurnover,
    SalesToPurchaseRatio,

    -- Markup %
    ROUND(
        (ActualPrice - PurchasePrice)
        / NULLIF(PurchasePrice, 0) * 100,
    2) AS MarkupPct,

    -- Gross margin %
    ROUND(
        (ActualPrice - PurchasePrice)
        / NULLIF(ActualPrice, 0) * 100,
    2) AS GrossMarginPct,

    -- Freight burden % = vendor freight / vendor revenue
    -- Same calculation as vw_PortfolioHealth
    ROUND(
        MAX(FreightCost)
            OVER(PARTITION BY VendorName)
        / NULLIF(
            SUM(TotalSalesDollars)
                OVER(PARTITION BY VendorName),
            0) * 100,
    2) AS FreightBurdenPct,

    -- Excise burden % (SKU-level cost)
    ROUND(
        TotalExciseTax
        / NULLIF(TotalSalesDollars, 0) * 100,
    2) AS ExciseBurdenPct,

    -- Revenue per unit sold
    ROUND(
        TotalSalesDollars
        / NULLIF(TotalSalesQuantity, 0),
    2) AS RevenuePerUnit,

    -- Cost per unit purchased
    ROUND(
        TotalPurchaseDollars
        / NULLIF(TotalPurchaseQuantity, 0),
    2) AS CostPerUnit,

    -- Net profit after excise
    ROUND(
        GrossProfit - TotalExciseTax,
    2) AS NetProfitAfterExcise,

    -- Net margin after excise %
    ROUND(
        (GrossProfit - TotalExciseTax)
        / NULLIF(TotalSalesDollars, 0) * 100,
    2) AS NetMarginAfterExcisePct,

    -- Health classification on clean data
    CASE
        WHEN ProfitMargin >= 30 AND StockTurnover >= 1.0
            THEN 'Star Product'
        WHEN ProfitMargin >= 20 AND StockTurnover >= 1.0
            THEN 'Healthy'
        WHEN ProfitMargin >= 20 AND StockTurnover < 1.0
            THEN 'Profitable but Slow'
        WHEN ProfitMargin < 20 AND StockTurnover >= 1.0
            THEN 'Selling but Thin Margin'
        ELSE 'Needs Review'
    END AS HealthStatus,

    -- Volume category
    CASE
        WHEN Volume >= 1750 THEN 'Large Format'
        WHEN Volume >= 1000 THEN 'Standard Plus'
        WHEN Volume >= 750  THEN 'Standard'
        ELSE                     'Small Format'
    END AS VolumeCategory

FROM dbo.vw_VendorSalesBase
WHERE
    -- Only profitable SKUs
    GrossProfit > 0

    -- Realistic margin range -- removes calculation errors
    AND ProfitMargin BETWEEN 0 AND 100

    -- Only SKUs that actually sold
    AND TotalSalesQuantity > 0

    -- Only SKUs with actual revenue
    AND TotalSalesDollars > 0

    -- Only SKUs with a valid purchase price
    AND PurchasePrice > 0

    -- Only SKUs with a valid selling price
    AND ActualPrice > 0

    -- Selling price must be higher than purchase price
    -- If not it is a data error or pricing mistake
    AND ActualPrice > PurchasePrice

    -- Same turnover-outlier rule as vw_PortfolioHealth
    AND StockTurnover <= 10.0;
GO



SELECT TOP 10
    VendorName,
    Description,
    FreightBurdenPct,
    ExciseBurdenPct,
    MarkupPct,
    GrossMarginPct
FROM dbo.vw_CleanAnalysis
ORDER BY FreightBurdenPct DESC;




-- Test 1: How many SKUs pass the clean filter?
-- Compare to total 10,692 to understand what % is clean
SELECT COUNT(*) AS CleanSKUs
FROM dbo.vw_CleanAnalysis;

-- Test 2: Confirm no negatives exist in clean view
SELECT
    MIN(GrossProfit)    AS MinProfit,
    MAX(GrossProfit)    AS MaxProfit,
    MIN(ProfitMargin)   AS MinMargin,
    MAX(ProfitMargin)   AS MaxMargin,
    AVG(ProfitMargin)   AS AvgMargin
FROM dbo.vw_CleanAnalysis;

-- Test 3: Vendor summary on clean data
-- Matches the vendor summary in the Excel workbook
SELECT
    VendorName,
    COUNT(Description)              AS CleanSKUs,
    ROUND(SUM(TotalSalesDollars),2) AS TotalRevenue,
    ROUND(SUM(GrossProfit),2)       AS TotalProfit,
    ROUND(AVG(ProfitMargin),2)      AS AvgMarginPct,
    ROUND(AVG(MarkupPct),2)         AS AvgMarkupPct,
    ROUND(AVG(StockTurnover),3)     AS AvgTurnover
FROM dbo.vw_CleanAnalysis
GROUP BY VendorName
ORDER BY TotalRevenue DESC;





-- =====================================================
-- VIEW: dbo.vw_ParetoAnalysis
-- PURPOSE: Revenue concentration and Pareto analysis
--          Identifies which vendors follow the 80/20 rule
--          Shows cumulative revenue contribution
-- FEEDS: Power BI Page 1, Excel Executive Summary
-- =====================================================

IF OBJECT_ID('dbo.vw_ParetoAnalysis', 'V') IS NOT NULL
    DROP VIEW dbo.vw_ParetoAnalysis;
GO

CREATE VIEW dbo.vw_ParetoAnalysis AS
WITH VendorRevenue AS (
    SELECT
        VendorName,
        COUNT(Description)                   AS SKUCount,
        ROUND(SUM(TotalSalesDollars), 2)     AS TotalRevenue,
        ROUND(SUM(GrossProfit), 2)           AS TotalProfit,
        ROUND(AVG(ProfitMargin), 2)          AS AvgMargin,
        ROUND(SUM(GrossProfit) * 100.0
              / NULLIF(SUM(TotalSalesDollars), 0), 2) AS BlendedMargin
    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName
),
VendorRanked AS (
    SELECT
        *,
        DENSE_RANK() OVER (ORDER BY TotalRevenue DESC)                 AS RevenueRank,
        ROUND(TotalRevenue * 100.0 / SUM(TotalRevenue) OVER(), 2)       AS RevenueSharePct,
        SUM(TotalRevenue) OVER()                                        AS GrandTotalRevenue
    FROM VendorRevenue
),
VendorCumulative AS (
    SELECT
        *,
        ROUND(SUM(TotalRevenue) OVER (ORDER BY TotalRevenue DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 2)     AS CumulativeRevenue,
        ROUND(SUM(TotalRevenue) OVER (ORDER BY TotalRevenue DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0
              / GrandTotalRevenue, 2)                                   AS CumulativeRevenuePct
    FROM VendorRanked
)
SELECT
    VendorName,
    SKUCount,
    TotalRevenue,
    TotalProfit,
    AvgMargin,
    RevenueRank,
    RevenueSharePct,
    CumulativeRevenue,
    CumulativeRevenuePct,
    CASE
        WHEN CumulativeRevenuePct <= 80 THEN 'Top 80% Revenue Band'
        WHEN CumulativeRevenuePct <= 95 THEN 'Mid 15% Revenue Band'
        ELSE 'Tail 5% Revenue Band'
    END AS ParetoBand,
    CASE
        WHEN CumulativeRevenuePct <= 80 THEN 'Critical Vendor'
        ELSE 'Non Critical Vendor'
    END AS VendorCriticality,
    BlendedMargin
FROM VendorCumulative;
GO


-- Testing 

-- See the Pareto curve clearly
SELECT
    RevenueRank,
    VendorName,
    TotalRevenue,
    RevenueSharePct,
    CumulativeRevenuePct,
    ParetoBand,
    VendorCriticality
FROM dbo.vw_ParetoAnalysis
ORDER BY RevenueRank;

-- The headline finding
-- How many vendors make up 80% of revenue?
SELECT
    ParetoBand,
    COUNT(VendorName)              AS VendorCount,
    ROUND(SUM(TotalRevenue), 2)    AS BandRevenue,
    ROUND(AVG(RevenueSharePct), 2) AS AvgSharePct
FROM dbo.vw_ParetoAnalysis
GROUP BY ParetoBand
ORDER BY BandRevenue DESC;






-- =====================================================
-- 
-- VIEW: dbo.vw_profit_leakage
-- PURPOSE: Identifies where profit is being lost, per vendor.
--          TotalLeakage = excise tax + freight + losses on loss-making SKUs.
--          Controllable = freight + loss-making SKUs; excise is statutory
--          (non-controllable). Dead stock is reported separately as revenue
--          at risk and is not added to leakage.
-- FEEDS: Power BI Risk page, Excel Risk tab
-- =====================================================




IF OBJECT_ID('dbo.vw_ProfitLeakage', 'V') IS NOT NULL
    DROP VIEW dbo.vw_ProfitLeakage;
GO

CREATE VIEW dbo.vw_ProfitLeakage AS

WITH VendorBase AS (
    SELECT
        VendorName,
        VendorNumber,
        ROUND(SUM(TotalSalesDollars), 2)      AS TotalRevenue,
        ROUND(SUM(GrossProfit), 2)            AS TotalGrossProfit,
        ROUND(SUM(TotalPurchaseDollars), 2)    AS TotalCOGS,
        ROUND(SUM(TotalExciseTax), 2)          AS TotalExciseTax,
        COUNT(Description)                     AS TotalSKUs,
        ROUND(MAX(FreightCost), 2)             AS TotalFreight,

        ROUND(SUM(CASE
            WHEN GrossProfit < 0
            THEN ABS(GrossProfit)
            ELSE 0 END), 2)                   AS LossMakingLeakage,

        ROUND(SUM(CASE
            WHEN StockTurnover < 1.0
            THEN TotalSalesDollars
            ELSE 0 END), 2)                   AS DeadStockRevenue,

        SUM(CASE
            WHEN StockTurnover < 1.0
            THEN 1 ELSE 0 END)                AS DeadStockSKUs,

        SUM(CASE
            WHEN GrossProfit < 0
            THEN 1 ELSE 0 END)                AS LossMakingSKUs

    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName, VendorNumber
)
SELECT
    VendorName,
    VendorNumber,
    TotalRevenue,
    TotalGrossProfit,
    TotalCOGS,
    TotalSKUs,
    LossMakingSKUs,
    DeadStockSKUs,

    -- EXCISE LEAKAGE
    TotalExciseTax                            AS ExciseLeakage,
    ROUND(TotalExciseTax * 100.0
        / NULLIF(TotalRevenue, 0), 2)         AS ExciseLeakagePct,

    -- FREIGHT LEAKAGE
    TotalFreight                              AS FreightLeakage,
    ROUND(TotalFreight * 100.0
        / NULLIF(TotalRevenue, 0), 2)         AS FreightLeakagePct,

    -- LOSS MAKING LEAKAGE
    LossMakingLeakage,
    ROUND(LossMakingLeakage * 100.0
        / NULLIF(TotalRevenue, 0), 2)         AS LossMakingLeakagePct,

    -- DEAD STOCK
    DeadStockRevenue,
    ROUND(DeadStockRevenue * 100.0
        / NULLIF(TotalRevenue, 0), 2)         AS DeadStockRevenuePct,
    ROUND(DeadStockSKUs * 100.0
        / NULLIF(TotalSKUs, 0), 2)            AS DeadStockSKUsPct,

    -- LOSS MAKING SKU PCT
    ROUND(LossMakingSKUs * 100.0
        / NULLIF(TotalSKUs, 0), 2)            AS LossMakingSKUsPct,

    -- TOTAL LEAKAGE
    ROUND(
        TotalExciseTax
        + TotalFreight
        + LossMakingLeakage, 2)              AS TotalLeakageAmount,

    ROUND(
        (TotalExciseTax
        + TotalFreight
        + LossMakingLeakage) * 100.0
        / NULLIF(TotalRevenue, 0), 2)        AS TotalLeakagePct,

    -- POTENTIAL PROFIT: net profit after all costs plus the controllable
    -- leakage recovered (freight + loss-making SKUs). GrossProfit is
    -- sales - purchases, so excise is subtracted and treated as unavoidable.
    ROUND(
        TotalGrossProfit
        - TotalExciseTax
        + LossMakingLeakage, 2)              AS PotentialProfit,
    ROUND(
        (TotalGrossProfit
        - TotalExciseTax
        + LossMakingLeakage) * 100.0
        / NULLIF(TotalRevenue, 0), 2)        AS PotentialMarginPct,

    -- SEVERITY
    CASE
        WHEN (TotalExciseTax + TotalFreight
              + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 30
            THEN 'Critical Leakage'
        WHEN (TotalExciseTax + TotalFreight
              + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 15
            THEN 'High Leakage'
        WHEN (TotalExciseTax + TotalFreight
              + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 5
            THEN 'Moderate Leakage'
        ELSE 'Low Leakage'
    END                                      AS LeakageSeverity,

    -- Net profit and leakage split: controllable (freight + loss-making SKUs)
    -- vs non-controllable (excise, a statutory tax)
    ROUND(TotalGrossProfit - TotalExciseTax - TotalFreight, 2)
                                             AS NetProfitAfterAllCosts,
    ROUND((TotalGrossProfit - TotalExciseTax - TotalFreight) * 100.0
        / NULLIF(TotalRevenue, 0), 2)        AS NetMarginAfterAllCostsPct,
    ROUND(TotalFreight + LossMakingLeakage, 2)
                                             AS ControllableLeakage,
    ROUND((TotalFreight + LossMakingLeakage) * 100.0
        / NULLIF(TotalRevenue, 0), 2)        AS ControllableLeakagePct,
    TotalExciseTax                           AS NonControllableCost,
    -- Thresholds set for this dataset; review the distribution with check C5
    CASE
        WHEN (TotalFreight + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 10 THEN 'Critical'
        WHEN (TotalFreight + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 5  THEN 'High'
        WHEN (TotalFreight + LossMakingLeakage) * 100.0
             / NULLIF(TotalRevenue, 0) > 2  THEN 'Moderate'
        ELSE 'Low'
    END                                      AS ControllableLeakageSeverity

FROM VendorBase;
GO




SELECT * FROM vw_ProfitLeakage;

SELECT
    ROUND(SUM(TotalRevenue), 2)          AS TotalRevenue,
    ROUND(SUM(ExciseLeakage), 2)        AS TotalExcise,
    ROUND(SUM(FreightLeakage), 2)          AS TotalFreight,
    ROUND(SUM(LossMakingLeakage), 2)     AS TotalLossLeakage,
    ROUND(SUM(TotalLeakageAmount), 2)    AS TotalLeakage
FROM dbo.vw_ProfitLeakage;



 

 -- Check what makes up the leakage for the top vendors
SELECT TOP 5
    VendorName,
    ROUND(SUM(TotalSalesDollars), 2)    AS TotalRevenue,
    ROUND(SUM(TotalExciseTax), 2)       AS ExciseTotal,
    ROUND(MAX(FreightCost), 2)          AS FreightTotal,
    ROUND(SUM(CASE WHEN GrossProfit < 0 
        THEN ABS(GrossProfit) 
        ELSE 0 END), 2)                 AS LossAmount,
    ROUND(SUM(TotalExciseTax) 
        + MAX(FreightCost)
        + SUM(CASE WHEN GrossProfit < 0 
            THEN ABS(GrossProfit) 
            ELSE 0 END), 2)             AS TotalLeakage
FROM dbo.vw_VendorSalesBase
GROUP BY VendorName
ORDER BY TotalLeakage DESC;




SELECT
    LeakageSeverity,
    COUNT(*)                            AS VendorCount,
    ROUND(SUM(TotalRevenue), 2)         AS TotalRevenue,
    ROUND(SUM(FreightLeakage), 2)         AS TotalFreight,
    ROUND(SUM(ExciseLeakage), 2)       AS TotalExcise,
    ROUND(SUM(LossMakingLeakage), 2)    AS TotalLossLeakage,
    ROUND(SUM(TotalLeakageAmount), 2)   AS TotalLeakage,
    ROUND(AVG(TotalLeakagePct), 2)      AS AvgLeakagePct
FROM dbo.vw_ProfitLeakage
GROUP BY LeakageSeverity
ORDER BY TotalLeakage DESC;



SELECT TOP 10
    VendorName,
    TotalRevenue,
    FreightLeakage,
    ExciseLeakage,
    LossMakingLeakage,
    TotalLeakageAmount,
    TotalLeakagePct,
    LeakageSeverity
FROM dbo.vw_ProfitLeakage
WHERE LeakageSeverity = 'Critical Leakage'
ORDER BY TotalLeakagePct DESC;



-- Top 10 vendors by total leakage amount
SELECT TOP 10
    VendorName,
    TotalRevenue,
    ExciseLeakage,
    FreightLeakage,
    LossMakingLeakage,
    TotalLeakageAmount,
    TotalLeakagePct,
    LeakageSeverity
FROM dbo.vw_ProfitLeakage
ORDER BY TotalLeakageAmount DESC;




-- COMPLETE HEADLINE KPI CHECK
-- This is to confirm all numbers for CV and interview

SELECT
    -- Total portfolio
    COUNT(*)                                AS TotalSKUs,
    COUNT(DISTINCT VendorName)              AS TotalVendors,
    ROUND(SUM(TotalSalesDollars), 2)        AS TotalRevenue,
    ROUND(SUM(GrossProfit), 2)              AS TotalGrossProfit,
    ROUND(SUM(GrossProfit) * 100.0
        / NULLIF(SUM(TotalSalesDollars),0),2) AS BlendedMarginPct,

    -- Loss making
    SUM(CASE WHEN MarginCategory = 'Loss Making'
        THEN 1 ELSE 0 END)                  AS LossMakingSKUs,
    ROUND(SUM(CASE WHEN MarginCategory = 'Loss Making'
        THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2)                      AS LossMakingPct,

    -- Dead stock
    SUM(CASE WHEN TurnoverCategory = 'Dead Stock Risk'
        THEN 1 ELSE 0 END)                  AS DeadStockSKUs,
    ROUND(SUM(CASE WHEN TurnoverCategory = 'Dead Stock Risk'
        THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2)                      AS DeadStockPct,

    -- Profitable but slow
    SUM(CASE WHEN HealthStatus = 'Profitable but Slow'
        THEN 1 ELSE 0 END)                  AS ProfitableSlowSKUs,
    ROUND(SUM(CASE WHEN HealthStatus = 'Profitable but Slow'
        THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2)                      AS ProfitableSlowPct,

    -- Average turnover
    ROUND(AVG(StockTurnover), 3)            AS AvgStockTurnover

FROM dbo.vw_PortfolioHealth;

--- To get full details of different views which are created



SELECT
    name AS ViewName,
    create_date AS Created,
    modify_date AS LastModified
FROM sys.views
WHERE name LIKE 'vw_%'
ORDER BY name;


/* ==========================================================================
   DATA CHECKS AND VALIDATION
   Run after creating the views. Expected results on the current dataset are
   noted with each check, so a data change that breaks an assumption shows up.
   ========================================================================== */

-- A1. Is GrossProfit = Sales - Purchases (so excise and freight are NOT in it)?
--     Expected: MaxAbsDifference close to 0, which is why net profit and
--     PotentialProfit subtract excise and freight separately.
SELECT
    COUNT(*)                                                         AS SKURows,
    ROUND(MAX(ABS(TotalSalesDollars - TotalPurchaseDollars - GrossProfit)), 4)
                                                                     AS MaxAbsDifference
FROM dbo.vendor_sales_summary;



-- A2. Is freight really one repeated value per vendor (the reason for MAX)?
--     Expected: no rows. Any row here means MAX would under-count that vendor.
SELECT
    VendorName,
    COUNT(DISTINCT FreightCost)   AS DistinctFreightValues,
    COUNT(DISTINCT VendorNumber)  AS DistinctVendorNumbers
FROM dbo.vendor_sales_summary
GROUP BY VendorName
HAVING COUNT(DISTINCT FreightCost) > 1
    OR COUNT(DISTINCT VendorNumber) > 1;
GO



-- A3. Does any VendorNumber appear under more than one name?
--     Expected in the raw table: 2 rows (VendorNumber 2000 and 1587).
--     vw_VendorSalesBase resolves both, so the same query on the base view returns no rows.
SELECT VendorNumber, COUNT(DISTINCT VendorName) AS NamesPerNumber
FROM dbo.vendor_sales_summary
GROUP BY VendorNumber
HAVING COUNT(DISTINCT VendorName) > 1;

SELECT VendorNumber, COUNT(DISTINCT VendorName) AS NamesPerNumber
FROM dbo.vw_VendorSalesBase
GROUP BY VendorNumber
HAVING COUNT(DISTINCT VendorName) > 1;

GO

-- C1. Portfolio totals: all rows (vendor-level views) vs outlier-cleaned base
--     (portfolio health metrics).
--     Expected: all rows $451.62M, 10,692 rows, 126 vendors;
--               cleaned $450.92M, 10,495 rows, 125 vendors
SELECT 'All rows (vendor views)' AS Base,
       COUNT(*) AS SKURows, COUNT(DISTINCT VendorName) AS Vendors,
       ROUND(SUM(TotalSalesDollars), 2) AS Revenue,
       ROUND(SUM(GrossProfit), 2) AS GrossProfit,
       ROUND(SUM(GrossProfit) * 100.0 / SUM(TotalSalesDollars), 2) AS BlendedMarginPct
FROM dbo.vw_VendorSalesBase
UNION ALL
SELECT 'Cleaned (StockTurnover <= 10)',
       COUNT(*), COUNT(DISTINCT VendorName),
       ROUND(SUM(TotalSalesDollars), 2),
       ROUND(SUM(GrossProfit), 2),
       ROUND(SUM(GrossProfit) * 100.0 / SUM(TotalSalesDollars), 2)
FROM dbo.vw_VendorSalesBase
WHERE StockTurnover <= 10.0 OR StockTurnover IS NULL;

-- C2. Simple vs blended margin: the 15 vendors (>= $10K) where they differ most
SELECT TOP 15
    VendorName, TotalRevenue, TotalGrossProfit,
    AvgMarginPct      AS SimpleAvgMarginPct,
    BlendedMarginPct,
    ROUND(BlendedMarginPct - AvgMarginPct, 2) AS Gap
FROM dbo.vw_VendorRevenueSummary
WHERE TotalRevenue >= 10000
ORDER BY ABS(BlendedMarginPct - AvgMarginPct) DESC;

-- C3. Margin ranking: simple-average margin vs blended margin
--     Shows how much a simple average of SKU margins would misrank vendors.
WITH SimpleRank AS (
    SELECT VendorName,
           DENSE_RANK() OVER (ORDER BY AVG(ProfitMargin) DESC) AS SimpleAvgMarginRank
    FROM dbo.vw_VendorSalesBase
    GROUP BY VendorName
)
SELECT TOP 20
    r.VendorName, r.TotalRevenue, r.AvgMargin, r.BlendedMargin,
    sr.SimpleAvgMarginRank, r.MarginRank AS BlendedMarginRank,
    sr.SimpleAvgMarginRank - r.MarginRank AS RankDifference
FROM dbo.vw_VendorRankings r
JOIN SimpleRank sr ON sr.VendorName = r.VendorName
WHERE r.IsMicroVendor = 0
ORDER BY ABS(sr.SimpleAvgMarginRank - r.MarginRank) DESC;

-- C4. Leakage: controllable vs non-controllable, net profit and potential profit
--     Expected: controllable leakage $5.99M (1.33%), excise $18.97M,
--               net profit after all costs $109.11M (24.16%), PotentialProfit $115.10M
SELECT
    ROUND(SUM(TotalRevenue), 2)                     AS Revenue,
    ROUND(SUM(TotalGrossProfit), 2)                 AS GrossProfit,
    ROUND(SUM(ExciseLeakage), 2)                    AS Excise_NonControllable,
    ROUND(SUM(FreightLeakage), 2)                   AS Freight,
    ROUND(SUM(LossMakingLeakage), 2)                AS LossMakingSKUs,
    ROUND(SUM(ControllableLeakage), 2)              AS ControllableLeakage,
    ROUND(SUM(ControllableLeakage) * 100.0 / SUM(TotalRevenue), 2) AS ControllablePctOfRevenue,
    ROUND(SUM(TotalLeakageAmount), 2)               AS TotalLeakage,
    ROUND(SUM(NetProfitAfterAllCosts), 2)           AS NetProfitAfterAllCosts,
    ROUND(SUM(NetProfitAfterAllCosts) * 100.0 / SUM(TotalRevenue), 2) AS BlendedNetMarginPct,
    ROUND(SUM(PotentialProfit), 2)                  AS PotentialProfit
FROM dbo.vw_ProfitLeakage;

-- C5. Where to act first: top 10 vendors by controllable leakage
SELECT TOP 10
    VendorName, TotalRevenue, FreightLeakage, LossMakingLeakage,
    ControllableLeakage, ControllableLeakagePct, ControllableLeakageSeverity
FROM dbo.vw_ProfitLeakage
ORDER BY ControllableLeakage DESC;
GO