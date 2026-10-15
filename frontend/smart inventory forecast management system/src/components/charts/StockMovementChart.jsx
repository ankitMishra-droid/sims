import React, { useState, useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import { useSelector } from 'react-redux'
import { Boxes } from 'lucide-react'
import { getChartTheme } from './ChartSetup'
import ChartCard from './ChartCard'

export default function StockMovementChart({ sales = [], purchaseOrders = [], products = [] }) {
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const [range, setRange] = useState('7') // '7' | '14' | '30'
  const [movementFilter, setMovementFilter] = useState('all') // 'all' | 'inbound' | 'outbound' | 'procurement'

  const {
    labels,
    inboundData,
    outboundData,
    procurementData,
    netBalance,
    totalInbound,
    totalOutbound,
    totalProcured,
    trackingRows,
  } = useMemo(() => {
    const numDays = range === '14' ? 14 : range === '30' ? 30 : 7
    const days = []
    const inboundMap = new Map()
    const outboundMap = new Map()
    const orderedMap = new Map()

    for (let i = numDays - 1; i >= 0; i--) {
      const d = new Date()
      d.setDate(d.getDate() - i)
      const key = d.toLocaleDateString(undefined, { weekday: numDays > 7 ? undefined : 'short', month: 'short', day: 'numeric' })
      const dateKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      days.push({ label: key, dateKey })
      inboundMap.set(dateKey, 0)
      outboundMap.set(dateKey, 0)
      orderedMap.set(dateKey, 0)
    }

    const parseDateKey = (rawDate) => {
      if (!rawDate) return null
      if (typeof rawDate === 'string' && /^\d{4}-\d{2}-\d{2}/.test(rawDate)) {
        return rawDate.substring(0, 10)
      }
      const d = new Date(rawDate)
      if (isNaN(d.getTime())) return null
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    }

    // Map sales to outbound
    sales.forEach((s) => {
      const rawDate = s.sales_date || s.sale_date || s.created_at
      const dStr = parseDateKey(rawDate)
      if (dStr && outboundMap.has(dStr)) {
        outboundMap.set(dStr, outboundMap.get(dStr) + (Number(s.quantity_sold) || 0))
      }
    })

    // Map purchase orders: items received to inbound & ordered to procurement
    purchaseOrders.forEach((po) => {
      const rawDate = po.order_date || po.created_at
      const dStr = parseDateKey(rawDate)
      if (dStr) {
        if (orderedMap.has(dStr)) {
          const ordTotal = (po.items || []).reduce(
            (acc, itm) => acc + (Number(itm.ordered_quantity) || 0),
            0
          )
          orderedMap.set(dStr, orderedMap.get(dStr) + ordTotal)
        }
        if (inboundMap.has(dStr)) {
          const recTotal = (po.items || []).reduce(
            (acc, itm) => acc + (Number(itm.received_quantity) || 0),
            0
          )
          inboundMap.set(dStr, inboundMap.get(dStr) + recTotal)
        }
      }
    })

    const lbls = days.map((d) => d.label)
    const inPts = days.map((d) => inboundMap.get(d.dateKey) || 0)
    const outPts = days.map((d) => outboundMap.get(d.dateKey) || 0)
    const ordPts = days.map((d) => orderedMap.get(d.dateKey) || 0)

    const sumIn = inPts.reduce((a, b) => a + b, 0)
    const sumOut = outPts.reduce((a, b) => a + b, 0)
    const sumOrd = ordPts.reduce((a, b) => a + b, 0)
    const net = sumIn - sumOut

    // Granular tracking table rows
    const rows = days
      .map((d) => {
        const inUnits = inboundMap.get(d.dateKey) || 0
        const outUnits = outboundMap.get(d.dateKey) || 0
        const poUnits = orderedMap.get(d.dateKey) || 0
        const delta = inUnits - outUnits
        return {
          date: d.dateKey,
          label: d.label,
          inbound: inUnits,
          outbound: outUnits,
          procurement: poUnits,
          netDelta: delta,
          trend:
            delta > 0
              ? 'Stock Surplus (+)'
              : delta < 0
              ? 'Stock Outflow (-)'
              : inUnits === 0 && outUnits === 0
              ? 'Balanced / Idle'
              : 'Equal Flow',
        }
      })
      .reverse()

    return {
      labels: lbls,
      inboundData: inPts,
      outboundData: outPts,
      procurementData: ordPts,
      netBalance: net,
      totalInbound: sumIn,
      totalOutbound: sumOut,
      totalProcured: sumOrd,
      trackingRows: rows,
    }
  }, [sales, purchaseOrders, range])

  const trackingColumns = [
    { key: 'date', label: 'Date', sortable: true },
    { key: 'label', label: 'Day / Label', sortable: true },
    {
      key: 'inbound',
      label: 'Received Inflow',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: row.inbound > 0 ? '#10b981' : 'var(--erp-text-muted)' }}>
          {row.inbound > 0 ? `+${row.inbound} units` : '0'}
        </span>
      ),
    },
    {
      key: 'procurement',
      label: 'PO Procurement',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: row.procurement > 0 ? '#8b5cf6' : 'var(--erp-text-muted)' }}>
          {row.procurement > 0 ? `${row.procurement} units` : '0'}
        </span>
      ),
    },
    {
      key: 'outbound',
      label: 'Dispatched Sales',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span style={{ fontWeight: 600, color: row.outbound > 0 ? '#3b82f6' : 'var(--erp-text-muted)' }}>
          {row.outbound > 0 ? `-${row.outbound} units` : '0'}
        </span>
      ),
    },
    {
      key: 'netDelta',
      label: 'Net Daily Delta',
      numeric: true,
      sortable: true,
      render: (row) => (
        <span
          style={{
            fontWeight: 700,
            color: row.netDelta > 0 ? '#10b981' : row.netDelta < 0 ? '#ef4444' : 'var(--erp-text-muted)',
          }}
        >
          {row.netDelta > 0 ? `+${row.netDelta}` : row.netDelta}
        </span>
      ),
    },
    {
      key: 'trend',
      label: 'Flow Status',
      sortable: true,
      render: (row) => (
        <span
          style={{
            fontSize: '0.7rem',
            padding: '2px 8px',
            borderRadius: '4px',
            fontWeight: 600,
            background:
              row.netDelta > 0
                ? 'var(--status-success-bg)'
                : row.netDelta < 0
                ? 'var(--status-warning-bg)'
                : 'var(--erp-surface-subtle)',
            color:
              row.netDelta > 0
                ? 'var(--status-success-text)'
                : row.netDelta < 0
                ? 'var(--status-warning-text)'
                : 'var(--erp-text-muted)',
            border: `1px solid ${
              row.netDelta > 0
                ? 'var(--status-success-border)'
                : row.netDelta < 0
                ? 'var(--status-warning-border)'
                : 'var(--erp-border)'
            }`,
          }}
        >
          {row.trend}
        </span>
      ),
    },
  ]

  const kpiSummary = [
    {
      label: 'Total Inbound',
      value: `+${totalInbound} units`,
      subtext: 'Inventory received',
      color: '#10b981',
    },
    {
      label: 'Total Outbound',
      value: `-${totalOutbound} units`,
      subtext: 'Fulfilled sales items',
      color: '#3b82f6',
    },
    {
      label: 'Net Flow Delta',
      value: `${netBalance >= 0 ? `+${netBalance}` : netBalance} units`,
      subtext: netBalance >= 0 ? 'Inventory accumulation' : 'Depletion trend',
      color: netBalance >= 0 ? '#10b981' : '#f59e0b',
    },
    {
      label: 'Procurement Pipeline',
      value: `${totalProcured} units`,
      subtext: 'Purchase orders placed',
      color: '#8b5cf6',
    },
  ]

  // Filter datasets based on flow switcher
  const datasets = []
  if (movementFilter === 'all' || movementFilter === 'inbound') {
    datasets.push({
      label: 'Inbound (Received Stock)',
      data: inboundData,
      backgroundColor: isDark ? 'rgba(16, 185, 129, 0.75)' : '#10b981',
      borderRadius: 4,
      barPercentage: 0.65,
      categoryPercentage: 0.7,
    })
  }
  if (movementFilter === 'all' || movementFilter === 'procurement') {
    datasets.push({
      label: 'Procurement (POs Created)',
      data: procurementData,
      backgroundColor: isDark ? 'rgba(192, 132, 252, 0.75)' : '#8b5cf6',
      borderRadius: 4,
      barPercentage: 0.65,
      categoryPercentage: 0.7,
    })
  }
  if (movementFilter === 'all' || movementFilter === 'outbound') {
    datasets.push({
      label: 'Outbound (Dispatched Sales)',
      data: outboundData,
      backgroundColor: isDark ? 'rgba(59, 130, 246, 0.75)' : '#3b82f6',
      borderRadius: 4,
      barPercentage: 0.65,
      categoryPercentage: 0.7,
    })
  }

  const chartData = {
    labels,
    datasets,
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        align: 'end',
        labels: {
          color: chartColors.textColor,
          boxWidth: 12,
          boxHeight: 12,
          usePointStyle: true,
          font: { size: 11 },
        },
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
          label: (context) => `${context.dataset.label}: ${context.parsed.y} units`,
        },
      },
    },
    scales: {
      x: {
        grid: {
          display: false,
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
          callback: (val) => `${val} u`,
        },
      },
    },
  }

  const movementFilterControl = (
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
        className={`btn btn-sm ${movementFilter === 'all' ? 'btn-primary' : 'btn-subtle'}`}
        style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
        onClick={() => setMovementFilter('all')}
      >
        All Flows
      </button>
      <button
        type="button"
        className={`btn btn-sm ${movementFilter === 'inbound' ? 'btn-primary' : 'btn-subtle'}`}
        style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
        onClick={() => setMovementFilter('inbound')}
      >
        Inbound Only
      </button>
      <button
        type="button"
        className={`btn btn-sm ${movementFilter === 'outbound' ? 'btn-primary' : 'btn-subtle'}`}
        style={{ padding: '0.2rem 0.5rem', fontSize: '0.725rem' }}
        onClick={() => setMovementFilter('outbound')}
      >
        Outbound Only
      </button>
    </div>
  )

  return (
    <ChartCard
      title="Stock Movements: Inbound vs Outbound"
      subtitle={`${range}-day warehouse velocity & inventory flow`}
      icon={Boxes}
      badge={netBalance >= 0 ? `Net +${netBalance} units` : `Net ${netBalance} units`}
      badgeType={netBalance >= 0 ? 'success' : 'info'}
      kpiSummary={kpiSummary}
      trackingData={trackingRows}
      trackingColumns={trackingColumns}
      filterControls={movementFilterControl}
      periodFilter={{
        active: range,
        onChange: setRange,
        options: ['7', '14', '30'],
      }}
      actions={
        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          {movementFilterControl}
          <select
            className="form-control"
            style={{ width: '95px', padding: '0.25rem 0.5rem', fontSize: '0.725rem' }}
            value={range}
            onChange={(e) => setRange(e.target.value)}
          >
            <option value="7">7 Days</option>
            <option value="14">14 Days</option>
            <option value="30">30 Days</option>
          </select>
        </div>
      }
      height={280}
    >
      {({ isFullscreen, height: chartHeight }) => (
        <div style={{ height: chartHeight || 280, position: 'relative', width: '100%' }}>
          <Bar key={`${theme}-${range}-${movementFilter}-${isFullscreen}`} data={chartData} options={options} />
        </div>
      )}
    </ChartCard>
  )
}
