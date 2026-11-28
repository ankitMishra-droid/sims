import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  ShoppingCart,
  RefreshCw,
  Check,
  XCircle,
  ExternalLink,
  AlertTriangle,
  Info,
} from 'lucide-react'
import { api } from '../api'
import { addToast } from '../store/uiSlice'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import Modal from '../components/Modal'
import { LoadingState, EmptyState, ErrorState } from '../components/common/StateBlocks'

export default function ReorderPlannerPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const user = useSelector((state) => state.auth.user)
  const currentWorkspace = useSelector((state) => state.auth.currentWorkspace)

  const effectiveRole = String(currentWorkspace?.role || user?.role || '').toLowerCase()
  const canCreatePo = ['owner', 'admin', 'manager'].includes(effectiveRole)
  const canWriteIntel = ['owner', 'admin', 'manager', 'analyst'].includes(effectiveRole)

  const [recommendations, setRecommendations] = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState(null)

  const [statusFilter, setStatusFilter] = useState('OPEN')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [serviceLevel, setServiceLevel] = useState(0.95)

  // Modal state for PO Confirmation (never creates PO blindly)
  const [poModalRec, setPoModalRec] = useState(null)
  const [poForm, setPoForm] = useState({
    supplier_id: '',
    ordered_quantity: 1,
    expected_delivery_date: '',
    notes: '',
  })
  const [submittingPo, setSubmittingPo] = useState(false)
  const [poError, setPoError] = useState('')

  // Explanation drawer/modal
  const [detailRec, setDetailRec] = useState(null)

  const loadData = useCallback(
    async (syncNow = true, sl = serviceLevel, status = statusFilter, recType = typeFilter) => {
      if (syncNow) setSyncing(true)
      setLoading(true)
      setError(null)
      try {
        const [recList, supList] = await Promise.all([
          api.getIntelligenceRecommendations({
            status,
            recommendationType: recType,
            sync: syncNow,
            serviceLevel: sl,
          }),
          api.getSuppliers(),
        ])
        setRecommendations(Array.isArray(recList) ? recList : [])
        setSuppliers(Array.isArray(supList) ? supList : [])
      } catch (err) {
        const msg = err.message || 'Failed to load replenishment recommendations.'
        setError(msg)
        dispatch(addToast({ type: 'error', message: msg }))
      } finally {
        setLoading(false)
        setSyncing(false)
      }
    },
    [dispatch, serviceLevel, statusFilter, typeFilter]
  )

  useEffect(() => {
    const id = setTimeout(() => {
      loadData(true, serviceLevel, statusFilter, typeFilter)
    }, 0)
    return () => clearTimeout(id)
  }, [serviceLevel, statusFilter, typeFilter, loadData])

  const openPoConfirmationModal = (rec) => {
    const defaultSupId = rec.supplier_id || suppliers[0]?.id || ''
    const leadDays = Math.max(1, Math.round(Number(rec.lead_time_days || 7)))
    const eta = new Date(Date.now() + leadDays * 86400000).toISOString().slice(0, 10)
    setPoForm({
      supplier_id: defaultSupId ? String(defaultSupId) : '',
      ordered_quantity: rec.adjusted_order_qty || rec.suggested_order_qty || 1,
      expected_delivery_date: eta,
      notes: `Replenishment Recommendation #${rec.id}: ${rec.explanation_summary?.slice(0, 140) || ''}`,
    })
    setPoError('')
    setPoModalRec(rec)
  }

  const handleConfirmCreatePo = async (e) => {
    e.preventDefault()
    if (!poModalRec || submittingPo) return
    setPoError('')

    const qty = parseInt(poForm.ordered_quantity, 10)
    if (!poForm.supplier_id) {
      setPoError('Please select a supplier before creating the Draft Purchase Order.')
      return
    }
    if (isNaN(qty) || qty <= 0) {
      setPoError('Order quantity must be greater than zero.')
      return
    }

    setSubmittingPo(true)
    try {
      const res = await api.convertIntelligenceRecommendationToPo(poModalRec.id, {
        supplier_id: Number(poForm.supplier_id),
        ordered_quantity: qty,
        expected_delivery_date: poForm.expected_delivery_date || null,
        notes: poForm.notes,
        confirmed: true,
      })
      dispatch(
        addToast({
          type: 'success',
          message: res.message || `Draft PO ${res.order_number} created.`,
        })
      )
      setPoModalRec(null)
      await loadData(false)
    } catch (err) {
      setPoError(err.message || 'Failed to create Draft PO.')
    } finally {
      setSubmittingPo(false)
    }
  }

  const handleAccept = async (rec) => {
    try {
      await api.acceptIntelligenceRecommendation(rec.id)
      dispatch(addToast({ type: 'success', message: `Accepted recommendation for ${rec.product_name}.` }))
      await loadData(false)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to accept recommendation' }))
    }
  }

  const handleDismiss = async (rec) => {
    try {
      await api.dismissIntelligenceRecommendation(rec.id, 'Dismissed from Replenishment Planner')
      dispatch(addToast({ type: 'info', message: `Dismissed recommendation for ${rec.product_name}.` }))
      await loadData(false)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to dismiss recommendation' }))
    }
  }

  const urgencyBadgeStyle = (urgency) => {
    if (urgency === 'CRITICAL') return { bg: '#fee2e2', color: '#b91c1c' }
    if (urgency === 'HIGH') return { bg: '#fef3c7', color: '#b45309' }
    if (urgency === 'MEDIUM') return { bg: '#e0f2fe', color: '#0369a1' }
    return { bg: '#f1f5f9', color: '#475569' }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title={t('nav.reorderSuggestions')}
        subtitle="Explainable, persisted replenishment & risk queue driven by inventory position (On-Hand + Incoming POs), rolling demand forecasts, and empirical lead times."
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => loadData(true)}
            disabled={syncing || loading}
          >
            <RefreshCw size={15} className={syncing ? 'spin-icon' : ''} />
            <span>{syncing ? 'Recalculating...' : 'Sync Recommendations'}</span>
          </button>
        }
      />

      {/* Filter Bar */}
      <section className="section-card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '0.875rem' }}>
          <div className="form-group">
            <label className="form-label" htmlFor="rec-status-filter">Lifecycle Status</label>
            <select
              id="rec-status-filter"
              className="form-control"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="OPEN">Open (New / Viewed / Accepted)</option>
              <option value="NEW">New Only</option>
              <option value="ACCEPTED">Accepted</option>
              <option value="CONVERTED_TO_PO">Converted to PO</option>
              <option value="DISMISSED">Dismissed</option>
              <option value="EXPIRED">Expired / Resolved</option>
              <option value="ALL">All History</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="rec-type-filter">Category</label>
            <select
              id="rec-type-filter"
              className="form-control"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="ALL">All Categories</option>
              <option value="REORDER_NOW">Reorder Now</option>
              <option value="LOW_STOCK_RISK">Low Stock (Incoming Covers)</option>
              <option value="OVERSTOCK_ALERT">Overstock / Dead Stock</option>
              <option value="SUPPLIER_LEAD_TIME_RISK">Supplier Lead-Time Risk</option>
              <option value="DEMAND_INCREASING">Demand Increasing</option>
              <option value="DEMAND_DECREASING">Demand Decreasing</option>
              <option value="COLD_START_REVIEW">Cold Start Review</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="rec-sl-filter">Target Service Level</label>
            <select
              id="rec-sl-filter"
              className="form-control"
              value={serviceLevel}
              onChange={(e) => setServiceLevel(Number(e.target.value))}
            >
              <option value={0.9}>90% (Lean Buffer)</option>
              <option value={0.95}>95% (Balanced Standard)</option>
              <option value={0.98}>98% (High Availability)</option>
              <option value={0.99}>99% (Critical Buffer)</option>
            </select>
          </div>
        </div>
      </section>

      {error && <ErrorState message={error} onRetry={() => loadData(true)} />}

      {loading ? (
        <LoadingState message="Synchronizing inventory position, supplier lead times, and replenishment recommendations..." />
      ) : recommendations.length === 0 ? (
        <EmptyState
          title="No recommendations in this view"
          description="Try switching lifecycle status or click Sync Recommendations to recalculate."
        />
      ) : (
        <section className="section-card">
          <div className="table-responsive">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Urgency / Type</th>
                  <th className="numeric">Inventory Position</th>
                  <th className="numeric">ROP / Target</th>
                  <th className="numeric">Lead Time</th>
                  <th className="numeric">Cover</th>
                  <th className="numeric">Suggested Order</th>
                  <th>Status</th>
                  <th className="center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {recommendations.map((rec) => {
                  const uStyle = urgencyBadgeStyle(rec.urgency)
                  return (
                    <tr key={rec.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{rec.product_name}</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.74rem', color: 'var(--erp-text-muted)' }}>
                          {rec.sku} • {rec.avg_daily_demand}/day ({rec.data_sufficiency})
                        </div>
                      </td>
                      <td>
                        <span
                          className="badge"
                          style={{ background: uStyle.bg, color: uStyle.color, fontWeight: 700 }}
                        >
                          {rec.urgency} · {rec.recommendation_type}
                        </span>
                        <div style={{ fontSize: '0.76rem', color: 'var(--erp-text-secondary)', marginTop: '0.3rem', maxWidth: '280px' }}>
                          {rec.explanation_summary}
                        </div>
                      </td>
                      <td className="numeric">
                        <strong>{rec.inventory_position}</strong>
                        <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>
                          {rec.on_hand_stock} on hand + {rec.incoming_stock} in
                        </div>
                      </td>
                      <td className="numeric">
                        <div>ROP: <strong>{rec.reorder_point}</strong> (SS {rec.safety_stock})</div>
                        <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>
                          Target: {rec.target_stock_level}
                        </div>
                      </td>
                      <td className="numeric">
                        <strong>{rec.lead_time_days}d</strong>
                        <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>
                          ±{rec.lead_time_std_days}d ({rec.lead_time_source === 'po_receipt_history' ? 'Empirical' : 'Default'})
                        </div>
                      </td>
                      <td className="numeric">
                        {rec.days_of_cover_position != null ? `${rec.days_of_cover_position}d` : '—'}
                      </td>
                      <td className="numeric">
                        {rec.suggested_order_qty > 0 ? (
                          <div>
                            <strong style={{ fontSize: '0.95rem' }}>{rec.adjusted_order_qty || rec.suggested_order_qty}</strong>{' '}
                            <span style={{ fontSize: '0.74rem' }}>{rec.unit}</span>
                            <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>
                              ₹{Number(rec.estimated_order_cost || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </div>
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <span className={`badge ${rec.status === 'CONVERTED_TO_PO' ? 'badge-received' : 'badge-draft'}`}>
                          {rec.status}
                        </span>
                      </td>
                      <td className="center">
                        <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'center', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            title={t('intelligence.whySuggested')}
                            onClick={async () => {
                              try {
                                const detail = await api.getIntelligenceRecommendation(rec.id)
                                setDetailRec(detail)
                              } catch {
                                setDetailRec(rec)
                              }
                            }}
                          >
                            <Info size={13} />
                          </button>

                          {rec.status === 'CONVERTED_TO_PO' && rec.linked_purchase_order_id ? (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={() => navigate('/purchase-orders')}
                            >
                              <ExternalLink size={13} />
                              <span>{t('intelligence.viewPo')}</span>
                            </button>
                          ) : (
                            <>
                              {canCreatePo && rec.suggested_order_qty > 0 && !['DISMISSED', 'EXPIRED'].includes(rec.status) && (
                                <button
                                  type="button"
                                  className="btn btn-primary btn-sm"
                                  onClick={() => openPoConfirmationModal(rec)}
                                >
                                  <ShoppingCart size={13} />
                                  <span>{t('intelligence.reviewAndCreatePo')}</span>
                                </button>
                              )}
                              {canWriteIntel && ['NEW', 'VIEWED'].includes(rec.status) && (
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-sm"
                                  title={t('intelligence.accept')}
                                  onClick={() => handleAccept(rec)}
                                >
                                  <Check size={13} />
                                </button>
                              )}
                              {canWriteIntel && ['NEW', 'VIEWED', 'ACCEPTED'].includes(rec.status) && (
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-sm"
                                  title={t('intelligence.dismiss')}
                                  onClick={() => handleDismiss(rec)}
                                >
                                  <XCircle size={13} />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Review & Confirm PO Creation Modal */}
      <Modal
        isOpen={Boolean(poModalRec)}
        onClose={() => !submittingPo && setPoModalRec(null)}
        title={t('intelligence.confirmPoTitle')}
        subtitle={poModalRec ? `${poModalRec.sku} — ${poModalRec.product_name}` : ''}
        size="lg"
      >
        {poModalRec && (
          <form onSubmit={handleConfirmCreatePo}>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
              <div
                style={{
                  padding: '0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--erp-surface-subtle)',
                  fontSize: '0.83rem',
                  color: 'var(--erp-text-secondary)',
                }}
              >
                <strong>{t('intelligence.whySuggested')}:</strong> {poModalRec.explanation_summary}
                <div style={{ marginTop: '0.35rem', color: '#0369a1', fontWeight: 600 }}>
                  {t('intelligence.confirmPoSubtitle')}
                </div>
              </div>

              {poError && (
                <div className="form-error-banner">
                  <AlertTriangle size={16} />
                  <span>{poError}</span>
                </div>
              )}

              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="po-confirm-supplier">Supplier</label>
                  <select
                    id="po-confirm-supplier"
                    className="form-control"
                    required
                    value={poForm.supplier_id}
                    onChange={(e) => setPoForm({ ...poForm, supplier_id: e.target.value })}
                  >
                    <option value="">-- Select Active Supplier --</option>
                    {suppliers.map((s) => (
                      <option key={s.id} value={String(s.id)}>
                        {s.name} ({s.lead_time_days}d default)
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="po-confirm-qty">
                    {t('intelligence.adjustedQty')} ({poModalRec.unit}) <span className="required">*</span>
                  </label>
                  <input
                    id="po-confirm-qty"
                    type="number"
                    min="1"
                    required
                    className="form-control"
                    placeholder={t('placeholders.poQuantity', 'e.g. 100')}
                    value={poForm.ordered_quantity}
                    onChange={(e) => setPoForm({ ...poForm, ordered_quantity: e.target.value })}
                  />
                  <span style={{ fontSize: '0.74rem', color: 'var(--erp-text-muted)' }}>
                    Engine suggestion: {poModalRec.suggested_order_qty} {poModalRec.unit} • Est. Total: ₹
                    {Number((Number(poForm.ordered_quantity) || 0) * Number(poModalRec.unit_cost || 0)).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </span>
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="po-confirm-eta">Expected Delivery Date</label>
                  <input
                    id="po-confirm-eta"
                    type="date"
                    className="form-control"
                    value={poForm.expected_delivery_date}
                    onChange={(e) => setPoForm({ ...poForm, expected_delivery_date: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="po-confirm-notes">Purchase Order Notes</label>
                  <input
                    id="po-confirm-notes"
                    type="text"
                    className="form-control"
                    placeholder={t('placeholders.poNotes', 'e.g. PO-2026-001 urgent festive restock')}
                    value={poForm.notes}
                    onChange={(e) => setPoForm({ ...poForm, notes: e.target.value })}
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" disabled={submittingPo} onClick={() => setPoModalRec(null)}>
                {t('common.cancel')}
              </button>
              <button type="submit" className="btn btn-primary" disabled={submittingPo}>
                <ShoppingCart size={15} />
                <span>{submittingPo ? 'Creating Draft PO...' : 'Confirm & Create Draft PO'}</span>
              </button>
            </div>
          </form>
        )}
      </Modal>

      {/* Formula & Calculation Inspector Modal */}
      <Modal
        isOpen={Boolean(detailRec)}
        onClose={() => setDetailRec(null)}
        title={t('intelligence.whySuggested')}
        subtitle={detailRec ? `${detailRec.sku} — ${detailRec.product_name}` : ''}
      >
        {detailRec && (
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <p style={{ fontSize: '0.88rem', lineHeight: 1.5 }}>{detailRec.explanation_summary}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.6rem', fontSize: '0.82rem' }}>
              <div>On-Hand Stock: <strong>{detailRec.on_hand_stock}</strong></div>
              <div>Incoming PO Stock: <strong>{detailRec.incoming_stock}</strong></div>
              <div>Inventory Position: <strong>{detailRec.inventory_position}</strong></div>
              <div>Forecast Model: <strong>{detailRec.forecast_model_used || 'Auto'}</strong></div>
              <div>Daily Demand (σ): <strong>{detailRec.avg_daily_demand} (±{detailRec.demand_std_dev})</strong></div>
              <div>Effective Lead Time (σ): <strong>{detailRec.lead_time_days}d (±{detailRec.lead_time_std_days}d)</strong></div>
              <div>Safety Stock ({Math.round((detailRec.service_level || 0.95) * 100)}%): <strong>{detailRec.safety_stock}</strong></div>
              <div>Reorder Point / Target: <strong>{detailRec.reorder_point} / {detailRec.target_stock_level}</strong></div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
