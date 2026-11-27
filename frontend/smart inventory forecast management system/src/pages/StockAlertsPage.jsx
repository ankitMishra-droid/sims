import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { AlertTriangle, RefreshCw, Plus } from 'lucide-react'
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import Badge from '../components/Badge'
import { LoadingState, ErrorState, EmptyState } from '../components/common/StateBlocks'

export default function StockAlertsPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const products = useSelector(selectAllProducts)

  const [lowStock, setLowStock] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedProductId, setSelectedProductId] = useState('')
  const [anomalies, setAnomalies] = useState(null)
  const [anomLoading, setAnomLoading] = useState(false)

  const loadLowStock = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.getLowStockProducts()
      setLowStock(Array.isArray(data) ? data : [])
    } catch (err) {
      setError(err.message || 'Failed to load stock alerts.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    dispatch(fetchProducts())
    const id = setTimeout(() => {
      loadLowStock()
    }, 0)
    return () => clearTimeout(id)
  }, [dispatch])

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

  const productOptions = useMemo(
    () => products.map((p) => ({ value: p.id, label: p.name, badge: p.sku })),
    [products]
  )

  const columns = [
    { key: 'sku', label: 'SKU', render: (p) => <span style={{ fontFamily: 'var(--font-mono)' }}>{p.sku}</span> },
    { key: 'name', label: 'Product', sortable: true },
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
      render: (p) => <Badge status={p.current_stock === 0 ? 'OUT OF STOCK' : 'LOW STOCK'} />,
    },
    {
      key: 'action',
      label: 'Action',
      center: true,
      render: (p) => (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => navigate(`/purchase-orders?supplier_id=${p.supplier_id || ''}`)}
        >
          <Plus size={12} /> Create PO
        </button>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title="Stock Alerts & Demand Anomalies"
        subtitle="Active low-stock items and Z-score sales spike/drop detection"
        actions={
          <button type="button" className="btn btn-secondary btn-sm" onClick={loadLowStock} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        }
      />

      {error && <ErrorState message={error} onRetry={loadLowStock} />}

      <DataTable
        columns={columns}
        data={lowStock}
        keyField="id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No low-stock alerts"
        emptyMessage="All active products are currently above their reorder threshold."
      />

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
