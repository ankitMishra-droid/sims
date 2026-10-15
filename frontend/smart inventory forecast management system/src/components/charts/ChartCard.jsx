import React, { useState } from 'react'
import { Maximize2 } from 'lucide-react'
import FullScreenChartModal from './FullScreenChartModal'

export default function ChartCard({
  title,
  subtitle,
  icon: Icon,
  badge = null,
  badgeType = 'success', // 'success' | 'info' | 'warning' | 'neutral'
  actions = null,
  children,
  height = 300,
  // Fullscreen Tracking additions
  kpiSummary = [],
  trackingData = [],
  trackingColumns = [],
  filterControls = null,
  periodFilter = null,
}) {
  const [isFullscreen, setIsFullscreen] = useState(false)

  return (
    <>
      <div
        className="erp-chart-card"
        style={{
          background: 'var(--erp-surface)',
          border: '1px solid var(--erp-border)',
          borderRadius: '10px',
          padding: '1.25rem',
          boxShadow: 'var(--shadow-xs)',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
          transition: 'background-color 0.25s ease, border-color 0.25s ease, box-shadow 0.2s ease',
          position: 'relative',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.75rem',
            borderBottom: '1px solid var(--erp-border)',
            paddingBottom: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
            {Icon && (
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--erp-brand-subtle)',
                  color: 'var(--erp-brand)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon size={18} />
              </div>
            )}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <h3 style={{ fontSize: '0.975rem', color: 'var(--erp-text-main)', margin: 0 }}>
                  {title}
                </h3>
                {badge && (
                  <span
                    style={{
                      fontSize: '0.675rem',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor:
                        badgeType === 'success'
                          ? 'var(--status-success-bg)'
                          : badgeType === 'warning'
                          ? 'var(--status-warning-bg)'
                          : badgeType === 'info'
                          ? 'var(--status-info-bg)'
                          : 'var(--erp-surface-subtle)',
                      color:
                        badgeType === 'success'
                          ? 'var(--status-success-text)'
                          : badgeType === 'warning'
                          ? 'var(--status-warning-text)'
                          : badgeType === 'info'
                          ? 'var(--status-info-text)'
                          : 'var(--erp-text-muted)',
                      border: `1px solid ${
                        badgeType === 'success'
                          ? 'var(--status-success-border)'
                          : badgeType === 'warning'
                          ? 'var(--status-warning-border)'
                          : badgeType === 'info'
                          ? 'var(--status-info-border)'
                          : 'var(--erp-border)'
                      }`,
                    }}
                  >
                    {badge}
                  </span>
                )}
              </div>
              {subtitle && (
                <p style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', marginTop: '2px' }}>
                  {subtitle}
                </p>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {actions}

            {/* Fullscreen Expand Action Button */}
            <button
              type="button"
              className="chart-expand-btn"
              onClick={() => setIsFullscreen(true)}
              title="Open chart in Fullscreen with Tracking Filters & Data"
              aria-label={`Open ${title} in fullscreen`}
            >
              <Maximize2 size={13} />
              <span className="expand-text">Fullscreen</span>
            </button>
          </div>
        </div>

        {/* Body with responsive height & click-to-expand */}
        <div
          className="chart-interactive-body"
          onClick={(e) => {
            // Prevent expanding if clicking an interactive element (button, input, select, clickable legend)
            if (e.target.closest('button, input, select, a, [role="button"], .chart-no-fullscreen')) {
              return
            }
            setIsFullscreen(true)
          }}
          title="Click graph to open in Fullscreen Tracking Mode"
          style={{ height, position: 'relative', width: '100%', cursor: 'pointer' }}
        >
          {/* Subtle Hover Hint */}
          <div className="chart-hover-hint">
            <Maximize2 size={11} />
            <span>Click to expand full screen</span>
          </div>

          {typeof children === 'function' ? children({ isFullscreen: false, height }) : children}
        </div>
      </div>

      {/* Fullscreen Modal View */}
      {isFullscreen && (
        <FullScreenChartModal
          title={title}
          subtitle={subtitle}
          icon={Icon}
          badge={badge}
          badgeType={badgeType}
          kpiSummary={kpiSummary}
          trackingData={trackingData}
          trackingColumns={trackingColumns}
          filterControls={filterControls}
          periodFilter={periodFilter}
          onClose={() => setIsFullscreen(false)}
        >
          {typeof children === 'function'
            ? children({ isFullscreen: true, height: 440 })
            : children}
        </FullScreenChartModal>
      )}
    </>
  )
}

