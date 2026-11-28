import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import {
  BrainCircuit,
  AlertTriangle,
  RefreshCw,
  ShoppingCart,
  TrendingUp,
  Truck,
  PackageX,
  ArrowRight,
} from 'lucide-react'
import { api } from '../api'
import { addToast } from '../store/uiSlice'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import { LoadingState, ErrorState, EmptyState } from '../components/common/StateBlocks'

const SUFFICIENCY_LABELS = {
  SEASONAL: { label: 'Seasonal (>=56d)', bg: '#dcfce7', color: '#15803d' },
  ESTABLISHED: { label: 'Established (>=30d)', bg: '#dbeafe', color: '#1d4ed8' },
  INTERMITTENT: { label: 'Intermittent (Sparse)', bg: '#fef3c7', color: '#b45309' },
  LIMITED: { label: 'Limited (7-29d)', bg: '#f3e8ff', color: '#7e22ce' },
  NEW: { label: 'Cold Start (<7d)', bg: '#f1f5f9', color: '#475569' },
}

export default function IntelligenceOverviewPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t } = useTranslation()

  const [overview, setOverview] = useState(null)
  const [overstockItems, setOverstockItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const loadData = useCallback(async (sync = true) => {
    setLoading(true)
    setError('')
    try {
      const [ov, overstock] = await Promise.all([
        api.getIntelligenceOverview(null, sync),
        api.getOverstockRisks(),
      ])
      setOverview(ov)
      setOverstockItems(Array.isArray(overstock) ? overstock.slice(0, 8) : [])
    } catch (err) {
      setError(err.message || 'Failed to load inventory intelligence overview.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => {
      loadData(true)
    }, 0)
    return () => clearTimeout(id)
  }, [loadData])

  const handleRefreshAll = async () => {
    setRefreshing(true)
    try {
      const res = await api.refreshIntelligenceForecasts({ horizon_days: 30, sync_recommendations: true })
      dispatch(
        addToast({
          type: 'success',
          message: `Refreshed forecasts & recommendations across ${res.refreshed_count || 0} products.`,
        })
      )
      await loadData(false)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Refresh failed' }))
    } finally {
      setRefreshing(false)
    }
  }

  const riskBreakdown = overview?.stockout_risk_breakdown || {}
  const criticalAndHigh = (riskBreakdown.CRITICAL || 0) + (riskBreakdown.HIGH || 0)
  const topRecs = overview?.top_recommendations || []
  const supplierLeadTimes = overview?.supplier_lead_times || []
  const suffBreakdown = overview?.sufficiency_breakdown || {}

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('intelligence.overviewTitle')}
        subtitle={t('intelligence.overviewSubtitle')}
        actions={
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleRefreshAll}
              disabled={refreshing || loading}
            >
              <RefreshCw size={15} className={refreshing ? 'spin-icon' : ''} />
              <span>{t('intelligence.refreshModels')}</span>
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate('/reorder-planner')}
            >
              <ShoppingCart size={15} />
              <span>{t('nav.reorderSuggestions')}</span>
            </button>
          </div>
        }
      />

      {loading ? (
        <LoadingState message="Analyzing demand patterns, supplier lead times, and inventory positions..." />
      ) : error ? (
        <ErrorState title="Intelligence load failed" message={error} onRetry={() => loadData(true)} />
      ) : (
        <>
          <div className="kpi-grid" style={{ marginBottom: '1.25rem' }}>
            <KpiCard
              label={t('intelligence.stockoutRisk')}
              value={criticalAndHigh}
              subtitle={`${riskBreakdown.CRITICAL || 0} Critical / ${riskBreakdown.HIGH || 0} High`}
              icon={AlertTriangle}
              variant={criticalAndHigh > 0 ? 'rose' : 'emerald'}
            />
            <KpiCard
              label={t('intelligence.reorderCandidates')}
              value={overview?.reorder_candidates_count || 0}
              subtitle={`Est. Reorder Investment: ₹${Number(overview?.estimated_reorder_investment || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              icon={ShoppingCart}
              variant="blue"
            />
            <KpiCard
              label={t('intelligence.overstockCapital')}
              value={`₹${Number(overview?.overstock_capital_tied_up || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              subtitle={`${overstockItems.length} overstock / slow-moving SKU(s)`}
              icon={PackageX}
              variant="amber"
            />
            <KpiCard
              label={t('intelligence.supplierLeadTimes')}
              value={supplierLeadTimes.length}
              subtitle={`${overview?.high_delay_risk_suppliers || 0} supplier(s) with delay risk`}
              icon={Truck}
              variant="default"
            />
          </div>

          {/* Data Sufficiency Tiers Summary */}
          <section className="section-card" style={{ marginBottom: '1.25rem' }}>
            <div className="section-card-header">
              <h2 className="section-card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <BrainCircuit size={17} />
                <span>{t('intelligence.sufficiencyTiers')}</span>
              </h2>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/forecasting')}>
                <span>{t('nav.demandForecasts')}</span>
                <ArrowRight size={13} />
              </button>
            </div>
            <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap' }}>
              {Object.entries(SUFFICIENCY_LABELS).map(([tier, cfg]) => (
                <div
                  key={tier}
                  style={{
                    padding: '0.45rem 0.75rem',
                    borderRadius: 'var(--radius-md)',
                    background: cfg.bg,
                    color: cfg.color,
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.45rem',
                  }}
                >
                  <span>{cfg.label}:</span>
                  <strong>{suffBreakdown[tier] || 0}</strong>
                </div>
              ))}
            </div>
          </section>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '1.25rem', marginBottom: '1.25rem' }}>
            {/* Top Explained Recommendations */}
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('intelligence.urgentActions')}</h2>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate('/reorder-planner')}
                >
                  <span>Manage All ({overview?.open_recommendations_count || 0})</span>
                  <ArrowRight size={13} />
                </button>
              </div>
              {topRecs.length === 0 ? (
                <EmptyState title="No urgent actions" description={t('intelligence.noActions')} />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>SKU / Product</th>
                        <th>Category / Urgency</th>
                        <th className="numeric">Position (On Hand + In)</th>
                        <th className="numeric">Daily Demand</th>
                        <th className="numeric">Suggested Qty</th>
                        <th>Reason</th>
                        <th className="center">Inspect</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topRecs.map((rec) => (
                        <tr key={rec.id}>
                          <td>
                            <div style={{ fontWeight: 600 }}>{rec.product_name}</div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                              {rec.sku} • {rec.data_sufficiency}
                            </div>
                          </td>
                          <td>
                            <span
                              className="badge"
                              style={{
                                background: rec.urgency === 'CRITICAL' ? '#fee2e2' : rec.urgency === 'HIGH' ? '#fef3c7' : '#e0f2fe',
                                color: rec.urgency === 'CRITICAL' ? '#b91c1c' : rec.urgency === 'HIGH' ? '#b45309' : '#0369a1',
                                fontWeight: 700,
                              }}
                            >
                              {rec.urgency} · {rec.recommendation_type}
                            </span>
                          </td>
                          <td className="numeric">
                            <strong>{rec.inventory_position}</strong>
                            <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>
                              {rec.on_hand_stock} + {rec.incoming_stock} in
                            </div>
                          </td>
                          <td className="numeric">{Number(rec.avg_daily_demand || 0).toFixed(2)}/{rec.unit}</td>
                          <td className="numeric" style={{ fontWeight: 700 }}>
                            {rec.suggested_order_qty > 0 ? `+${rec.suggested_order_qty}` : '—'}
                          </td>
                          <td style={{ maxWidth: '320px', fontSize: '0.8rem', color: 'var(--erp-text-secondary)' }}>
                            {rec.explanation_summary}
                          </td>
                          <td className="center">
                            <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'center' }}>
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => navigate(`/forecasting?product_id=${rec.product_id}`)}
                              >
                                <TrendingUp size={13} />
                              </button>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => navigate('/reorder-planner')}
                              >
                                Review
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          {/* Supplier Lead-Time Intelligence & Overstock Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.25rem' }}>
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('intelligence.supplierLeadTimes')}</h2>
              </div>
              {supplierLeadTimes.length === 0 ? (
                <EmptyState title="No active suppliers" description="Add suppliers to track lead times and delivery performance." />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th className="numeric">Effective (σ)</th>
                        <th className="numeric">Tracked POs</th>
                        <th className="numeric">On-Time %</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {supplierLeadTimes.map((s) => (
                        <tr key={s.supplier_id}>
                          <td style={{ fontWeight: 600 }}>{s.supplier_name}</td>
                          <td className="numeric">
                            <strong>{s.effective_lead_time_days}d</strong>{' '}
                            <span style={{ color: 'var(--erp-text-muted)', fontSize: '0.75rem' }}>
                              (±{s.lead_time_std_days}d)
                            </span>
                          </td>
                          <td className="numeric">{s.sample_count}</td>
                          <td className="numeric">
                            {s.on_time_delivery_rate != null ? `${Math.round(s.on_time_delivery_rate * 100)}%` : '—'}
                          </td>
                          <td>
                            <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                              {s.lead_time_source === 'po_receipt_history' ? 'Empirical Receipts' : 'Manual Default'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">Overstock & Slow-Moving Capital</h2>
              </div>
              {overstockItems.length === 0 ? (
                <EmptyState title="No excess stock detected" description="No active items exceed 90-day / target buffer levels." />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th className="numeric">Position</th>
                        <th className="numeric">Excess Qty</th>
                        <th className="numeric">Excess Value</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overstockItems.map((item) => (
                        <tr key={item.product_id}>
                          <td>
                            <div style={{ fontWeight: 600 }}>{item.product_name}</div>
                            <div style={{ fontSize: '0.74rem', color: 'var(--erp-text-muted)' }}>{item.sku}</div>
                          </td>
                          <td className="numeric">{item.inventory_position}</td>
                          <td className="numeric" style={{ fontWeight: 700 }}>{item.overstock_excess_units}</td>
                          <td className="numeric">₹{Number(item.excess_inventory_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                          <td>
                            <span className="badge badge-draft">{item.overstock_risk}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
