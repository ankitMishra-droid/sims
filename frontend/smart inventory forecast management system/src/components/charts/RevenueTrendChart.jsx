import React, { useState, useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import { useSelector } from 'react-redux'
import { TrendingUp } from 'lucide-react'
import { getChartTheme } from './ChartSetup'
import ChartCard from './ChartCard'

export default function RevenueTrendChart({ sales = [] }) {
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const [metric, setMetric] = useState('revenue') // 'revenue' | 'orders'
  const [range, setRange] = useState('30') // '7' | '30' | 'all'

  // Prepare time series data
  const {
    labels,
    dataPoints,
    totalPeriodRevenue,
    growthPct,
    trackingRows,
    totalOrdersCount,
    peakDay,
  } = useMemo(() => {
    const numDays = range === '7' ? 7 : range === '30' ? 30 : 30
    const now = new Date()

    // 1. Build chronological day buckets for the chosen timeframe
    const days = []
    const bucketMap = new Map()

    for (let i = numDays - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i)
      const dateKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      const label = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      days.push({ label, dateKey })
      bucketMap.set(dateKey, { revenue: 0, count: 0 })
    }

    let totalRev = 0

    // 2. Aggregate sales data into the proper date buckets
    ;(sales || []).forEach((s) => {
      const rawDate = s.sales_date || s.sale_date || s.created_at
      if (!rawDate) return
      let dateKey = null
      if (typeof rawDate === 'string' && /^\d{4}-\d{2}-\d{2}/.test(rawDate)) {
        dateKey = rawDate.substring(0, 10)
      } else {
        const d = new Date(rawDate)
        if (isNaN(d.getTime())) return
        dateKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      }

      const rev = Number(s.revenue) || (Number(s.selling_price || 0) * Number(s.quantity_sold || 0)) || 0

      if (bucketMap.has(dateKey)) {
        const b = bucketMap.get(dateKey)
        b.revenue += rev
        b.count += 1
      }
      totalRev += rev
    })

    const lbls = days.map((d) => d.label)
    const pts = days.map((d) => {
      const b = bucketMap.get(d.dateKey)
      return metric === 'revenue' ? Math.round(b.revenue * 100) / 100 : b.count
    })

    // 3. Compute growth rate
    let growth = 12.5
    const mid = Math.floor(pts.length / 2)
    const firstHalf = pts.slice(0, mid).reduce((a, b) => a + b, 0) || 1
    const secondHalf = pts.slice(mid).reduce((a, b) => a + b, 0)
    growth = Math.round(((secondHalf - firstHalf) / firstHalf) * 100)
    if (isNaN(growth)) growth = 0

    // 4. Generate granular tracking rows for table tracking
    const trackingRows = days.map((d) => {
      const b = bucketMap.get(d.dateKey)
      const dayRev = b ? b.revenue : 0
      const dayOrders = b ? b.count : 0
      const aov = dayOrders > 0 ? dayRev / dayOrders : 0
      return {
        date: d.dateKey,
        label: d.label,
        revenue: dayRev,
        orders: dayOrders,
        aov: aov,
        status: dayOrders > 0 ? 'Active Sales' : 'No Activity',
      }
    }).reverse() // most recent first for tracking

    // 5. Calculate peak metrics
    const totalOrdersCount = days.reduce((sum, d) => sum + (bucketMap.get(d.dateKey)?.count || 0), 0)
    const peakDay = days.reduce((max, d) => {
      const r = bucketMap.get(d.dateKey)?.revenue || 0
      return r > (max.revenue || 0) ? { label: d.label, dateKey: d.dateKey, revenue: r } : max
    }, { label: '—', revenue: 0 })

    return {
      labels: lbls,
      dataPoints: pts,
      totalPeriodRevenue: totalRev,
      growthPct: growth,
      trackingRows,
      totalOrdersCount,
      peakDay,
    }
  }, [sales, metric, range])

  const trackingColumns = [
    { key: 'date', label: 'Date', sortable: true },
    { key: 'label', label: 'Day', sortable: true },
    {
      key: 'revenue',
      label: 'Daily Revenue',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 700, color: row.revenue > 0 ? '#10b981' : 'var(--erp-text-muted)' }}>
          ₹{Number(row.revenue).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
      ),
    },
    {
      key: 'orders',
      label: 'Orders Count',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600 }}>{row.orders}</span>
      ),
    },
    {
      key: 'aov',
      label: 'Average Order Value',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span>₹{Number(row.aov).toFixed(2)}</span>
      ),
    },
    {
      key: 'status',
      label: 'Activity',
      sortable: true,
      render: (row) => (
        <span
          style={{
            fontSize: '0.7rem',
            padding: '2px 8px',
            borderRadius: '4px',
            fontWeight: 600,
            background: row.orders > 0 ? 'var(--status-success-bg)' : 'var(--erp-surface-subtle)',
            color: row.orders > 0 ? 'var(--status-success-text)' : 'var(--erp-text-muted)',
            border: `1px solid ${row.orders > 0 ? 'var(--status-success-border)' : 'var(--erp-border)'}`,
          }}
        >
          {row.status}
        </span>
      ),
    },
  ]

  const kpiSummary = [
    {
      label: 'Total Revenue',
      value: `₹${Number(totalPeriodRevenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      subtext: `Selected ${range === 'all' ? 'All Time' : `${range} Days`}`,
      color: '#10b981',
    },
    {
      label: 'Total Orders',
      value: totalOrdersCount || 0,
      subtext: 'Executed customer transactions',
      color: 'var(--erp-brand)',
    },
    {
      label: 'Avg Daily Revenue',
      value: `₹${Math.round(totalPeriodRevenue / (labels.length || 1)).toLocaleString()}`,
      subtext: 'Daily average run rate',
      color: '#3b82f6',
    },
    {
      label: 'Peak Sales Day',
      value: peakDay.revenue > 0 ? `₹${Number(peakDay.revenue).toLocaleString()}` : '—',
      subtext: peakDay.label,
      color: '#f59e0b',
    },
  ]

  const chartData = {
    labels,
    datasets: [
      {
        label: metric === 'revenue' ? 'Sales Revenue (₹)' : 'Orders Processed',
        data: dataPoints,
        borderColor: '#10b981',
        backgroundColor: isDark ? 'rgba(16, 185, 129, 0.12)' : 'rgba(16, 185, 129, 0.18)',
        fill: true,
        tension: 0.38,
        pointBackgroundColor: '#10b981',
        pointBorderColor: isDark ? '#111827' : '#ffffff',
        pointBorderWidth: 2,
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
        displayColors: false,
        callbacks: {
          label: (context) => {
            const val = context.parsed.y
            return metric === 'revenue' ? `Revenue: ₹${val.toFixed(2)}` : `Orders: ${val}`
          },
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
          font: { size: 11 },
        },
      },
      y: {
        grid: {
          color: chartColors.gridColor,
        },
        ticks: {
          color: chartColors.textColor,
          font: { size: 11 },
          callback: (value) => (metric === 'revenue' ? `₹${value}` : value),
        },
      },
    },
  }

  const metricFilterControl = (
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
        className={`btn btn-sm ${metric === 'orders' ? 'btn-primary' : 'btn-subtle'}`}
        style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
        onClick={() => setMetric('orders')}
      >
        Orders (#)
      </button>
    </div>
  )

  return (
    <ChartCard
      title="Revenue Growth & Sales Trend"
      subtitle={`Total in range: ₹${totalPeriodRevenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
      icon={TrendingUp}
      badge={growthPct >= 0 ? `+${growthPct}% Growth` : `${growthPct}% Trend`}
      badgeType={growthPct >= 0 ? 'success' : 'warning'}
      kpiSummary={kpiSummary}
      trackingData={trackingRows}
      trackingColumns={trackingColumns}
      filterControls={metricFilterControl}
      periodFilter={{
        active: range,
        onChange: setRange,
        options: ['7', '30', '90', 'all'],
      }}
      actions={
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          {metricFilterControl}
          {/* Timeframe */}
          <select
            className="form-control"
            style={{ width: '105px', padding: '0.25rem 0.5rem', fontSize: '0.725rem' }}
            value={range}
            onChange={(e) => setRange(e.target.value)}
          >
            <option value="7">7 Days</option>
            <option value="30">30 Days</option>
            <option value="90">90 Days</option>
            <option value="all">All Time</option>
          </select>
        </div>
      }
      height={280}
    >
      {({ isFullscreen, height: chartHeight }) => (
        <div style={{ height: chartHeight || 280, position: 'relative', width: '100%' }}>
          <Line key={`${theme}-${metric}-${range}-${isFullscreen}`} data={chartData} options={options} />
        </div>
      )}
    </ChartCard>
  )
}
