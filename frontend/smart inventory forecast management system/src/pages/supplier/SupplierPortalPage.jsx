import { useCallback, useEffect, useState } from 'react'
import { useDispatch } from 'react-redux'
import { PackageCheck, RefreshCw, CheckCircle2, Truck, AlertTriangle } from 'lucide-react'
import { api } from '../../api'
import { addToast } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'
import Badge from '../../components/Badge'
import { LoadingState, EmptyState, ErrorState } from '../../components/common/StateBlocks'

export default function SupplierPortalPage() {
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notesMap, setNotesMap] = useState({})
  const [updatingId, setUpdatingId] = useState(null)

  const loadOrders = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const list = await api.getSupplierPortalOrders()
      setOrders(Array.isArray(list) ? list : [])
    } catch (err) {
      setError(err.message || 'Failed to load shared purchase orders.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => {
      loadOrders()
    }, 0)
    return () => clearTimeout(id)
  }, [loadOrders])

  const handleStatusUpdate = async (orderId, supplierStatus) => {
    setUpdatingId(orderId)
    try {
      await api.updateSupplierOrderStatus(orderId, {
        supplier_status: supplierStatus,
        notes: (notesMap[orderId] || '').trim() || null,
      })
      dispatch(addToast({ type: 'success', message: `Order updated to ${supplierStatus}` }))
      await loadOrders()
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Status update failed.' }))
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('supplierPortal.title')}
        subtitle={t('supplierPortal.subtitle')}
        actions={
          <button type="button" className="btn btn-secondary" onClick={loadOrders} disabled={loading}>
            <RefreshCw size={15} />
            <span>{t('common.refresh')}</span>
          </button>
        }
      />

      {error && <ErrorState message={error} onRetry={loadOrders} />}

      {loading ? (
        <LoadingState message={t('common.loading')} />
      ) : orders.length === 0 ? (
        <EmptyState
          title="No Shared Orders"
          description={t('supplierPortal.empty')}
          icon={PackageCheck}
        />
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {orders.map((po) => {
            const locked = po.status === 'RECEIVED' || po.status === 'CANCELLED'
            return (
              <div key={po.id} className="section-card">
                <div className="section-card-header" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <h2 className="section-card-title">{po.order_number || `PO-${po.id}`}</h2>
                      <Badge status={po.status} />
                      {po.supplier_status && <Badge status="SENT" label={po.supplier_status} />}
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)', marginTop: '0.2rem' }}>
                      Buyer: <strong>{po.buyer_business_name}</strong> • Total: ₹{Number(po.total_amount || 0).toLocaleString()}
                    </div>
                  </div>
                </div>

                <div className="table-responsive" style={{ marginBottom: '0.9rem' }}>
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>Product</th>
                        <th>Ordered Qty</th>
                        <th>Received Qty</th>
                        <th>Unit Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(po.items || []).map((it) => (
                        <tr key={it.id}>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{it.sku || `#${it.product_id}`}</td>
                          <td>{it.product_name || 'Item'}</td>
                          <td>{it.ordered_quantity}</td>
                          <td>{it.received_quantity}</td>
                          <td>₹{Number(it.unit_cost || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {!locked && (
                  <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <input
                      type="text"
                      className="form-control"
                      style={{ flex: '1 1 220px' }}
                      placeholder="Optional dispatch note or tracking reference"
                      value={notesMap[po.id] ?? ''}
                      onChange={(e) => setNotesMap({ ...notesMap, [po.id]: e.target.value })}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={updatingId === po.id}
                      onClick={() => handleStatusUpdate(po.id, 'ACKNOWLEDGED')}
                    >
                      <CheckCircle2 size={14} />
                      <span>Acknowledge</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={updatingId === po.id}
                      onClick={() => handleStatusUpdate(po.id, 'DISPATCHED')}
                    >
                      <Truck size={14} />
                      <span>Mark Dispatched</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ color: 'var(--status-danger-text)' }}
                      disabled={updatingId === po.id}
                      onClick={() => handleStatusUpdate(po.id, 'ISSUE_REPORTED')}
                    >
                      <AlertTriangle size={14} />
                      <span>Report Issue</span>
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
