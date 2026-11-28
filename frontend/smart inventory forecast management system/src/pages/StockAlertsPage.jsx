import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { AlertTriangle, RefreshCw, Plus, CheckCheck, Eye, X, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { addToast, setAlertsUnreadCount } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import Badge from '../components/Badge'
import { LoadingState, ErrorState, EmptyState } from '../components/common/StateBlocks'

export default function StockAlertsPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const products = useSelector(selectAllProducts)
  const currentWorkspace = useSelector((state) => state.auth.currentWorkspace)
  const role = String(currentWorkspace?.role || '').toLowerCase()
  const canDismiss = ['owner', 'admin', 'manager', 'analyst'].includes(role)

  const [alerts, setAlerts] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [dismissedCount, setDismissedCount] = useState(0)
  const [showDismissed, setShowDismissed] = useState(false)
  const [overstock, setOverstock] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyKey, setBusyKey] = useState('')
  const [error, setError] = useState('')
  const [selectedProductId, setSelectedProductId] = useState('')
  const [anomalies, setAnomalies] = useState(null)
  const [anomLoading, setAnomLoading] = useState(false)

  const loadLowStock = useCallback(async (includeDismissed = showDismissed) => {
    setLoading(true)
    setError('')
    try {
      const [alertData, overData] = await Promise.all([
        api.getStockAlerts(includeDismissed),
        api.getOverstockRisks().catch(() => []),
      ])
      setAlerts(Array.isArray(alertData?.alerts) ? alertData.alerts : [])
      const unread = Number(alertData?.unread_count || 0)
      setUnreadCount(unread)
      dispatch(setAlertsUnreadCount(unread))
      setDismissedCount(Number(alertData?.dismissed_count || 0))
      setOverstock(Array.isArray(overData) ? overData : [])
    } catch (err) {
      setError(err.message || 'Failed to load stock alerts.')
    } finally {
      setLoading(false)
    }
  }, [showDismissed, dispatch])

  useEffect(() => {
    dispatch(fetchProducts())
    const id = setTimeout(() => {
      loadLowStock(showDismissed)
    }, 0)
    return () => clearTimeout(id)
  }, [dispatch, showDismissed, loadLowStock])

  const activeProdId = selectedProductId || (products[0] ? String(products[0].id) : '')

  useEffect(() => {
    if (!activeProdId) return
    let active = true
    const run = async () => {
      setAnomLoading(true)
      try {
        const res = await api.getProductAnomalies(activeProdId, 90)
        if (active) setAnomalies(res)
      } catch {
        if (active) setAnomalies(null)
      } finally {
        if (active) setAnomLoading(false)
      }
    }
    run()
    return () => {
      active = false
    }
  }, [activeProdId])

  const handleMarkRead = async (alert) => {
    setBusyKey(alert.alert_key)
    try {
      await api.markStockAlertsRead({
        alert_key: alert.alert_key,
        product_id: alert.product_id,
      })
      await loadLowStock(showDismissed)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to mark alert read.' }))
    } finally {
      setBusyKey('')
    }
  }

  const handleMarkAllRead = async () => {
    setBusyKey('__all__')
    try {
      await api.markStockAlertsRead({ mark_all: true })
      dispatch(addToast({ type: 'success', message: 'All active alerts marked as read.' }))
      await loadLowStock(showDismissed)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to mark alerts read.' }))
    } finally {
      setBusyKey('')
    }
  }

  const handleDismiss = async (alert) => {
    setBusyKey(alert.alert_key)
    try {
      await api.dismissStockAlert({
        alert_key: alert.alert_key,
        alert_type: alert.alert_type,
        product_id: alert.product_id,
        severity: alert.severity,
        current_stock: alert.current_stock,
        cooldown_days: 7,
      })
      dispatch(addToast({ type: 'info', message: `Alert for ${alert.sku} dismissed for 7 days (reopens if stock drops).` }))
      await loadLowStock(showDismissed)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to dismiss alert.' }))
    } finally {
      setBusyKey('')
    }
  }

  const handleReopen = async (alert) => {
    setBusyKey(alert.alert_key)
    try {
      await api.reopenStockAlert(alert.alert_key)
      dispatch(addToast({ type: 'success', message: `Alert for ${alert.sku} restored.` }))
      await loadLowStock(showDismissed)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to restore alert.' }))
    } finally {
      setBusyKey('')
    }
  }

  const productOptions = useMemo(
    () => products.map((p) => ({ value: p.id, label: p.name, badge: p.sku })),
    [products]
  )

  const columns = [
    { key: 'sku', label: 'SKU', render: (p) => <span style={{ fontFamily: 'var(--font-mono)' }}>{p.sku}</span> },
    {
      key: 'name',
      label: 'Product',
      sortable: true,
      render: (p) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          {!p.is_read && p.status !== 'DISMISSED' && (
            <span
              title="Unread alert"
              aria-label="Unread alert"
              style={{ width: '8px', height: '8px', borderRadius: '999px', backgroundColor: '#ef4444', flexShrink: 0 }}
            />
          )}
          <span style={{ fontWeight: p.is_read ? 400 : 600 }}>{p.name}</span>
        </div>
      ),
    },
    {
      key: 'current_stock',
      label: 'On Hand',
      numeric: true,
      render: (p) => <strong style={{ color: p.current_stock === 0 ? '#dc2626' : '#d97706' }}>{p.current_stock}</strong>,
    },
    { key: 'reorder_level', label: 'Reorder Threshold', numeric: true },
    {
      key: 'status',
      label: 'Severity',
      center: true,
      render: (p) => (
        <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'center', flexWrap: 'wrap' }}>
          <Badge status={p.current_stock === 0 ? 'OUT OF STOCK' : 'LOW STOCK'} />
          {p.status === 'DISMISSED' && <Badge status="DRAFT" label="Dismissed" />}
        </div>
      ),
    },
    {
      key: 'action',
      label: 'Actions',
      center: true,
      render: (p) => (
        <div className="actions-group" style={{ justifyContent: 'center' }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => navigate(`/purchase-orders?supplier_id=${p.supplier_id || ''}`)}
          >
            <Plus size={12} /> Create PO
          </button>
          {!p.is_read && p.status !== 'DISMISSED' && (
            <button
              type="button"
              className="btn-action-icon"
              title="Mark as read"
              aria-label={`Mark ${p.sku} alert as read`}
              disabled={busyKey === p.alert_key}
              onClick={() => handleMarkRead(p)}
            >
              <Eye size={14} />
            </button>
          )}
          {canDismiss && p.status !== 'DISMISSED' && (
            <button
              type="button"
              className="btn-action-icon danger"
              title="Dismiss alert"
              aria-label={`Dismiss ${p.sku} alert`}
              disabled={busyKey === p.alert_key}
              onClick={() => handleDismiss(p)}
            >
              <X size={14} />
            </button>
          )}
          {canDismiss && p.status === 'DISMISSED' && (
            <button
              type="button"
              className="btn-action-icon"
              title="Restore alert"
              aria-label={`Restore ${p.sku} alert`}
              disabled={busyKey === p.alert_key}
              onClick={() => handleReopen(p)}
            >
              <RotateCcw size={14} />
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title="Stock Alerts & Demand Anomalies"
        subtitle={`${unreadCount} unread active alerts • ${dismissedCount} dismissed`}
        actions={
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
            {unreadCount > 0 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleMarkAllRead}
                disabled={busyKey === '__all__'}
              >
                <CheckCheck size={14} />
                <span>Mark All Read</span>
              </button>
            )}
            {dismissedCount > 0 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setShowDismissed((prev) => !prev)}
              >
                <span>{showDismissed ? 'Hide Dismissed' : `Show Dismissed (${dismissedCount})`}</span>
              </button>
            )}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadLowStock(showDismissed)} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          </div>
        }
      />

      {error && <ErrorState message={error} onRetry={() => loadLowStock(showDismissed)} />}

      <DataTable
        columns={columns}
        data={alerts}
        keyField="alert_key"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No low-stock alerts"
        emptyMessage="All active products are either healthy or dismissed."
      />

      {overstock.length > 0 && (
        <section className="section-card">
          <div className="section-card-header">
            <h2 className="section-card-title">Overstock & Dead-Stock Risk Alerts</h2>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/intelligence')}>
              Intelligence Overview
            </button>
          </div>
          <div className="table-responsive">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Product</th>
                  <th className="numeric">Position</th>
                  <th className="numeric">Excess Units</th>
                  <th className="numeric">Tied-Up Value</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {overstock.slice(0, 8).map((item) => (
                  <tr key={item.product_id}>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{item.sku}</td>
                    <td style={{ fontWeight: 600 }}>{item.product_name}</td>
                    <td className="numeric">{item.inventory_position}</td>
                    <td className="numeric">{item.overstock_excess_units}</td>
                    <td className="numeric">₹{Number(item.excess_inventory_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td><span className="badge badge-draft">{item.overstock_risk}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="section-card" style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
          <div>
            <h2 className="section-card-title">Product Demand Anomalies (90-Day Lookback)</h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>
              Powered by backend Z-score detection (/api/analytics/anomalies)
            </p>
          </div>
          <div style={{ width: '320px', maxWidth: '100%' }}>
            <SearchableSelect options={productOptions} value={activeProdId} onChange={(v) => setSelectedProductId(String(v))} />
          </div>
        </div>

        {anomLoading ? (
          <LoadingState message="Analyzing historical demand..." />
        ) : !anomalies || !anomalies.anomalies?.length ? (
          <EmptyState
            title="No anomalies detected"
            description="No unusual demand spikes or drops were detected for this product in the last 90 days."
            icon={AlertTriangle}
          />
        ) : (
          <div className="table-responsive">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Severity</th>
                  <th className="numeric">Observed</th>
                  <th className="numeric">Expected</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.anomalies.map((a, i) => (
                  <tr key={`${a.date}-${i}`}>
                    <td>{a.date}</td>
                    <td><Badge status={a.type === 'DEMAND_SPIKE' ? 'WARNING' : 'INFO'} label={a.type} /></td>
                    <td>{a.severity}</td>
                    <td className="numeric">{a.observed_value}</td>
                    <td className="numeric">{a.expected_value}</td>
                    <td>{a.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
