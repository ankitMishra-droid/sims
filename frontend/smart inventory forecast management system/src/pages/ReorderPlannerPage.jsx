import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { ShoppingCart, RefreshCw, Filter, CheckCircle2 } from 'lucide-react'
import { api } from '../api'
import { addToast } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'
import { LoadingState, EmptyState, ErrorState } from '../components/common/StateBlocks'

export default function ReorderPlannerPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const user = useSelector((state) => state.auth.user)
  const canCreatePo = ['admin', 'manager'].includes(String(user?.role || '').toLowerCase())

  const [recommendations, setRecommendations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [serviceLevel, setServiceLevel] = useState(0.95)
  const [riskFilter, setRiskFilter] = useState('ALL')
  const [convertingId, setConvertingId] = useState(null)

  const loadRecommendations = useCallback(async (sl) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getReorderRecommendations(sl)
      setRecommendations(Array.isArray(data) ? data : [])
    } catch (err) {
      const msg = err.message || 'Failed to load recommendations'
      setError(msg)
      dispatch(addToast({ type: 'error', message: msg }))
    } finally {
      setLoading(false)
    }
  }, [dispatch])

  useEffect(() => {
    const id = setTimeout(() => {
      loadRecommendations(serviceLevel)
    }, 0)
    return () => clearTimeout(id)
  }, [serviceLevel, loadRecommendations])

  const handleCreatePo = async (rec) => {
    if (!rec.supplier_id) {
      dispatch(addToast({ type: 'error', message: 'No supplier attached to product. Please assign a supplier first.' }))
      return
    }

    setConvertingId(rec.product_id)
    try {
      const poPayload = {
        supplier_id: rec.supplier_id,
        items: [
          {
            product_id: rec.product_id,
            quantity: rec.recommended_order_quantity || 10,
          },
        ],
        notes: `Smart Reorder PO for ${rec.product_name} (Risk: ${rec.stockout_risk})`,
      }
      const res = await api.convertRecommendationToPo(poPayload)
      dispatch(addToast({ type: 'success', message: res.message || 'Purchase order created successfully!' }))
      // Refresh list
      loadRecommendations(serviceLevel)
      // Navigate to purchase orders page
      navigate('/purchase-orders')
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to create PO' }))
    } finally {
      setConvertingId(null)
    }
  }

  const filteredRecs = (Array.isArray(recommendations) ? recommendations : []).filter((r) => {
    if (riskFilter === 'ALL') return true
    return r.stockout_risk === riskFilter
  })

  const getRiskBadge = (risk) => {
    switch (risk) {
      case 'CRITICAL':
        return { label: 'CRITICAL', bg: '#fee2e2', color: '#b91c1c', border: '#f87171' }
      case 'HIGH':
        return { label: 'HIGH RISK', bg: '#fef3c7', color: '#b45309', border: '#fcd34d' }
      case 'OPTIMAL':
        return { label: 'OPTIMAL', bg: '#dcfce7', color: '#15803d', border: '#86efac' }
      case 'OVERSTOCK':
        return { label: 'OVERSTOCK', bg: '#e0e7ff', color: '#4338ca', border: '#a5b4fc' }
      default:
        return { label: risk, bg: '#f1f5f9', color: '#475569', border: '#cbd5e1' }
    }
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title="Smart Reorder Planner"
        subtitle="Automated Reorder Points (ROP), Safety Stock, Inventory Position & 1-Click Purchase Orders"
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => loadRecommendations(serviceLevel)}
            disabled={loading}
          >
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
            <span>Refresh Analysis</span>
          </button>
        }
      />

      {error && <ErrorState message={error} onRetry={() => loadRecommendations(serviceLevel)} />}

      {/* Controls Bar */}
      <div
        className="section-card"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        {/* Service Level Select */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--erp-text-muted)' }}>
            Target Service Level:
          </span>
          <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
            {[
              { val: 0.9, label: '90%' },
              { val: 0.95, label: '95% (Standard)' },
              { val: 0.98, label: '98%' },
              { val: 0.99, label: '99% (High)' },
            ].map((sl) => (
              <button
                key={sl.val}
                type="button"
                className={`btn btn-sm ${serviceLevel === sl.val ? 'btn-accent' : 'btn-secondary'}`}
                onClick={() => setServiceLevel(sl.val)}
              >
                {sl.label}
              </button>
            ))}
          </div>
        </div>

        {/* Risk Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <Filter size={16} style={{ color: 'var(--erp-text-muted)' }} />
          <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
            {['ALL', 'CRITICAL', 'HIGH', 'OPTIMAL', 'OVERSTOCK'].map((rf) => (
              <button
                key={rf}
                type="button"
                className={`btn btn-sm ${riskFilter === rf ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setRiskFilter(rf)}
              >
                {rf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Grid of Recommendation Cards */}
      {loading ? (
        <LoadingState message="Computing optimal safety stocks & reorder points..." />
      ) : filteredRecs.length === 0 ? (
        <EmptyState
          title="All Inventory Levels Optimal!"
          description="No products matching the selected filter currently require immediate replenishment."
          icon={CheckCircle2}
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '1.25rem' }}>
          {filteredRecs.map((rec) => {
            const badge = getRiskBadge(rec.stockout_risk)
            const isCriticalOrHigh = rec.stockout_risk === 'CRITICAL' || rec.stockout_risk === 'HIGH'
            return (
              <div
                key={rec.product_id}
                className="section-card"
                style={{
                  border: isCriticalOrHigh ? `1px solid ${badge.border}` : undefined,
                  boxShadow: isCriticalOrHigh ? '0 4px 12px rgba(239, 68, 68, 0.08)' : undefined,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem', marginBottom: '0.75rem' }}>
                    <div>
                      <h4 style={{ margin: '0 0 0.25rem', fontSize: 'var(--text-md)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--erp-text-main)' }}>
                        {rec.product_name}
                      </h4>
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--erp-text-muted)' }}>
                        SKU: <span style={{ fontFamily: 'var(--font-mono)' }}>{rec.sku}</span> | Supplier: {rec.supplier_name}
                      </span>
                    </div>

                    <span
                      style={{
                        fontSize: 'var(--text-xs)',
                        fontWeight: 'var(--font-weight-semibold)',
                        padding: '0.2rem 0.5rem',
                        borderRadius: 'var(--radius-sm)',
                        background: badge.bg,
                        color: badge.color,
                        border: `1px solid ${badge.border}`,
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {badge.label}
                    </span>
                  </div>

                  {/* Stock & Math Metrics */}
                  <div
                    className="tabular-nums"
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(2, 1fr)',
                      gap: '0.75rem',
                      padding: '0.75rem',
                      borderRadius: 'var(--radius-md)',
                      background: 'var(--erp-surface-subtle)',
                      marginBottom: '1rem',
                      fontSize: 'var(--text-sm)',
                    }}
                  >
                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>On-Hand / Incoming:</span>
                      <strong style={{ display: 'block', color: 'var(--erp-text-main)', fontSize: 'var(--text-md)', fontWeight: 'var(--font-weight-semibold)' }}>
                        {rec.current_stock} / +{rec.incoming_stock ?? 0} units
                      </strong>
                    </div>

                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>Inventory Position:</span>
                      <strong style={{ display: 'block', color: 'var(--erp-text-main)', fontSize: 'var(--text-md)', fontWeight: 'var(--font-weight-semibold)' }}>
                        {rec.inventory_position ?? rec.current_stock} units
                      </strong>
                    </div>

                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>Days Remaining:</span>
                      <strong
                        style={{
                          display: 'block',
                          color: rec.days_inventory_remaining < rec.lead_time_days ? '#ef4444' : 'var(--erp-text-main)',
                          fontSize: 'var(--text-md)',
                          fontWeight: 'var(--font-weight-semibold)',
                        }}
                      >
                        {rec.days_inventory_remaining} days
                      </strong>
                    </div>

                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>Reorder Point (ROP):</span>
                      <strong style={{ display: 'block', color: 'var(--erp-text-main)', fontWeight: 'var(--font-weight-semibold)' }}>
                        {rec.reorder_point} units
                      </strong>
                    </div>

                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>Safety Stock (SS):</span>
                      <strong style={{ display: 'block', color: '#10b981', fontWeight: 'var(--font-weight-semibold)' }}>
                        {rec.safety_stock} units
                      </strong>
                    </div>

                    <div>
                      <span style={{ color: 'var(--erp-text-muted)', fontSize: 'var(--text-xs)' }}>Daily Demand / Lead Time:</span>
                      <strong style={{ display: 'block', color: 'var(--erp-text-main)', fontWeight: 'var(--font-weight-semibold)' }}>
                        {rec.daily_predicted_demand}/day ({rec.lead_time_days}d)
                      </strong>
                    </div>
                  </div>
                </div>

                {/* Action button */}
                {rec.is_reorder_needed ? (
                  canCreatePo ? (
                    <button
                      type="button"
                      className="btn btn-accent"
                      onClick={() => handleCreatePo(rec)}
                      disabled={convertingId === rec.product_id || !rec.supplier_id}
                      title={!rec.supplier_id ? 'Assign a supplier to this product first' : undefined}
                      style={{ width: '100%' }}
                    >
                      <ShoppingCart size={16} />
                      <span>
                        {convertingId === rec.product_id
                          ? 'Creating Order...'
                          : !rec.supplier_id
                          ? 'Assign Supplier Before Ordering'
                          : `Order ${rec.recommended_order_quantity} Units (Est. ₹${rec.estimated_order_cost})`}
                      </span>
                    </button>
                  ) : (
                    <div
                      style={{
                        textAlign: 'center',
                        padding: '0.5rem',
                        fontSize: 'var(--text-sm)',
                        color: 'var(--erp-text-muted)',
                        borderTop: '1px solid var(--erp-border)',
                      }}
                    >
                      Recommended order: {rec.recommended_order_quantity} units (Manager/Admin role required to create PO)
                    </div>
                  )
                ) : (
                  <div
                    style={{
                      textAlign: 'center',
                      padding: '0.5rem',
                      fontSize: 'var(--text-sm)',
                      color: 'var(--erp-text-muted)',
                      borderTop: '1px solid var(--erp-border)',
                    }}
                  >
                    Inventory position is sufficient.
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
