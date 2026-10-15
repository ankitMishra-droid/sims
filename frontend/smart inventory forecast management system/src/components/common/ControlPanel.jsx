import React from 'react'
import { Search, RefreshCw, List, LayoutGrid } from 'lucide-react'
import CsvExportButton from './CsvExportButton'

export default function ControlPanel({
  moduleName = 'Module',
  activePage = 'Overview',
  itemCount = null,
  primaryAction = null, // { label, icon: Icon, onClick, id }
  secondaryAction = null,
  onRefresh = null,
  loading = false,
  searchQuery = '',
  onSearchChange = null,
  searchPlaceholder = 'Search records...',
  filters = null, // JSX for dropdown filters
  viewMode = null, // 'table' | 'kanban' | 'cards'
  onViewModeChange = null,
  exportData = null,
  exportColumns = null,
  exportFilename = 'export',
}) {
  return (
    <div className="erp-control-panel control-panel">
      {/* Top Header Row */}
      <div className="control-panel-top">
        <div className="breadcrumb-area">
          <span className="breadcrumb-root">{moduleName}</span>
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-active">{activePage}</span>
          {itemCount !== null && (
            <span style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)', marginLeft: '0.5rem' }}>
              ({itemCount} records)
            </span>
          )}
        </div>

        <div className="control-actions-group">
          {primaryAction && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={primaryAction.onClick}
              id={primaryAction.id}
            >
              {primaryAction.icon && <primaryAction.icon size={16} />}
              <span>{primaryAction.label}</span>
            </button>
          )}

          {secondaryAction && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={secondaryAction.onClick}
            >
              {secondaryAction.icon && <secondaryAction.icon size={16} />}
              <span>{secondaryAction.label}</span>
            </button>
          )}

          {exportData && (
            <CsvExportButton
              data={exportData}
              columns={exportColumns}
              filename={exportFilename}
            />
          )}

          {onRefresh && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRefresh}
              title="Refresh dataset"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          )}
        </div>
      </div>

      {/* Bottom Filter & View Switcher Row */}
      {(onSearchChange || filters || onViewModeChange) && (
        <div className="control-panel-bottom">
          <div className="search-filter-wrapper">
            {onSearchChange && (
              <div className="search-box">
                <Search size={16} color="#64748b" />
                <input
                  type="text"
                  placeholder={searchPlaceholder}
                  value={searchQuery}
                  onChange={(e) => onSearchChange(e.target.value)}
                />
              </div>
            )}

            {filters}
          </div>

          {onViewModeChange && (
            <div className="view-switcher">
              <button
                type="button"
                className={`view-btn ${viewMode === 'table' ? 'active' : ''}`}
                onClick={() => onViewModeChange('table')}
                title="Table View"
              >
                <List size={16} />
              </button>
              <button
                type="button"
                className={`view-btn ${viewMode !== 'table' ? 'active' : ''}`}
                onClick={() => onViewModeChange('kanban')}
                title="Grid / Kanban View"
              >
                <LayoutGrid size={16} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
