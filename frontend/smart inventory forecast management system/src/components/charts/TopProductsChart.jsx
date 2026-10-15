import React, { useState, useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import { useSelector } from 'react-redux'
import { Award, Filter } from 'lucide-react'
import { getChartTheme } from './ChartSetup'
import ChartCard from './ChartCard'

const PALETTE = [
  '#8b5cf6',
  '#a855f7',
  '#3b82f6',
  '#06b6d4',
  '#10b981',
  '#f59e0b',
  '#ec4899',
  '#6366f1',
  '#14b8a6',
  '#f97316',
]

export default function TopProductsChart({ sales = [], products = [] }) {
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const [metric, setMetric] = useState('revenue') // 'revenue' | 'units'
  const [limit, setLimit] = useState('5') // '5' | '10' | '20' | 'all'
  const [selectedCategory, setSelectedCategory] = useState('all')

  // Extract unique categories
  const categories = useMemo(() => {
    const set = new Set()
    products.forEach((p) => {
      if (p.category) set.add(p.category.trim())
    })
    return Array.from(set).sort()
  }, [products])

  const {
    labels,
    chartValues,
    topProductName,
    topRevenue,
    totalTrackedRevenue,
    totalTrackedUnits,
    trackingRows,
  } = useMemo(() => {
    if (!sales || sales.length === 0) {
      return {
        labels: ['No sales data'],
        chartValues: [0],
        topProductName: '—',
        topRevenue: 0,
        totalTrackedRevenue: 0,
        totalTrackedUnits: 0,
        trackingRows: [],
      }
    }

    // Aggregate sales by product_id
    const prodMap = new Map()

    sales.forEach((s) => {
      const pid = s.product_id
      const rev = Number(s.revenue) || (Number(s.selling_price || 0) * Number(s.quantity_sold || 0)) || 0
      const qty = Number(s.quantity_sold) || 0

      if (!prodMap.has(pid)) {
        prodMap.set(pid, {
          productId: pid,
          revenue: 0,
          unitsSold: 0,
        })
      }

      const item = prodMap.get(pid)
      item.revenue += rev
      item.unitsSold += qty
    })

    // Filter by category if chosen
    let rows = Array.from(prodMap.values()).map((item) => {
      const prod = products.find((p) => p.id === item.productId)
      return {
        productId: item.productId,
        name: prod?.name || `Product #${item.productId}`,
        sku: prod?.sku || '—',
        category: prod?.category || 'General',
        currentStock: Number(prod?.current_stock) || 0,
        minStock: Number(prod?.min_stock_level) || 0,
        revenue: Math.round(item.revenue * 100) / 100,
        unitsSold: item.unitsSold,
      }
    })

    if (selectedCategory !== 'all') {
      rows = rows.filter((r) => r.category.toLowerCase() === selectedCategory.toLowerCase())
    }

    // Sort by chosen metric
    rows.sort((a, b) => {
      if (metric === 'revenue') {
        return b.revenue - a.revenue
      }
      return b.unitsSold - a.unitsSold
    })

    // Add rank
    rows = rows.map((r, idx) => {
      const isLow = r.currentStock <= r.minStock
      const isOut = r.currentStock <= 0
      return {
        ...r,
        rank: idx + 1,
        stockStatus: isOut ? 'Out of Stock' : isLow ? 'Low Stock' : 'In Stock',
      }
    })

    const topLimit = limit === 'all' ? rows.length : parseInt(limit, 10) || 5
    const displayedRows = rows.slice(0, topLimit)

    const lbls = displayedRows.map((r) =>
      r.name.length > 20 ? `${r.name.substring(0, 18)}...` : r.name
    )
    const vals = displayedRows.map((r) =>
      metric === 'revenue' ? r.revenue : r.unitsSold
    )

    const totalRev = rows.reduce((acc, r) => acc + r.revenue, 0)
    const totalUnits = rows.reduce((acc, r) => acc + r.unitsSold, 0)

    return {
      labels: lbls,
      chartValues: vals,
      topProductName: rows[0]?.name || 'Leader',
      topRevenue: rows[0]?.revenue || 0,
      totalTrackedRevenue: totalRev,
      totalTrackedUnits: totalUnits,
      trackingRows: rows,
    }
  }, [sales, products, metric, limit, selectedCategory])

  const trackingColumns = [
    {
      key: 'rank',
      label: 'Rank',
      numeric: true,
      sortable: true,
      render: (r) => (
        <span
          style={{
            fontWeight: 800,
            color: r.rank === 1 ? '#f59e0b' : r.rank === 2 ? '#94a3b8' : r.rank === 3 ? '#d97706' : 'var(--erp-text-muted)',
          }}
        >
          #{r.rank}
        </span>
      ),
    },
    { key: 'name', label: 'Product Name', sortable: true },
    { key: 'sku', label: 'SKU', sortable: true },
    { key: 'category', label: 'Category', sortable: true },
    {
      key: 'unitsSold',
      label: 'Units Sold',
      numeric: true,
      sortable: true,
      render: (r) => <span style={{ fontWeight: 600 }}>{r.unitsSold.toLocaleString()}</span>,
    },
    {
      key: 'revenue',
      label: 'Revenue (₹)',
      numeric: true,
      sortable: true,
      render: (r) => (
        <span style={{ fontWeight: 700, color: '#10b981' }}>
          ₹{r.revenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
      ),
    },
    {
      key: 'currentStock',
      label: 'Remaining Stock',
      numeric: true,
      sortable: true,
      render: (r) => <span>{r.currentStock} units</span>,
    },
    {
      key: 'stockStatus',
      label: 'Stock Status',
      sortable: true,
      render: (r) => {
        const isOut = r.stockStatus === 'Out of Stock'
        const isLow = r.stockStatus === 'Low Stock'
        return (
          <span
            style={{
              fontSize: '0.7rem',
              padding: '2px 8px',
              borderRadius: '4px',
              fontWeight: 600,
              background: isOut
                ? 'var(--status-danger-bg)'
                : isLow
                ? 'var(--status-warning-bg)'
                : 'var(--status-success-bg)',
              color: isOut
                ? 'var(--status-danger-text)'
                : isLow
                ? 'var(--status-warning-text)'
                : 'var(--status-success-text)',
              border: `1px solid ${
                isOut
                  ? 'var(--status-danger-border)'
                  : isLow
                  ? 'var(--status-warning-border)'
                  : 'var(--status-success-border)'
              }`,
            }}
          >
            {r.stockStatus}
          </span>
        )
      },
    },
  ]

  const kpiSummary = [
    {
      label: 'Top Revenue Driver',
      value: topProductName,
      subtext: `₹${Number(topRevenue).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      color: 'var(--erp-brand)',
    },
    {
      label: 'Total Revenue in Catalog',
      value: `₹${Number(totalTrackedRevenue).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
      subtext: 'Cumulative sales revenue',
      color: '#10b981',
    },
    {
      label: 'Total Units Sold',
      value: `${totalTrackedUnits.toLocaleString()} units`,
      subtext: 'Cumulative items dispatched',
      color: '#3b82f6',
    },
    {
      label: 'Products Sold',
      value: `${trackingRows.length} active SKUs`,
      subtext: 'Catalog contribution',
      color: '#f59e0b',
    },
  ]

  const chartData = {
    labels,
    datasets: [
      {
        label: metric === 'revenue' ? 'Revenue (₹)' : 'Units Sold',
        data: chartValues,
        backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
        borderRadius: 4,
        barPercentage: 0.65,
      },
    ],
  }

  const options = {
    indexAxis: 'y',
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
          label: (context) =>
            metric === 'revenue'
              ? ` Revenue: ₹${context.parsed.x.toLocaleString()}`
              : ` Units Sold: ${context.parsed.x} units`,
        },
      },
    },
    scales: {
      x: {
        grid: {
          color: chartColors.gridColor,
        },
        ticks: {
          color: chartColors.textColor,
          font: { size: 10 },
          callback: (val) => (metric === 'revenue' ? `₹${val}` : `${val} u`),
        },
      },
      y: {
        grid: {
          display: false,
        },
        ticks: {
          color: chartColors.textColor,
          font: { size: 11, weight: 600 },
        },
      },
    },
  }

  const filterControlGroup = (
    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'center' }}>
      {/* Metric Toggle */}
      <div
        style={{
          display: 'inline-flex',
          backgroundColor: 'var(--erp-surface-subtle)',
          borderRadius: '6px',
          padding: '2px',
          border: '1px solid var(--erp-border)',
        }}
      >
        <button
          type="button"
          className={`btn btn-sm ${metric === 'revenue' ? 'btn-primary' : 'btn-subtle'}`}
          style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
          onClick={() => setMetric('revenue')}
        >
          Revenue (₹)
        </button>
        <button
          type="button"
          className={`btn btn-sm ${metric === 'units' ? 'btn-primary' : 'btn-subtle'}`}
          style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
          onClick={() => setMetric('units')}
        >
          Units Sold
        </button>
      </div>

      {/* Category Dropdown */}
      {categories.length > 0 && (
        <select
          className="form-control"
          style={{ width: '130px', padding: '0.25rem 0.5rem', fontSize: '0.725rem' }}
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
        >
          <option value="all">All Categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      )}

      {/* Top Limit Dropdown */}
      <select
        className="form-control"
        style={{ width: '90px', padding: '0.25rem 0.5rem', fontSize: '0.725rem' }}
        value={limit}
        onChange={(e) => setLimit(e.target.value)}
      >
        <option value="5">Top 5</option>
        <option value="10">Top 10</option>
        <option value="20">Top 20</option>
        <option value="all">All Items</option>
      </select>
    </div>
  )

  return (
    <ChartCard
      title={`Top Products by ${metric === 'revenue' ? 'Revenue' : 'Units Sold'}`}
      subtitle={`Leader: ${topProductName} (₹${Number(topRevenue).toLocaleString()})`}
      icon={Award}
      badge={metric === 'revenue' ? 'Revenue Drivers' : 'Volume Leaders'}
      badgeType="success"
      kpiSummary={kpiSummary}
      trackingData={trackingRows}
      trackingColumns={trackingColumns}
      filterControls={filterControlGroup}
      actions={filterControlGroup}
      height={280}
    >
      {({ isFullscreen, height: chartHeight }) => (
        <div style={{ height: chartHeight || 280, position: 'relative', width: '100%' }}>
          <Bar
            key={`${theme}-${metric}-${limit}-${selectedCategory}-${isFullscreen}`}
            data={chartData}
            options={options}
          />
        </div>
      )}
    </ChartCard>
  )
}
