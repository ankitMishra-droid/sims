import React, { useState, useEffect, useMemo, useRef } from 'react'
import {
  X,
  Minimize2,
  Download,
  Search,
  Filter,
  BarChart3,
  Table as TableIcon,
  Layers,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Calendar,
  Sparkles,
  Camera,
} from 'lucide-react'

export default function FullScreenChartModal({
  title,
  subtitle,
  icon: Icon,
  badge = null,
  badgeType = 'success',
  kpiSummary = [],
  trackingData = [],
  trackingColumns = [],
  filterControls = null,
  periodFilter = null, // { active: string, onChange: function, options: array }
  onClose,
  children,
}) {
  const [activeTab, setActiveTab] = useState('split') // 'split' | 'chart' | 'table'
  const [searchQuery, setSearchQuery] = useState('')
  const [sortField, setSortField] = useState(null)
  const [sortAsc, setSortAsc] = useState(true)
  const chartContainerRef = useRef(null)

  // Close on Escape key press & prevent background scroll
  useEffect(() => {
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = originalOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  // Filter and sort tracking data
  const filteredAndSortedData = useMemo(() => {
    if (!trackingData || !trackingData.length) return []

    let data = [...trackingData]

    // 1. Text Search Filter across all fields
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      data = data.filter((row) => {
        return Object.values(row).some((val) => {
          if (val === null || val === undefined) return false
          return String(val).toLowerCase().includes(q)
        })
      })
    }

    // 2. Column Sorting
    if (sortField) {
      data.sort((a, b) => {
        const valA = a[sortField]
        const valB = b[sortField]

        if (valA === valB) return 0
        if (valA === null || valA === undefined) return 1
        if (valB === null || valB === undefined) return -1

        let cmp = 0
        if (typeof valA === 'number' && typeof valB === 'number') {
          cmp = valA - valB
        } else {
          cmp = String(valA).localeCompare(String(valB), undefined, { numeric: true })
        }
        return sortAsc ? cmp : -cmp
      })
    }

    return data
  }, [trackingData, searchQuery, sortField, sortAsc])

  // Handle column header click for sorting
  const handleSort = (key) => {
    if (sortField === key) {
      setSortAsc((prev) => !prev)
    } else {
      setSortField(key)
      setSortAsc(true)
    }
  }

  // Export data as CSV
  const handleExportCsv = () => {
    if (!filteredAndSortedData.length || !trackingColumns.length) return

    const headers = trackingColumns.map((c) => `"${c.label}"`).join(',')
    const rows = filteredAndSortedData.map((row) => {
      return trackingColumns
        .map((c) => {
          let val = row[c.key]
          if (typeof val === 'number') return val
          return `"${String(val ?? '').replace(/"/g, '""')}"`
        })
        .join(',')
    })

    const csvContent = 'data:text/csv;charset=utf-8,' + [headers, ...rows].join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    const safeTitle = (title || 'chart-data').toLowerCase().replace(/[^a-z0-9]/g, '_')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `${safeTitle}_tracking_${new Date().toISOString().slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  // Export chart as PNG
  const handleExportPng = () => {
    if (!chartContainerRef.current) return
    const canvas = chartContainerRef.current.querySelector('canvas')
    if (!canvas) return

    try {
      const dataUrl = canvas.toDataURL('image/png')
      const link = document.createElement('a')
      const safeTitle = (title || 'chart').toLowerCase().replace(/[^a-z0-9]/g, '_')
      link.download = `${safeTitle}_analytics_${new Date().toISOString().slice(0, 10)}.png`
      link.href = dataUrl
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    } catch (err) {
      console.warn('Canvas export not available:', err)
    }
  }

  return (
    <div
      className="fullscreen-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose()
        }
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`${title} Fullscreen Tracking`}
    >
      <div className="fullscreen-modal-container">
        {/* Modal Top Header */}
        <div className="fullscreen-modal-header">
          <div className="fullscreen-header-left">
            {Icon && (
              <div className="fullscreen-icon-badge">
                <Icon size={20} />
              </div>
            )}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <h2 className="fullscreen-title">{title}</h2>
                {badge && (
                  <span className={`fullscreen-badge fullscreen-badge-${badgeType}`}>
                    {badge}
                  </span>
                )}
                <span className="fullscreen-mode-pill">
                  <Sparkles size={11} /> Detailed Track Mode
                </span>
              </div>
              {subtitle && <p className="fullscreen-subtitle">{subtitle}</p>}
            </div>
          </div>

          <div className="fullscreen-header-actions">
            {/* View Mode Switcher */}
            <div className="fullscreen-view-switcher">
              <button
                type="button"
                className={`view-switcher-btn ${activeTab === 'split' ? 'active' : ''}`}
                onClick={() => setActiveTab('split')}
                title="Split view (Chart + Data Table)"
              >
                <Layers size={14} />
                <span>Split</span>
              </button>
              <button
                type="button"
                className={`view-switcher-btn ${activeTab === 'chart' ? 'active' : ''}`}
                onClick={() => setActiveTab('chart')}
                title="Chart Focus view"
              >
                <BarChart3 size={14} />
                <span>Chart</span>
              </button>
              <button
                type="button"
                className={`view-switcher-btn ${activeTab === 'table' ? 'active' : ''}`}
                onClick={() => setActiveTab('table')}
                title="Data Table Tracking view"
              >
                <TableIcon size={14} />
                <span>Table</span>
              </button>
            </div>

            {/* Export Buttons */}
            {trackingData.length > 0 && (
              <button
                type="button"
                className="fullscreen-tool-btn"
                onClick={handleExportCsv}
                title="Export tracked data rows to CSV file"
              >
                <Download size={14} />
                <span>CSV</span>
              </button>
            )}

            <button
              type="button"
              className="fullscreen-tool-btn"
              onClick={handleExportPng}
              title="Download high-resolution chart image"
            >
              <Camera size={14} />
              <span>Image</span>
            </button>

            {/* Close / Minimize Button */}
            <button
              type="button"
              className="fullscreen-close-btn"
              onClick={onClose}
              title="Exit fullscreen (Esc)"
              aria-label="Close fullscreen modal"
            >
              <Minimize2 size={16} />
            </button>
          </div>
        </div>

        {/* Global & Chart-Specific Filter Ribbon */}
        <div className="fullscreen-filter-ribbon">
          <div className="fullscreen-filters-left">
            {/* Period Filters */}
            {periodFilter && (
              <div className="fullscreen-period-group">
                <span className="filter-group-label">
                  <Calendar size={13} /> Period:
                </span>
                <div className="period-pill-group">
                  {(periodFilter.options || ['7', '30', '90', 'all']).map((opt) => {
                    const label =
                      opt === 'today'
                        ? 'Today'
                        : opt === '7'
                        ? '7 Days'
                        : opt === '14'
                        ? '14 Days'
                        : opt === '30'
                        ? '30 Days'
                        : opt === '90'
                        ? '90 Days'
                        : opt === '1y'
                        ? '1 Year'
                        : opt === 'all'
                        ? 'All Time'
                        : opt
                    const isActive = periodFilter.active === opt
                    return (
                      <button
                        key={opt}
                        type="button"
                        className={`period-pill-btn ${isActive ? 'active' : ''}`}
                        onClick={() => periodFilter.onChange(opt)}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Custom Chart Filters */}
            {filterControls && (
              <div className="fullscreen-custom-filters">{filterControls}</div>
            )}
          </div>

          {/* Quick Search within Table / Track Records */}
          {trackingData.length > 0 && (
            <div className="fullscreen-search-box">
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Track / Search records..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="fullscreen-search-input"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => setSearchQuery('')}
                  title="Clear search"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          )}
        </div>

        {/* Optional KPI Summary Ribbon */}
        {kpiSummary && kpiSummary.length > 0 && (
          <div className="fullscreen-kpi-ribbon">
            {kpiSummary.map((kpi, idx) => (
              <div key={idx} className="fullscreen-kpi-card">
                <div className="fullscreen-kpi-label">{kpi.label}</div>
                <div
                  className="fullscreen-kpi-value"
                  style={{ color: kpi.color || 'var(--erp-text-main)' }}
                >
                  {kpi.value}
                </div>
                {kpi.subtext && (
                  <div className="fullscreen-kpi-subtext">{kpi.subtext}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Modal Scrollable Body */}
        <div className="fullscreen-modal-body">
          {/* Chart Section */}
          {(activeTab === 'split' || activeTab === 'chart') && (
            <div
              className={`fullscreen-chart-section ${
                activeTab === 'chart' ? 'chart-full-height' : ''
              }`}
              ref={chartContainerRef}
            >
              {children}
            </div>
          )}

          {/* Data Tracking Table Section */}
          {(activeTab === 'split' || activeTab === 'table') && trackingColumns.length > 0 && (
            <div
              className={`fullscreen-table-section ${
                activeTab === 'table' ? 'table-full-height' : ''
              }`}
            >
              <div className="table-section-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <TableIcon size={15} color="var(--erp-brand)" />
                  <span className="table-header-title">Data Tracking & Audit Records</span>
                  <span className="table-count-badge">
                    {filteredAndSortedData.length}{' '}
                    {filteredAndSortedData.length === 1 ? 'record' : 'records'}
                  </span>
                </div>

                {searchQuery && (
                  <div className="table-filter-indicator">
                    Filtered by "{searchQuery}"
                  </div>
                )}
              </div>

              <div className="fullscreen-table-wrapper">
                <table className="fullscreen-data-table">
                  <thead>
                    <tr>
                      {trackingColumns.map((col) => {
                        const isSorted = sortField === col.key
                        return (
                          <th
                            key={col.key}
                            className={`${col.numeric ? 'numeric' : ''} ${
                              col.sortable !== false ? 'sortable' : ''
                            }`}
                            onClick={() => col.sortable !== false && handleSort(col.key)}
                            title={col.sortable !== false ? `Sort by ${col.label}` : ''}
                          >
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                                justifyContent: col.numeric ? 'flex-end' : 'flex-start',
                              }}
                            >
                              <span>{col.label}</span>
                              {col.sortable !== false && (
                                <span className="sort-icon-box">
                                  {isSorted ? (
                                    sortAsc ? (
                                      <ArrowUp size={12} color="var(--erp-brand)" />
                                    ) : (
                                      <ArrowDown size={12} color="var(--erp-brand)" />
                                    )
                                  ) : (
                                    <ArrowUpDown size={11} className="sort-neutral" />
                                  )}
                                </span>
                              )}
                            </div>
                          </th>
                        )
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAndSortedData.length === 0 ? (
                      <tr>
                        <td
                          colSpan={trackingColumns.length}
                          className="table-empty-message"
                        >
                          No matching records found for "{searchQuery}".
                        </td>
                      </tr>
                    ) : (
                      filteredAndSortedData.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {trackingColumns.map((col) => (
                            <td
                              key={col.key}
                              className={col.numeric ? 'numeric' : ''}
                            >
                              {col.render ? col.render(row) : row[col.key]}
                            </td>
                          ))}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
