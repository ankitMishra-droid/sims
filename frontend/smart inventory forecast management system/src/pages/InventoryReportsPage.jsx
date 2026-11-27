import { useEffect, useState, useMemo, useCallback } from 'react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import DataTable from '../components/common/DataTable'
import Badge from '../components/Badge'
import CsvExportButton from '../components/common/CsvExportButton'
import { LoadingState, ErrorState } from '../components/common/StateBlocks'
import { CategoryValuationChart } from '../components/charts'
import { Package, DollarSign, AlertTriangle, Truck, RefreshCw } from 'lucide-react'

const formatCurrency = (val) =>
  `₹${Number(val || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export default function InventoryReportsPage() {
  const { t } = useTranslation()
  const [summary, setSummary] = useState(null)
  const [positions, setPositions] = useState([])
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sumRes, posRes, prodRes] = await Promise.all([
        api.getDashboardSummary(),
        api.getInventoryPositions(),
        api.getProducts(),
      ])
      setSummary(sumRes)
      setPositions(Array.isArray(posRes) ? posRes : [])
      setProducts(Array.isArray(prodRes) ? prodRes : [])
    } catch (err) {
      setError(err.message || 'Failed to load inventory report')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => {
      loadReport()
    }, 0)
    return () => clearTimeout(id)
  }, [loadReport])

  const categoryBreakdown = useMemo(() => {
    const posMap = new Map(positions.map((p) => [p.product_id, p]))
    const catMap = new Map()
    products.forEach((prod) => {
      if (!prod.is_active) return
      const cat = prod.category?.trim() || 'General'
      const pos = posMap.get(prod.id)
      const onHand = Number(pos?.on_hand_stock ?? prod.current_stock ?? 0)
      const incoming = Number(pos?.incoming_stock ?? 0)
      const value = Number(pos?.inventory_value ?? onHand * Number(prod.cost_price || 0))
      const entry = catMap.get(cat) || {
        category: cat,
        sku_count: 0,
        on_hand_units: 0,
        incoming_units: 0,
        valuation: 0,
      }
      entry.sku_count += 1
      entry.on_hand_units += onHand
      entry.incoming_units += incoming
      entry.valuation += value
      catMap.set(cat, entry)
    })
    return Array.from(catMap.values()).sort((a, b) => b.valuation - a.valuation)
  }, [products, positions])

  const totalIncoming = useMemo(
    () => positions.reduce((sum, p) => sum + Number(p.incoming_stock || 0), 0),
    [positions]
  )

  const columns = [
    {
      key: 'category',
      label: 'Category',
      render: (row) => <strong>{row.category}</strong>,
    },
    {
      key: 'sku_count',
      label: 'Active SKUs',
      render: (row) => row.sku_count,
    },
    {
      key: 'on_hand_units',
      label: 'On-Hand Units',
      render: (row) => Number(row.on_hand_units).toLocaleString(),
    },
    {
      key: 'incoming_units',
      label: 'Incoming Units',
      render: (row) => (
        <Badge
          status={row.incoming_units > 0 ? 'SENT' : 'DRAFT'}
          label={Number(row.incoming_units).toLocaleString()}
        />
      ),
    },
    {
      key: 'valuation',
      label: 'Stock Cost Value',
      render: (row) => <strong>{formatCurrency(row.valuation)}</strong>,
    },
  ]

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('reports.inventoryTitle')}
        subtitle={t('reports.inventorySubtitle')}
        actions={
          <>
            <CsvExportButton
              data={positions}
              filename="inventory_positions"
              title="Export CSV"
            />
            <button type="button" className="btn btn-secondary" onClick={loadReport} disabled={loading}>
              <RefreshCw size={15} />
              <span>{t('common.refresh')}</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={loadReport} />}

      {loading ? (
        <LoadingState message="Loading live inventory valuation and positions..." />
      ) : (
        <>
          <div className="erp-grid-4">
            <KpiCard
              title="Active Catalog SKUs"
              value={Number(summary?.total_products || 0).toLocaleString()}
              subtitle={`${Number(summary?.total_stock_units || 0).toLocaleString()} total units on hand`}
              icon={Package}
              color="blue"
            />
            <KpiCard
              title="Total Inventory Valuation"
              value={formatCurrency(summary?.total_inventory_value)}
              subtitle="Based on on-hand units × unit cost"
              icon={DollarSign}
              color="emerald"
            />
            <KpiCard
              title="Incoming PO Stock"
              value={Number(totalIncoming).toLocaleString()}
              subtitle="Units on SENT / PARTIALLY RECEIVED POs"
              icon={Truck}
              color="purple"
            />
            <KpiCard
              title="Low-Stock Products"
              value={Number(summary?.low_stock_products || 0).toLocaleString()}
              subtitle="Products at or below reorder threshold"
              icon={AlertTriangle}
              color="amber"
            />
          </div>

          <div className="dashboard-grid-2">
            <CategoryValuationChart products={products} />

            <div className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">Category Stock Valuation</h2>
              </div>
              <DataTable
                columns={columns}
                data={categoryBreakdown}
                keyField="category"
                pageSize={8}
                emptyMessage="No active inventory categories found."
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
