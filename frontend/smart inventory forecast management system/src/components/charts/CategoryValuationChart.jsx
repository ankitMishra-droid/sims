import React, { useState, useMemo, useCallback } from 'react'
import { Doughnut } from 'react-chartjs-2'
import { useSelector } from 'react-redux'
import {
  PieChart as PieIcon,
  Check,
  CheckSquare,
  Square,
  Filter,
  RotateCcw,
  Layers,
  Sparkles,
} from 'lucide-react'
import { getChartTheme } from './ChartSetup'
import ChartCard from './ChartCard'

const COLOR_PALETTE = [
  '#8b5cf6', // purple
  '#10b981', // emerald
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#6366f1', // indigo
  '#14b8a6', // teal
  '#f97316', // orange
  '#a855f7', // violet
]

export default function CategoryValuationChart({ products = [] }) {
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const [mode, setMode] = useState('value') // 'value' | 'count'
  const [onlySelected, setOnlySelected] = useState(false) // Toggle: Show only selected legends
  const [selectedMap, setSelectedMap] = useState({}) // { [categoryName]: boolean }
  const [hoveredCategory, setHoveredCategory] = useState(null)

  // 1. Calculate all categories with their valuations and counts
  const allCategories = useMemo(() => {
    if (!products || products.length === 0) return []

    const catMap = new Map()
    products.forEach((p) => {
      const cat = p.category ? p.category.trim() : 'General'
      const val = (Number(p.current_stock) || 0) * (Number(p.cost_price) || 0)
      const count = Number(p.current_stock) || 0

      if (!catMap.has(cat)) {
        catMap.set(cat, {
          name: cat,
          value: 0,
          count: 0,
          productCount: 0,
        })
      }
      const entry = catMap.get(cat)
      entry.value += val
      entry.count += count
      entry.productCount += 1
    })

    // Sort descending by value
    const sorted = Array.from(catMap.values()).sort((a, b) => b.value - a.value)

    return sorted.map((cat, index) => ({
      ...cat,
      color: COLOR_PALETTE[index % COLOR_PALETTE.length],
    }))
  }, [products])

  // Initialize or maintain selected categories map
  const activeSelected = useMemo(() => {
    if (allCategories.length === 0) return {}
    const result = {}
    let anyExplicit = false

    allCategories.forEach((cat) => {
      if (selectedMap[cat.name] !== undefined) {
        result[cat.name] = selectedMap[cat.name]
        anyExplicit = true
      }
    })

    // If no explicit selections exist yet, select all by default
    if (!anyExplicit) {
      allCategories.forEach((cat) => {
        result[cat.name] = true
      })
    } else {
      // Ensure new categories are defaulted to true
      allCategories.forEach((cat) => {
        if (result[cat.name] === undefined) {
          result[cat.name] = true
        }
      })
    }

    return result
  }, [allCategories, selectedMap])

  // Toggle single category selection
  const toggleCategory = useCallback((catName) => {
    setSelectedMap((prev) => {
      const current = prev[catName] !== undefined ? prev[catName] : true
      return {
        ...prev,
        [catName]: !current,
      }
    })
  }, [])

  // Select all categories
  const handleSelectAll = useCallback(() => {
    const updated = {}
    allCategories.forEach((c) => {
      updated[c.name] = true
    })
    setSelectedMap(updated)
  }, [allCategories])

  // Isolate a single category
  const handleSelectOnly = useCallback(
    (catName, e) => {
      e?.stopPropagation()
      const updated = {}
      allCategories.forEach((c) => {
        updated[c.name] = c.name === catName
      })
      setSelectedMap(updated)
    },
    [allCategories]
  )

  // Filtered categories for the chart
  const selectedCategories = useMemo(() => {
    return allCategories.filter((c) => activeSelected[c.name] !== false)
  }, [allCategories, activeSelected])

  // Categories shown in the legend (either only selected, or all)
  const displayedLegendCategories = useMemo(() => {
    if (onlySelected) {
      return selectedCategories
    }
    return allCategories
  }, [allCategories, selectedCategories, onlySelected])

  // Totals of currently selected categories
  const { totalSelectedValue, totalSelectedCount, totalAllValue, totalAllCount } = useMemo(() => {
    let selVal = 0
    let selCnt = 0
    let allVal = 0
    let allCnt = 0

    allCategories.forEach((c) => {
      allVal += c.value
      allCnt += c.count
      if (activeSelected[c.name] !== false) {
        selVal += c.value
        selCnt += c.count
      }
    })

    return {
      totalSelectedValue: selVal,
      totalSelectedCount: selCnt,
      totalAllValue: allVal,
      totalAllCount: allCnt,
    }
  }, [allCategories, activeSelected])

  // Doughnut chart dataset (only selected categories)
  const chartData = useMemo(() => {
    if (selectedCategories.length === 0) {
      return {
        labels: ['No category selected'],
        datasets: [
          {
            data: [1],
            backgroundColor: [isDark ? '#374151' : '#e2e8f0'],
            borderColor: isDark ? '#1f2937' : '#ffffff',
            borderWidth: 2,
          },
        ],
      }
    }

    const labels = selectedCategories.map((c) => c.name)
    const data = selectedCategories.map((c) =>
      mode === 'value' ? Math.round(c.value) : c.count
    )
    const bgColors = selectedCategories.map((c) => c.color)

    return {
      labels,
      datasets: [
        {
          data,
          backgroundColor: bgColors,
          borderColor: isDark ? '#111827' : '#ffffff',
          borderWidth: 2,
          hoverOffset: 8,
        },
      ],
    }
  }, [selectedCategories, mode, isDark])

  const chartOptions = useMemo(() => {
    return {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      plugins: {
        legend: {
          display: false, // We use our custom interactive legend
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
            label: (context) => {
              if (selectedCategories.length === 0) return ' None selected'
              const val = context.parsed
              const basis = mode === 'value' ? totalSelectedValue : totalSelectedCount
              const pct = basis > 0 ? ((val / basis) * 100).toFixed(1) : 0
              if (mode === 'value') {
                return ` ${context.label}: ₹${val.toLocaleString('en-IN')} (${pct}%)`
              }
              return ` ${context.label}: ${val.toLocaleString()} units (${pct}%)`
            },
          },
        },
      },
      onHover: (event, elements) => {
        if (elements && elements.length > 0 && selectedCategories.length > 0) {
          const index = elements[0].index
          setHoveredCategory(selectedCategories[index] || null)
        } else {
          setHoveredCategory(null)
        }
      },
      onClick: (event, elements) => {
        if (elements && elements.length > 0 && selectedCategories.length > 0) {
          const index = elements[0].index
          const cat = selectedCategories[index]
          if (cat) {
            toggleCategory(cat.name)
          }
        }
      },
    }
  }, [
    chartColors,
    selectedCategories,
    mode,
    totalSelectedValue,
    totalSelectedCount,
    toggleCategory,
  ])

  // Center display metric logic
  const centerMetric = useMemo(() => {
    const basisValue = mode === 'value' ? totalSelectedValue : totalSelectedCount

    if (hoveredCategory) {
      const catVal = mode === 'value' ? hoveredCategory.value : hoveredCategory.count
      const pct = basisValue > 0 ? ((catVal / basisValue) * 100).toFixed(1) : 0

      return {
        title: hoveredCategory.name,
        color: hoveredCategory.color,
        value:
          mode === 'value'
            ? `₹${Math.round(hoveredCategory.value).toLocaleString('en-IN')}`
            : `${hoveredCategory.count.toLocaleString()} pcs`,
        sub: `${pct}% of selected`,
      }
    }

    if (selectedCategories.length === 0) {
      return {
        title: 'Empty Selection',
        color: 'var(--erp-text-muted)',
        value: '0',
        sub: 'Click legend to select',
      }
    }

    const isAllSelected = selectedCategories.length === allCategories.length
    const currentVal = mode === 'value' ? totalSelectedValue : totalSelectedCount

    // Compact formatted large amount
    let formatted = ''
    if (mode === 'value') {
      if (currentVal >= 10000000) {
        formatted = `₹${(currentVal / 10000000).toFixed(2)} Cr`
      } else if (currentVal >= 100000) {
        formatted = `₹${(currentVal / 100000).toFixed(2)} L`
      } else {
        formatted = `₹${Math.round(currentVal).toLocaleString('en-IN')}`
      }
    } else {
      formatted = `${currentVal.toLocaleString()} pcs`
    }

    return {
      title: isAllSelected ? 'Total Value' : 'Selected Value',
      color: 'var(--erp-brand)',
      value: formatted,
      sub: `${selectedCategories.length} of ${allCategories.length} Categories`,
    }
  }, [
    hoveredCategory,
    selectedCategories,
    allCategories,
    mode,
    totalSelectedValue,
    totalSelectedCount,
  ])

  // Granular tracking rows for fullscreen table
  const categoryTrackingRows = useMemo(() => {
    const totalVal = allCategories.reduce((acc, c) => acc + c.value, 0) || 1
    return allCategories.map((c) => {
      const isSelected = selectedCategories.some((sc) => sc.name === c.name)
      const pct = Math.round((c.value / totalVal) * 100)
      return {
        name: c.name,
        productCount: c.productCount,
        count: c.count,
        value: Math.round(c.value),
        share: pct,
        status: isSelected ? 'Active Filter' : 'Hidden',
        color: c.color,
      }
    })
  }, [allCategories, selectedCategories])

  const categoryTrackingColumns = [
    {
      key: 'name',
      label: 'Category',
      sortable: true,
      render: (r) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span
            style={{
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              backgroundColor: r.color,
              display: 'inline-block',
            }}
          />
          <span style={{ fontWeight: 600 }}>{r.name}</span>
        </div>
      ),
    },
    {
      key: 'productCount',
      label: 'Products',
      numeric: true,
      sortable: true,
      render: (r) => <span>{r.productCount} SKUs</span>,
    },
    {
      key: 'count',
      label: 'Stock Units',
      numeric: true,
      sortable: true,
      render: (r) => <span>{r.count.toLocaleString()} units</span>,
    },
    {
      key: 'value',
      label: 'Asset Valuation',
      numeric: true,
      sortable: true,
      render: (r) => (
        <span style={{ fontWeight: 700, color: '#10b981' }}>
          ₹{r.value.toLocaleString('en-IN')}
        </span>
      ),
    },
    {
      key: 'share',
      label: '% Share',
      numeric: true,
      sortable: true,
      render: (r) => <span style={{ fontWeight: 600 }}>{r.share}%</span>,
    },
    {
      key: 'status',
      label: 'Selection',
      sortable: true,
      render: (r) => (
        <span
          style={{
            fontSize: '0.7rem',
            padding: '2px 8px',
            borderRadius: '4px',
            fontWeight: 600,
            background: r.status === 'Active Filter' ? 'var(--status-success-bg)' : 'var(--erp-surface-subtle)',
            color: r.status === 'Active Filter' ? 'var(--status-success-text)' : 'var(--erp-text-muted)',
            border: `1px solid ${r.status === 'Active Filter' ? 'var(--status-success-border)' : 'var(--erp-border)'}`,
          }}
        >
          {r.status}
        </span>
      ),
    },
  ]

  const categoryKpis = [
    {
      label: 'Selected Asset Value',
      value: `₹${Math.round(totalSelectedValue).toLocaleString('en-IN')}`,
      subtext: `${selectedCategories.length} active categories`,
      color: '#10b981',
    },
    {
      label: 'Selected Units',
      value: `${totalSelectedCount.toLocaleString()} units`,
      subtext: 'Current physical inventory',
      color: 'var(--erp-brand)',
    },
    {
      label: 'Top Category',
      value: allCategories[0]?.name || '—',
      subtext: `₹${Math.round(allCategories[0]?.value || 0).toLocaleString('en-IN')}`,
      color: '#3b82f6',
    },
    {
      label: 'Total Categories',
      value: `${allCategories.length} categories`,
      subtext: 'Catalog segments',
      color: '#f59e0b',
    },
  ]

  const modeFilterGroup = (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
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
          className={`btn btn-sm ${mode === 'value' ? 'btn-primary' : 'btn-subtle'}`}
          style={{ padding: '0.2rem 0.55rem', fontSize: '0.725rem', fontWeight: 600 }}
          onClick={() => setMode('value')}
          title="View financial asset allocation in Rupees"
        >
          Valuation (₹)
        </button>
        <button
          type="button"
          className={`btn btn-sm ${mode === 'count' ? 'btn-primary' : 'btn-subtle'}`}
          style={{ padding: '0.2rem 0.55rem', fontSize: '0.725rem', fontWeight: 600 }}
          onClick={() => setMode('count')}
          title="View physical unit quantity allocation"
        >
          Stock Units
        </button>
      </div>

      <button
        type="button"
        className={`btn btn-sm ${onlySelected ? 'btn-primary' : 'btn-subtle'}`}
        style={{ padding: '0.2rem 0.55rem', fontSize: '0.725rem', fontWeight: 600 }}
        onClick={() => setOnlySelected((prev) => !prev)}
      >
        {onlySelected ? '✓ Showing Selected Only' : 'Show All Legends'}
      </button>
    </div>
  )

  return (
    <ChartCard
      title="Category Asset Allocation"
      subtitle={`${selectedCategories.length} of ${allCategories.length} categories active`}
      icon={PieIcon}
      badge={
        mode === 'value'
          ? `₹${Math.round(totalSelectedValue).toLocaleString('en-IN')}`
          : `${totalSelectedCount.toLocaleString()} Units`
      }
      badgeType="info"
      kpiSummary={categoryKpis}
      trackingData={categoryTrackingRows}
      trackingColumns={categoryTrackingColumns}
      filterControls={modeFilterGroup}
      actions={modeFilterGroup}
      height={310}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          height: '100%',
          width: '100%',
          gap: '1rem',
        }}
      >
        {/* LEFT COLUMN: Perfectly Centered Doughnut Chart with Metric in Middle */}
        <div
          style={{
            position: 'relative',
            flex: '1 1 52%',
            height: '100%',
            minWidth: '160px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onMouseLeave={() => setHoveredCategory(null)}
        >
          <div style={{ width: '100%', height: '100%', position: 'relative' }}>
            <Doughnut
              key={`${theme}-${mode}-${selectedCategories.map((c) => c.name).join(',')}`}
              data={chartData}
              options={chartOptions}
            />
          </div>

          {/* EXACT MATHEMATICAL CENTER DISPLAY */}
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              textAlign: 'center',
              pointerEvents: 'none',
              maxWidth: '65%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 2,
            }}
          >
            <div
              style={{
                fontSize: '0.675rem',
                color: hoveredCategory ? centerMetric.color : 'var(--erp-text-muted)',
                textTransform: 'uppercase',
                fontWeight: 700,
                letterSpacing: '0.4px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '120px',
                lineHeight: 1.2,
                marginBottom: '2px',
              }}
            >
              {centerMetric.title}
            </div>

            <div
              style={{
                fontSize: '1.15rem',
                fontWeight: 800,
                color: 'var(--erp-text-main)',
                lineHeight: 1.15,
                letterSpacing: '-0.3px',
              }}
            >
              {centerMetric.value}
            </div>

            <div
              style={{
                fontSize: '0.65rem',
                color: 'var(--erp-text-muted)',
                fontWeight: 600,
                marginTop: '3px',
                whiteSpace: 'nowrap',
              }}
            >
              {centerMetric.sub}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Interactive Legend with 'Only Selected' toggle */}
        <div
          style={{
            flex: '1 1 48%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            borderLeft: '1px solid var(--erp-border)',
            paddingLeft: '0.875rem',
            overflow: 'hidden',
          }}
        >
          {/* Legend Controls Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: '0.45rem',
              borderBottom: '1px solid var(--erp-border)',
              marginBottom: '0.35rem',
              gap: '0.5rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <Layers size={13} color="var(--erp-brand)" />
              <span
                style={{
                  fontSize: '0.725rem',
                  fontWeight: 700,
                  color: 'var(--erp-text-main)',
                }}
              >
                Legends ({selectedCategories.length})
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              {/* Toggle: Show only selected legends */}
              <button
                type="button"
                className={`btn btn-sm ${onlySelected ? 'btn-primary' : 'btn-subtle'}`}
                style={{
                  padding: '0.15rem 0.45rem',
                  fontSize: '0.675rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '3px',
                }}
                onClick={() => setOnlySelected((prev) => !prev)}
                title={
                  onlySelected
                    ? 'Showing only selected categories. Click to show all.'
                    : 'Click to filter and show ONLY selected category legends.'
                }
              >
                <Filter size={11} />
                {onlySelected ? 'Selected Only' : 'All Legends'}
              </button>

              {/* Quick Reset / Select All */}
              {selectedCategories.length < allCategories.length && (
                <button
                  type="button"
                  className="btn btn-subtle btn-sm"
                  style={{
                    padding: '0.15rem 0.35rem',
                    fontSize: '0.675rem',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                  onClick={handleSelectAll}
                  title="Select all categories"
                >
                  <RotateCcw size={11} />
                </button>
              )}
            </div>
          </div>

          {/* Scrollable Legend Items */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              paddingRight: '0.25rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.3rem',
            }}
          >
            {displayedLegendCategories.length === 0 ? (
              <div
                style={{
                  padding: '1rem',
                  textAlign: 'center',
                  color: 'var(--erp-text-muted)',
                  fontSize: '0.75rem',
                }}
              >
                No categories selected.
                <div style={{ marginTop: '0.5rem' }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    style={{ fontSize: '0.7rem', padding: '0.2rem 0.6rem' }}
                    onClick={handleSelectAll}
                  >
                    Select All
                  </button>
                </div>
              </div>
            ) : (
              displayedLegendCategories.map((cat) => {
                const isSelected = activeSelected[cat.name] !== false
                const isHovered = hoveredCategory?.name === cat.name
                const catVal = mode === 'value' ? cat.value : cat.count
                const totalBasis = mode === 'value' ? totalSelectedValue : totalSelectedCount
                const pct =
                  isSelected && totalBasis > 0
                    ? ((catVal / totalBasis) * 100).toFixed(1)
                    : totalAllValue > 0
                    ? ((cat.value / totalAllValue) * 100).toFixed(1)
                    : 0

                return (
                  <div
                    key={cat.name}
                    onClick={() => toggleCategory(cat.name)}
                    onMouseEnter={() => setHoveredCategory(cat)}
                    onMouseLeave={() => setHoveredCategory(null)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.3rem 0.45rem',
                      borderRadius: '5px',
                      cursor: 'pointer',
                      backgroundColor: isHovered
                        ? 'var(--erp-surface-subtle)'
                        : isSelected
                        ? 'transparent'
                        : 'var(--erp-surface-subtle)',
                      opacity: isSelected ? 1 : 0.45,
                      border: isHovered
                        ? `1px solid ${cat.color}`
                        : '1px solid transparent',
                      transition: 'all 0.15s ease',
                    }}
                    title={`Click to ${isSelected ? 'deselect' : 'select'} ${cat.name}`}
                  >
                    {/* Color dot + Name */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        overflow: 'hidden',
                        maxWidth: '65%',
                      }}
                    >
                      <span
                        style={{
                          width: '9px',
                          height: '9px',
                          borderRadius: '50%',
                          backgroundColor: cat.color,
                          flexShrink: 0,
                          boxShadow: isSelected ? `0 0 6px ${cat.color}66` : 'none',
                        }}
                      />
                      <span
                        style={{
                          fontSize: '0.725rem',
                          fontWeight: isSelected ? 600 : 400,
                          color: isSelected ? 'var(--erp-text-main)' : 'var(--erp-text-muted)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          textDecoration: isSelected ? 'none' : 'line-through',
                        }}
                      >
                        {cat.name}
                      </span>
                    </div>

                    {/* Value + Share % */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        fontSize: '0.7rem',
                        flexShrink: 0,
                      }}
                    >
                      <span
                        style={{
                          fontWeight: 700,
                          color: isSelected ? 'var(--erp-text-main)' : 'var(--erp-text-muted)',
                        }}
                      >
                        {mode === 'value'
                          ? `₹${Math.round(cat.value).toLocaleString('en-IN')}`
                          : `${cat.count} pcs`}
                      </span>
                      <span
                        style={{
                          fontSize: '0.65rem',
                          color: isSelected ? cat.color : 'var(--erp-text-muted)',
                          fontWeight: 700,
                          minWidth: '32px',
                          textAlign: 'right',
                        }}
                      >
                        {pct}%
                      </span>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* Footer Hint */}
          <div
            style={{
              paddingTop: '0.35rem',
              borderTop: '1px solid var(--erp-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '0.65rem',
              color: 'var(--erp-text-muted)',
            }}
          >
            <span>Hover/Click items to inspect</span>
            <span style={{ fontWeight: 600, color: 'var(--erp-brand)' }}>
              {mode === 'value'
                ? `₹${Math.round(totalSelectedValue).toLocaleString('en-IN')}`
                : `${totalSelectedCount} units`}
            </span>
          </div>
        </div>
      </div>
    </ChartCard>
  )
}
