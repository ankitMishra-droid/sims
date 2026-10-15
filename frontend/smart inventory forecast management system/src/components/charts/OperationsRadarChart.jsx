import React, { useState, useMemo } from 'react'
import { Radar } from 'react-chartjs-2'
import { useSelector } from 'react-redux'
import { Activity } from 'lucide-react'
import { getChartTheme } from './ChartSetup'
import ChartCard from './ChartCard'

export default function OperationsRadarChart({
  products = [],
  sales = [],
  purchaseOrders = [],
  suppliers = [],
}) {
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const [dimensionFilter, setDimensionFilter] = useState('all')

  const { scores, compositeScore, trackingRows, strongestDim, weakestDim } = useMemo(() => {
    // 1. Stock Health (% of products with stock > reorder_level)
    const healthyCount = products.filter(
      (p) => (Number(p.current_stock) || 0) > (Number(p.reorder_level) || 0)
    ).length
    const stockHealth = products.length > 0 ? Math.round((healthyCount / products.length) * 100) : 85

    // 2. Stock Availability (% of items not at zero)
    const nonZeroCount = products.filter((p) => (Number(p.current_stock) || 0) > 0).length
    const availability = products.length > 0 ? Math.round((nonZeroCount / products.length) * 100) : 90

    // 3. Procurement Fulfillment (% of POs that are received or partially received)
    const receivedPOs = purchaseOrders.filter((po) =>
      ['RECEIVED', 'PARTIALLY_RECEIVED'].includes(po.status)
    ).length
    const poFulfillment =
      purchaseOrders.length > 0 ? Math.round((receivedPOs / purchaseOrders.length) * 100) : 75

    // 4. Sales Velocity (active sales activity index)
    const salesVelocity = Math.min(100, Math.max(30, sales.length * 12))

    // 5. Supplier Network Coverage
    const coveredSuppliers = new Set(products.map((p) => p.supplier_id).filter(Boolean))
    const supplierCoverage =
      suppliers.length > 0
        ? Math.min(100, Math.round((coveredSuppliers.size / suppliers.length) * 100) + 20)
        : 80

    // 6. Overall Composite Score
    const composite = Math.round(
      (stockHealth + availability + poFulfillment + salesVelocity + supplierCoverage) / 5
    )

    const dimensions = [
      {
        id: 'stock_health',
        name: 'Stock Health',
        score: stockHealth,
        benchmark: 85,
        status: stockHealth >= 80 ? 'Optimal' : stockHealth >= 60 ? 'Acceptable' : 'Needs Action',
        recommendation:
          stockHealth >= 80
            ? 'Stock buffers are healthy above safety reorder points.'
            : 'Replenish low-stock SKUs to prevent stockouts.',
      },
      {
        id: 'availability',
        name: 'Catalog Availability',
        score: availability,
        benchmark: 95,
        status: availability >= 90 ? 'Optimal' : availability >= 75 ? 'Acceptable' : 'Critical Stockouts',
        recommendation:
          availability >= 90
            ? 'Warehouse fill rate is high across all catalog lines.'
            : 'Several key items are depleted; execute restock immediately.',
      },
      {
        id: 'po_fulfillment',
        name: 'PO Fulfillment Rate',
        score: poFulfillment,
        benchmark: 80,
        status: poFulfillment >= 75 ? 'Optimal' : poFulfillment >= 50 ? 'Moderate' : 'Delayed Lead Times',
        recommendation:
          poFulfillment >= 75
            ? 'Suppliers delivering purchase orders within expected SLA.'
            : 'Follow up with pending vendors on overdue deliveries.',
      },
      {
        id: 'sales_velocity',
        name: 'Sales Velocity',
        score: salesVelocity,
        benchmark: 70,
        status: salesVelocity >= 70 ? 'High Throughput' : 'Steady',
        recommendation:
          salesVelocity >= 70
            ? 'Robust inventory turnover and regular customer dispatches.'
            : 'Promote slow-moving inventory to improve stock turns.',
      },
      {
        id: 'supplier_coverage',
        name: 'Supplier Network',
        score: supplierCoverage,
        benchmark: 80,
        status: supplierCoverage >= 75 ? 'Diversified' : 'Concentrated Risk',
        recommendation:
          supplierCoverage >= 75
            ? 'Vendor distribution covers majority of product lines.'
            : 'Diversify backup suppliers to reduce single-source dependency.',
      },
    ]

    const sortedByScore = [...dimensions].sort((a, b) => b.score - a.score)

    return {
      scores: [stockHealth, availability, poFulfillment, salesVelocity, supplierCoverage],
      compositeScore: composite,
      trackingRows: dimensions,
      strongestDim: sortedByScore[0],
      weakestDim: sortedByScore[sortedByScore.length - 1],
    }
  }, [products, sales, purchaseOrders, suppliers])

  const trackingColumns = [
    { key: 'name', label: 'Operational Dimension', sortable: true },
    {
      key: 'score',
      label: 'Performance Score',
      numeric: true,
      sortable: true,
      render: (r) => (
        <span
          style={{
            fontWeight: 800,
            color: r.score >= 80 ? '#10b981' : r.score >= 60 ? '#f59e0b' : '#ef4444',
          }}
        >
          {r.score} / 100
        </span>
      ),
    },
    {
      key: 'benchmark',
      label: 'Target Benchmark',
      numeric: true,
      sortable: true,
      render: (r) => <span>{r.benchmark}%</span>,
    },
    {
      key: 'status',
      label: 'Operational Status',
      sortable: true,
      render: (r) => (
        <span
          style={{
            fontSize: '0.7rem',
            padding: '2px 8px',
            borderRadius: '4px',
            fontWeight: 600,
            background:
              r.score >= 80
                ? 'var(--status-success-bg)'
                : r.score >= 60
                ? 'var(--status-warning-bg)'
                : 'var(--status-danger-bg)',
            color:
              r.score >= 80
                ? 'var(--status-success-text)'
                : r.score >= 60
                ? 'var(--status-warning-text)'
                : 'var(--status-danger-text)',
            border: `1px solid ${
              r.score >= 80
                ? 'var(--status-success-border)'
                : r.score >= 60
                ? 'var(--status-warning-border)'
                : 'var(--status-danger-border)'
            }`,
          }}
        >
          {r.status}
        </span>
      ),
    },
    {
      key: 'recommendation',
      label: 'Executive Recommendation',
      sortable: false,
      render: (r) => <span style={{ color: 'var(--erp-text-muted)' }}>{r.recommendation}</span>,
    },
  ]

  const kpiSummary = [
    {
      label: 'Composite Index',
      value: `${compositeScore} / 100`,
      subtext: compositeScore >= 80 ? 'Optimal operational readiness' : 'Moderate performance',
      color: compositeScore >= 80 ? '#10b981' : 'var(--erp-brand)',
    },
    {
      label: 'Strongest Pillar',
      value: strongestDim?.name || '—',
      subtext: `${strongestDim?.score}/100 efficiency score`,
      color: '#10b981',
    },
    {
      label: 'Priority Improvement',
      value: weakestDim?.name || '—',
      subtext: `${weakestDim?.score}/100 efficiency score`,
      color: '#f59e0b',
    },
    {
      label: 'Entities Tracked',
      value: `${products.length} Products, ${suppliers.length} Suppliers`,
      subtext: 'Real-time telemetry sample',
      color: '#3b82f6',
    },
  ]

  const chartData = {
    labels: [
      'Stock Health',
      'Availability',
      'PO Fulfillment',
      'Sales Velocity',
      'Supplier Coverage',
    ],
    datasets: [
      {
        label: 'Efficiency Index (0-100)',
        data: scores,
        backgroundColor: isDark ? 'rgba(192, 132, 252, 0.25)' : 'rgba(113, 75, 103, 0.2)',
        borderColor: isDark ? '#c084fc' : '#714b67',
        borderWidth: 2,
        pointBackgroundColor: isDark ? '#c084fc' : '#714b67',
        pointBorderColor: isDark ? '#111827' : '#ffffff',
        pointBorderWidth: 1.5,
        pointRadius: 4,
        pointHoverRadius: 6,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: chartColors.tooltipBg,
        borderColor: chartColors.tooltipBorder,
        borderWidth: 1,
        titleColor: chartColors.tooltipTitleColor || '#ffffff',
        bodyColor: chartColors.tooltipBodyColor || '#f1f5f9',
        padding: 10,
        cornerRadius: 6,
        callbacks: {
          label: (context) => ` ${context.label}: ${context.parsed.r}/100 Score`,
        },
      },
    },
    scales: {
      r: {
        min: 0,
        max: 100,
        ticks: {
          display: false,
          stepSize: 20,
        },
        grid: {
          color: chartColors.gridColor,
        },
        angleLines: {
          color: chartColors.gridColor,
        },
        pointLabels: {
          color: chartColors.textColor,
          font: { size: 10, weight: 600 },
        },
      },
    },
  }

  return (
    <ChartCard
      title="Warehouse Health & Operations Index"
      subtitle={`Composite Efficiency Score: ${compositeScore}/100`}
      icon={Activity}
      badge={compositeScore >= 80 ? 'Optimal' : compositeScore >= 60 ? 'Good' : 'Needs Action'}
      badgeType={compositeScore >= 80 ? 'success' : 'warning'}
      kpiSummary={kpiSummary}
      trackingData={trackingRows}
      trackingColumns={trackingColumns}
      height={280}
    >
      {({ isFullscreen, height: chartHeight }) => (
        <div style={{ height: chartHeight || 280, position: 'relative', width: '100%' }}>
          <Radar key={`${theme}-${isFullscreen}`} data={chartData} options={options} />
        </div>
      )}
    </ChartCard>
  )
}
