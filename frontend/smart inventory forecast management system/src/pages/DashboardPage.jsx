import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import {
  Package,
  IndianRupee,
  ShoppingCart,
  AlertTriangle,
  Plus,
  ClipboardList,
  Inbox,
  ArrowRight,
  RefreshCw,
} from 'lucide-react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import Badge from '../components/Badge'
import { LoadingState, ErrorState, EmptyState } from '../components/common/StateBlocks'

export default function DashboardPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const user = useSelector((state) => state.auth.user)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState(null)
  const [salesMetrics, setSalesMetrics] = useState(null)
  const [poMetrics, setPoMetrics] = useState(null)
  const [movementMetrics, setMovementMetrics] = useState(null)
  const [lowStock, setLowStock] = useState([])
  const [pendingPOs, setPendingPOs] = useState([])
  const [recentSales, setRecentSales] = useState([])
  const [productsMap, setProductsMap] = useState({})

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [sum, sMetrics, pMetrics, mMetrics, lowList, pos, salesPage, prods] = await Promise.all([
        api.getDashboardSummary(),
        api.getSalesMetrics(),
        api.getPurchaseOrderMetrics(),
        api.getInventoryMovementMetrics(),
        api.getLowStockProducts(),
        api.getPurchaseOrders(),
        api.getSalesPage({ limit: 5, skip: 0 }),
        api.getProducts(),
      ])

      setSummary(sum)
      setSalesMetrics(sMetrics)
      setPoMetrics(pMetrics)
      setMovementMetrics(mMetrics)
      setLowStock(Array.isArray(lowList) ? lowList.slice(0, 6) : [])
      setPendingPOs(
        (Array.isArray(pos) ? pos : [])
          .filter((po) => ['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(po.status))
          .slice(0, 6)
      )
      setRecentSales(salesPage?.data || [])

      const pMap = {}
      ;(Array.isArray(prods) ? prods : []).forEach((p) => {
        pMap[p.id] = p
      })
      setProductsMap(pMap)
    } catch (err) {
      setError(err.message || 'Failed to load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => {
      loadDashboard()
    }, 0)
    return () => clearTimeout(id)
  }, [loadDashboard])

  const todayDisplay = new Date().toLocaleDateString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title={`${t('dashboard.welcome')}, ${user?.name || 'Operator'}`}
        subtitle={`${t('common.workspace')} #${user?.active_business_id || 1} • ${todayDisplay} — ${t('dashboard.subtitle')}`}
        actions={
          <>
            <button type="button" className="btn btn-secondary btn-sm" onClick={loadDashboard} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>{t('common.refresh')}</span>
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/products')}>
              <Plus size={14} />
              <span>{t('dashboard.addProduct')}</span>
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => navigate('/sales/new')}>
              <ShoppingCart size={14} />
              <span>{t('dashboard.recordSale')}</span>
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/purchase-orders')}>
              <ClipboardList size={14} />
              <span>{t('dashboard.createPo')}</span>
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/receive-order')}>
              <Inbox size={14} />
              <span>{t('dashboard.receiveGoods')}</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={loadDashboard} />}

      {loading && !summary ? (
        <LoadingState message={t('common.loading')} />
      ) : (
        <>
          {/* Core Operational KPIs */}
          <div className="kpi-grid">
            <KpiCard
              label={t('dashboard.totalProducts')}
              value={summary?.total_products ?? 0}
              subtitle={`${(summary?.total_stock_units ?? 0).toLocaleString()} units on hand`}
              icon={Package}
              variant="blue"
              onClick={() => navigate('/products')}
            />
            <KpiCard
              label={t('dashboard.stockValue')}
              value={`₹${Number(summary?.total_inventory_value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
              subtitle="Cost valuation across active catalog"
              icon={IndianRupee}
              variant="emerald"
              onClick={() => navigate('/inventory')}
            />
            <KpiCard
              label={t('dashboard.todaysSales')}
              value={`₹${Number(salesMetrics?.todays_revenue || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
              subtitle={`${salesMetrics?.sales_count_today ?? 0} order(s) today`}
              icon={ShoppingCart}
              variant="purple"
              onClick={() => navigate('/sales')}
            />
            <KpiCard
              label={t('dashboard.lowStock')}
              value={summary?.low_stock_products ?? 0}
              subtitle="At or below reorder level"
              icon={AlertTriangle}
              variant={(summary?.low_stock_products || 0) > 0 ? 'amber' : 'emerald'}
              onClick={() => navigate('/stock-alerts')}
            />
          </div>

          {/* Operational Tables */}
          <div className="dashboard-grid-2">
            {/* Critical Low Stock */}
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('dashboard.criticalLowStock')}</h2>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate('/reorder-planner')}
                >
                  <span>Reorder Plan</span>
                  <ArrowRight size={13} />
                </button>
              </div>
              {lowStock.length === 0 ? (
                <EmptyState
                  title="All stock levels healthy"
                  description="No active products are at or below their reorder threshold."
                />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>Product</th>
                        <th className="numeric">On Hand</th>
                        <th className="numeric">Reorder At</th>
                        <th className="center">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {lowStock.map((p) => (
                        <tr key={p.id}>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.775rem' }}>{p.sku}</td>
                          <td style={{ fontWeight: 600 }}>{p.name}</td>
                          <td className="numeric" style={{ color: p.current_stock === 0 ? '#dc2626' : '#d97706', fontWeight: 700 }}>
                            {p.current_stock}
                          </td>
                          <td className="numeric">{p.reorder_level}</td>
                          <td className="center">
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={() => navigate(`/purchase-orders?supplier_id=${p.supplier_id || ''}`)}
                            >
                              Order
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Pending Purchase Orders */}
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('dashboard.pendingOrders')}</h2>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate('/purchase-orders')}
                >
                  <span>All POs</span>
                  <ArrowRight size={13} />
                </button>
              </div>
              {pendingPOs.length === 0 ? (
                <EmptyState
                  title="No pending purchase orders"
                  description="Create a purchase order to replenish stock from a supplier."
                />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>PO #</th>
                        <th>Status</th>
                        <th className="numeric">Total</th>
                        <th className="center">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pendingPOs.map((po) => (
                        <tr key={po.id}>
                          <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                            {po.order_number || `PO-${String(po.id).padStart(4, '0')}`}
                          </td>
                          <td>
                            <Badge status={po.status} />
                          </td>
                          <td className="numeric">₹{Number(po.total_amount || 0).toFixed(2)}</td>
                          <td className="center">
                            {po.status === 'DRAFT' ? (
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => navigate('/purchase-orders')}
                              >
                                Review
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => navigate(`/receive-order?order_id=${po.id}`)}
                              >
                                Receive
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Recent Sales */}
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('dashboard.recentSales')}</h2>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate('/sales')}
                >
                  <span>History</span>
                  <ArrowRight size={13} />
                </button>
              </div>
              {recentSales.length === 0 ? (
                <EmptyState title="No sales recorded" description="Record a sale to track revenue and stock deductions." />
              ) : (
                <div className="table-responsive">
                  <table className="erp-table">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Product</th>
                        <th className="numeric">Qty</th>
                        <th className="numeric">Revenue</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentSales.map((s) => (
                        <tr key={s.id}>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>#SO-{String(s.id).padStart(4, '0')}</td>
                          <td style={{ fontWeight: 500 }}>{productsMap[s.product_id]?.name || `Product #${s.product_id}`}</td>
                          <td className="numeric">{s.quantity_sold}</td>
                          <td className="numeric" style={{ fontWeight: 700, color: '#059669' }}>
                            ₹{Number(s.revenue || 0).toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Today's Movement & Procurement Summary */}
            <section className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">{t('dashboard.recentMovements')}</h2>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate('/inventory/history')}
                >
                  <span>Ledger</span>
                  <ArrowRight size={13} />
                </button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.75rem' }}>
                <div style={{ padding: '0.75rem', borderRadius: 'var(--radius-md)', background: 'var(--erp-surface-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Stock In Today</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#059669' }}>
                    +{movementMetrics?.stock_in_today ?? 0}
                  </div>
                </div>
                <div style={{ padding: '0.75rem', borderRadius: 'var(--radius-md)', background: 'var(--erp-surface-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Stock Out Today</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#dc2626' }}>
                    -{movementMetrics?.stock_out_today ?? 0}
                  </div>
                </div>
                <div style={{ padding: '0.75rem', borderRadius: 'var(--radius-md)', background: 'var(--erp-surface-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Expected Incoming Units</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--erp-brand)' }}>
                    {poMetrics?.expected_stock ?? 0}
                  </div>
                </div>
                <div style={{ padding: '0.75rem', borderRadius: 'var(--radius-md)', background: 'var(--erp-surface-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>30-Day Sales Revenue</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                    ₹{Number(salesMetrics?.this_months_revenue || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                </div>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  )
}
