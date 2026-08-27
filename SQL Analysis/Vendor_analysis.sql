



USE Vendor_sales;



--- Understanding rows and previewing data

SELECT count(*) AS TotalRows FROM vendor_sales_summary;

SELECT TOP 50 * FROM vendor_sales_summary;
GO



-- =============================================
-- VIEW: dbo.vw_VendorRevenueSummary
-- PURPOSE: Revenue and profit KPIs by vendor
-- FEEDS: Power BI Page 1 — Executive Summary
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
    ROUND(
        SUM(TotalSalesDollars) * 100.0
        / SUM(SUM(TotalSalesDollars)) OVER(),
    2)                                        AS RevenueSharePct
FROM dbo.vendor_sales_summary
GROUP BY VendorName;
GO


-- CHECK AFTER CREATING:
SELECT * FROM dbo.vw_VendorRevenueSummary ORDER BY TotalRevenue DESC;
GO




-- ================================================
-- CREATE VIEW: vw_LossMakingAnalysis or Commercial KPI's
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
    GrossProfit,
    ProfitMargin,
    StockTurnover,
    TotalPurchaseDollars,

    CASE
        WHEN GrossProfit < 0 THEN 'Loss Making'
        WHEN GrossProfit >= 0 AND ProfitMargin < 10 THEN 'Very Low Margin'
        WHEN ProfitMargin >= 10 AND ProfitMargin < 20 THEN 'Low Margin'
        WHEN ProfitMargin >= 20 AND ProfitMargin < 30 THEN 'Healthy'
        ELSE 'High Margin'
    END AS MarginCategory,

    CASE
        WHEN StockTurnover < 1.0 THEN 'Dead Stock Risk'
        WHEN StockTurnover >= 1.0 AND StockTurnover < 1.5 THEN 'Slow Moving'
        ELSE 'Healthy Turnover'
    END AS TurnoverCategory
FROM dbo.vendor_sales_summary;
GO


-- CHECK AFTER CREATING:
SELECT * FROM dbo.vw_LossMakingAnalysis;
GO




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
        ROUND(SUM(GrossProfit), 2)          AS TotalProfit,
        ROUND(AVG(ProfitMargin), 2)         AS AvgMargin,
        ROUND(AVG(StockTurnover), 3)        AS AvgTurnover,
        COUNT(Description)                  AS SKUCount
    FROM vendor_sales_summary
    GROUP BY VendorName
)
SELECT
    VendorName,
    TotalRevenue,
    TotalProfit,
    AvgMargin,
    AvgTurnover,
    SKUCount,

    -- NTILE(4) splits into 4 tiers
    -- Tier 1 = top 25% vendors by revenue
    NTILE(4) OVER (ORDER BY TotalRevenue DESC) AS RevenueTier,

    
    CASE NTILE(4) OVER (ORDER BY TotalRevenue DESC)
        WHEN 1 THEN 'Tier 1 — Premium'
        WHEN 2 THEN 'Tier 2 — Core'
        WHEN 3 THEN 'Tier 3 — Standard'
        WHEN 4 THEN 'Tier 4 — Tail'
    END AS TierLabel,

    -- Revenue share %
    ROUND(
        TotalRevenue * 100.0
        / SUM(TotalRevenue) OVER(),
    2) AS RevenueSharePct

FROM VendorRevenue;
GO


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
    Description,
    PurchasePrice,
    ActualPrice,
    TotalSalesDollars,
    TotalSalesQuantity,
    TotalPurchaseQuantity,
    GrossProfit,
    ProfitMargin,
    StockTurnover,
    FreightCost,
    TotalExciseTax,

    -- Markup %
    ROUND(
        ((ActualPrice - PurchasePrice) / NULLIF(PurchasePrice, 0)) * 100,
        2
    ) AS MarkupPct,

    -- Freight burden %
    ROUND(
        (FreightCost / NULLIF(TotalSalesDollars, 0)) * 100,
        2
    ) AS FreightBurdenPct,

    -- Excise burden %
    ROUND(
        (TotalExciseTax / NULLIF(TotalSalesDollars, 0)) * 100,
        2
    ) AS ExciseBurdenPct,

    -- Net profit after excise
    ROUND(
        GrossProfit - TotalExciseTax,
        2
    ) AS NetProfitAfterExcise,

    -- Composite health status
    CASE
        WHEN GrossProfit < 0 THEN 'Loss Making'
        WHEN ProfitMargin >= 20 AND StockTurnover >= 1.0 THEN 'Healthy'
        WHEN ProfitMargin >= 20 AND StockTurnover < 1.0 THEN 'Profitable but Slow'
        WHEN ProfitMargin >= 0 AND ProfitMargin < 20 AND StockTurnover >= 1.0 THEN 'Selling but Thin Margin'
        ELSE 'At Risk'
    END AS HealthStatus
FROM dbo.vendor_sales_summary;
GO
         

SELECT * FROM dbo.vw_VendorTiering;
GO




-- ================================================
-- CREATE VIEW: vw_LogisticsCostSummary
-- Purpose: Freight, excise and COGS by vendor
-- Used in: Power BI Page 2 (Commercial Deep Dive)  
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
    ROUND(SUM(TotalSalesDollars), 2)      AS TotalRevenue,
    ROUND(SUM(TotalPurchaseDollars), 2)   AS TotalCOGS,
    ROUND(SUM(FreightCost), 2)            AS TotalFreight,
    ROUND(SUM(TotalExciseTax), 2)         AS TotalExciseTax,
    ROUND(SUM(GrossProfit), 2)            AS TotalGrossProfit,

    -- COGS ratio: what % of revenue goes to purchasing
    ROUND(
        SUM(TotalPurchaseDollars) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2) AS COGSRatioPct,

    -- Freight as % of revenue
    ROUND(
        SUM(FreightCost) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2) AS FreightPctOfRevenue,

    -- Excise as % of revenue
    ROUND(
        SUM(TotalExciseTax) * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2) AS ExcisePctOfRevenue,

    -- Total cost burden = COGS + Freight + Excise
    ROUND(
        SUM(TotalPurchaseDollars)
        + SUM(FreightCost)
        + SUM(TotalExciseTax),
    2) AS TotalCostBurden,

    -- Net margin after ALL costs
    ROUND(
        (SUM(TotalSalesDollars)
        - SUM(TotalPurchaseDollars)
        - SUM(FreightCost)
        - SUM(TotalExciseTax))
        * 100.0
        / NULLIF(SUM(TotalSalesDollars), 0),
    2) AS NetMarginAfterAllCostsPct
FROM dbo.vendor_sales_summary
GROUP BY VendorName;
GO


SELECT * FROM dbo.vw_LogisticsCostSummary;



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



IF OBJECT_ID('dbo.vw_VendorRankings', 'V') IS NOT NULL
   DROP VIEW dbo.vw_VendorRankings;
GO


CREATE VIEW dbo.vw_VendorRankings AS
WITH VendorSummary AS (
     SELECT 
          VendorName,
          ROUND(SUM(TotalSalesDollars), 2)     AS TotalRevenue,
          ROUND(SUM(GrossProfit), 2)           AS TotalProfit,
          ROUND(AVG(ProfitMargin), 2)          AS AvgMargin,
          ROUND(AVG(StockTurnover), 3)         AS AvgTurnover,
          COUNT(Description)                   AS SKUCount
    FROM dbo.vendor_sales_summary
    GROUP BY VendorName
)
SELECT 
    VendorName,
    TotalRevenue,
    TotalProfit,
    AvgMargin,
    AvgTurnover,
    SKUCount,

    DENSE_RANK() OVER(ORDER BY TotalRevenue DESC) AS RevenueRank,
    DENSE_RANK() OVER(ORDER BY AvgMargin DESC) AS MarginRank,
    DENSE_RANK() OVER(ORDER BY AvgTurnover DESC) AS TurnoverRank,

    ROUND(
        ( 
           DENSE_RANK() OVER(ORDER BY TotalRevenue DESC) + 
           DENSE_RANK() OVER(ORDER BY AvgMargin DESC) +
           DENSE_RANK() OVER(ORDER BY AvgTurnover DESC)
        ) / 3.0,
        1
        ) AS CompositePerformanceScore
FROM VendorSummary;
GO


SELECT *
FROM dbo.vw_VendorRankings;


-- Vendors where revenue rank and margin rank
-- are very different -- Here are key findings
SELECT
    VendorName,
    TotalRevenue,
    AvgMargin,
    RevenueRank,
    MarginRank,
    -- Gap between ranks -- big gap = misalignment
    ABS(RevenueRank - MarginRank) AS RankGap,
    CompositePerformanceScore
FROM vw_VendorRankings
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
        -- These are different -- important keypoint to consider for me
        ROUND(
            ((ActualPrice - PurchasePrice) / NULLIF(ActualPrice, 0)) * 100,
            2
        ) AS GrossMarginPct,

        -- Revenue potential if sold at full price
        ROUND(ActualPrice * TotalSalesQuantity, 2) AS FullPriceRevenuePotential

    FROM dbo.vendor_sales_summary
    WHERE PurchasePrice > 0
      AND ActualPrice > 0
),

RankedByMarkup AS (
    SELECT *,
        -- Rank products within each vendor by markup %
        -- PARTITION BY VendorName = rank separately per vendor
        -- This is the key difference from Query 6
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

-- WHAT THIS TEACHES YOU:
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
-- New concept: Subquery + COALESCE + NULLIF
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

    -- COALESCE returns the first non-NULL value
    -- Protects against NULL values breaking calculations
    -- If FreightCost is NULL treat it as 0
    COALESCE(TotalFreight, 0)   AS FreightSafe,

    -- COGS ratio %
    -- Formula: What % of revenue goes to buying stock
    ROUND(
        TotalCOGS * 100.0
        / NULLIF(TotalRevenue, 0),
    2) AS COGSRatioPct,

    -- Freight burden %
    ROUND(
        TotalFreight * 100.0
        / NULLIF(TotalRevenue, 0),
    2) AS FreightBurdenPct,

    -- Excise burden %
    ROUND(
        TotalExciseTax * 100.0
        / NULLIF(TotalRevenue, 0),
    2) AS ExciseBurdenPct,

    -- Total cost burden in dollars
    ROUND(
        TotalCOGS + TotalFreight + TotalExciseTax,
    2) AS TotalAllCosts,

    -- Net profit after ALL costs
    ROUND(
        TotalRevenue - TotalCOGS
        - TotalFreight - TotalExciseTax,
    2) AS NetProfitAfterAllCosts,

    -- Net margin % after ALL costs
    -- This is your most realistic profitability KPI
    ROUND(
        (TotalRevenue - TotalCOGS
         - TotalFreight - TotalExciseTax)
        * 100.0 / NULLIF(TotalRevenue, 0),
    2) AS NetMarginPct,

    -- Performance vs average
    -- This is the subquery -- it calculates the average
    -- net margin across ALL vendors first
    -- then compares each vendor to that average
    CASE
        WHEN
            ROUND(
                (TotalRevenue - TotalCOGS
                 - TotalFreight - TotalExciseTax)
                * 100.0 / NULLIF(TotalRevenue, 0), 2)
            >
            -- SUBQUERY: calculates grand average net margin
            -- runs once, returns one number
            -- the outer query compares every vendor to it
            (SELECT AVG(
                (v.TotalSalesDollars - v.TotalPurchaseDollars
                 - v.FreightCost - v.TotalExciseTax)
                * 100.0 / NULLIF(v.TotalSalesDollars, 0)
             )
             FROM vendor_sales_summary v)
        THEN 'Above Average'
        ELSE 'Below Average'
    END AS PerformanceVsAverage

FROM (
    -- THIS IS THE OUTER SUBQUERY
    -- It pre-aggregates all vendors into one clean row each
    -- The main SELECT above then works on this clean data
    -- Instead of repeating SUM() everywhere
    SELECT
        VendorName,
        COUNT(Description)                  AS NumberOfSKUs,
        ROUND(SUM(TotalSalesDollars), 2)    AS TotalRevenue,
        ROUND(SUM(TotalPurchaseDollars), 2) AS TotalCOGS,
        ROUND(SUM(FreightCost), 2)          AS TotalFreight,
        ROUND(SUM(TotalExciseTax), 2)       AS TotalExciseTax,
        ROUND(SUM(GrossProfit), 2)          AS TotalGrossProfit
    FROM vendor_sales_summary
    GROUP BY VendorName
) AS VendorAggregated;

GO


SELECT * FROM vw_FullCostAnalysis;

-- WHAT THIS TEACHES YOU:
-- NULLIF(value, 0): if value = 0 return NULL instead
--   prevents divide by zero errors crashing your query
-- COALESCE(value, 0): if value is NULL return 0 instead
--   prevents NULL values propagating through calculations
-- Subquery in FROM clause: pre-aggregate data cleanly
--   then SELECT from the result as if it were a table
-- Subquery in WHERE/CASE: calculate a single comparison
--   value on the fly without needing a CTE
-- The combination of NULLIF and COALESCE = data quality
--   protection -- shows professional SQL thinking