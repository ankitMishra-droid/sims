import React, { useState, useMemo } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  RefreshCw,
  FolderOpen,
} from 'lucide-react'

export default function DataTable({
  columns = [],
  data = [],
  keyField = 'id',
  defaultPageSize = 10,
  searchQuery = '',
  searchFields = [],
  loading = false,
  emptyTitle = 'No records found',
  emptyMessage = 'There are no items matching your criteria.',
  emptyIcon: EmptyIcon = FolderOpen,
  onRowClick = null,
  actions = null,
}) {
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(defaultPageSize)
  const [sortKey, setSortKey] = useState(null)
  const [sortDirection, setSortDirection] = useState('asc') // 'asc' | 'desc'

  // Search filtering
  const filteredData = useMemo(() => {
    if (!searchQuery || !searchQuery.trim()) return data
    const q = searchQuery.toLowerCase().trim()
    return data.filter((item) => {
      if (searchFields.length > 0) {
        return searchFields.some((field) => {
          const val = item[field]
          return val !== undefined && val !== null && String(val).toLowerCase().includes(q)
        })
      }
      return Object.values(item).some(
        (val) => val !== undefined && val !== null && String(val).toLowerCase().includes(q)
      )
    })
  }, [data, searchQuery, searchFields])

  // Sorting
  const sortedData = useMemo(() => {
    if (!sortKey) return filteredData
    return [...filteredData].sort((a, b) => {
      let aVal = a[sortKey]
      let bVal = b[sortKey]

      if (aVal === undefined || aVal === null) aVal = ''
      if (bVal === undefined || bVal === null) bVal = ''

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }

      const aStr = String(aVal).toLowerCase()
      const bStr = String(bVal).toLowerCase()
      if (aStr < bStr) return sortDirection === 'asc' ? -1 : 1
      if (aStr > bStr) return sortDirection === 'asc' ? 1 : -1
      return 0
    })
  }, [filteredData, sortKey, sortDirection])

  // Pagination calculation
  const totalItems = sortedData.length
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))

  // Auto reset page if out of bounds
  const safeCurrentPage = Math.min(currentPage, totalPages)
  const startIndex = (safeCurrentPage - 1) * pageSize
  const paginatedData = useMemo(() => {
    return sortedData.slice(startIndex, startIndex + pageSize)
  }, [sortedData, startIndex, pageSize])

  const handleSort = (key) => {
    if (sortKey === key) {
      if (sortDirection === 'asc') setSortDirection('desc')
      else {
        setSortKey(null)
        setSortDirection('asc')
      }
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  return (
    <div className="table-card">
      <div className="table-responsive">
        <table className="erp-table">
          <thead>
            <tr>
              {columns.map((col) => {
                const isSortable = col.sortable !== false && col.key
                const isSorted = sortKey === col.key

                const isAction = col.key === 'actions' || col.key === 'action' || col.fixed === 'right'
                const colClasses = [
                  col.numeric ? 'numeric' : '',
                  col.center ? 'center' : '',
                  isAction ? 'actions-col' : '',
                  col.className || '',
                ].filter(Boolean).join(' ')

                return (
                  <th
                    key={col.key || col.label}
                    className={colClasses}
                    style={{
                      ...(isSortable ? { cursor: 'pointer', userSelect: 'none' } : {}),
                      ...(col.width ? { width: col.width, minWidth: col.width } : {}),
                      ...col.style,
                    }}
                    onClick={isSortable ? () => handleSort(col.key) : undefined}
                  >
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        justifyContent: col.numeric
                          ? 'flex-end'
                          : col.center || isAction
                          ? 'center'
                          : 'flex-start',
                      }}
                    >
                      <span>{col.label}</span>
                      {isSortable && (
                        <span style={{ color: isSorted ? 'var(--erp-brand)' : '#94a3b8' }}>
                          {isSorted ? (
                            sortDirection === 'asc' ? (
                              <ArrowUp size={13} />
                            ) : (
                              <ArrowDown size={13} />
                            )
                          ) : (
                            <ArrowUpDown size={12} />
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
            {loading ? (
              <tr>
                <td colSpan={columns.length} style={{ padding: '3rem', textAlign: 'center' }}>
                  <RefreshCw
                    size={28}
                    className="animate-spin"
                    color="var(--erp-brand)"
                    style={{ margin: '0 auto 0.5rem auto' }}
                  />
                  <div style={{ color: 'var(--erp-text-muted)', fontSize: '0.85rem' }}>
                    Loading data records...
                  </div>
                </td>
              </tr>
            ) : paginatedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>
                  <div className="empty-state" style={{ padding: '2.5rem 1rem' }}>
                    <div className="empty-state-icon">
                      <EmptyIcon size={24} />
                    </div>
                    <div className="empty-state-title" style={{ fontSize: '0.95rem' }}>
                      {emptyTitle}
                    </div>
                    <p className="empty-state-desc" style={{ fontSize: '0.8rem' }}>
                      {emptyMessage}
                    </p>
                  </div>
                </td>
              </tr>
            ) : (
              paginatedData.map((item, rowIdx) => (
                <tr
                  key={item[keyField] ?? rowIdx}
                  onClick={onRowClick ? () => onRowClick(item) : undefined}
                  style={onRowClick ? { cursor: 'pointer' } : {}}
                >
                  {columns.map((col) => {
                    const isAction = col.key === 'actions' || col.key === 'action' || col.fixed === 'right'
                    const tdClasses = [
                      col.numeric ? 'numeric' : '',
                      col.center ? 'center' : '',
                      isAction ? 'actions-col' : '',
                      col.className || '',
                    ].filter(Boolean).join(' ')

                    return (
                      <td
                        key={col.key || col.label}
                        className={tdClasses}
                        style={{
                          ...(col.width ? { width: col.width, minWidth: col.width } : {}),
                          ...col.style,
                        }}
                      >
                        {col.render ? col.render(item, rowIdx) : item[col.key]}
                      </td>
                    )
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {!loading && totalItems > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.75rem 1.25rem',
            backgroundColor: 'var(--erp-surface)',
            borderTop: '1px solid var(--erp-border)',
            flexWrap: 'wrap',
            gap: '0.75rem',
            fontSize: '0.8rem',
            color: 'var(--erp-text-muted)',
            transition: 'background-color 0.25s ease, border-color 0.25s ease',
          }}
        >
          {/* Range summary */}
          <div>
            Showing{' '}
            <strong style={{ color: 'var(--erp-text-main)' }}>
              {startIndex + 1}
            </strong>{' '}
            to{' '}
            <strong style={{ color: 'var(--erp-text-main)' }}>
              {Math.min(startIndex + pageSize, totalItems)}
            </strong>{' '}
            of <strong style={{ color: 'var(--erp-text-main)' }}>{totalItems}</strong> entries
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            {/* Page Size Selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span>Rows per page:</span>
              <select
                className="form-control"
                style={{ width: '65px', padding: '0.2rem 0.4rem', fontSize: '0.775rem' }}
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setCurrentPage(1)
                }}
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </div>

            {/* Navigation buttons */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              <button
                className="btn btn-subtle btn-sm"
                onClick={() => setCurrentPage(1)}
                disabled={safeCurrentPage === 1}
                title="First Page"
                style={{ padding: '0.25rem 0.45rem' }}
              >
                <ChevronsLeft size={15} />
              </button>
              <button
                className="btn btn-subtle btn-sm"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={safeCurrentPage === 1}
                title="Previous Page"
                style={{ padding: '0.25rem 0.45rem' }}
              >
                <ChevronLeft size={15} />
              </button>

              <span style={{ padding: '0 0.5rem', fontWeight: 600, color: 'var(--erp-text-main)' }}>
                Page {safeCurrentPage} of {totalPages}
              </span>

              <button
                className="btn btn-subtle btn-sm"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={safeCurrentPage === totalPages}
                title="Next Page"
                style={{ padding: '0.25rem 0.45rem' }}
              >
                <ChevronRight size={15} />
              </button>
              <button
                className="btn btn-subtle btn-sm"
                onClick={() => setCurrentPage(totalPages)}
                disabled={safeCurrentPage === totalPages}
                title="Last Page"
                style={{ padding: '0.25rem 0.45rem' }}
              >
                <ChevronsRight size={15} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
