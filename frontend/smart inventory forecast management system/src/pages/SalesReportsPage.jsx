import { useEffect, useState, useMemo, useCallback } from 'react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import DataTable from '../components/common/DataTable'
import CsvExportButton from '../components/common/CsvExportButton'
import { LoadingState, ErrorState } from '../components/common/StateBlocks'
import { RevenueTrendChart, TopProductsChart } from '../components/charts'
import { DollarSign, ShoppingBag, TrendingUp, Calendar, RefreshCw } from 'lucide-react'

const formatCurrency = (val) =>
  `₹${Number(val || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function SalesReportsPage() {
  const { t } = useTranslation()
  const [metrics, setMetrics] = useState(null)
  const [sales, setSales] = useState([])
  const [totalSalesInRange, setTotalSalesInRange] = useState(0)
  const [products, setProducts] = useState([])
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 30)
    return d.toISOString().slice(0, 10)
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [mRes, salesRes, prodRes] = await Promise.all([
        api.getSalesMetrics(),
        api.getSalesPage({
          start_date: startDate || undefined,
          end_date: endDate || undefined,
          limit: 500,
          skip: 0,
        }),
        api.getProducts(),
      ])
      setMetrics(mRes)
      setSales(Array.isArray(salesRes?.data) ? salesRes.data : [])
      setTotalSalesInRange(Number(salesRes?.total ?? 0))
      setProducts(Array.isArray(prodRes) ? prodRes : [])
    } catch (err) {
      setError(err.message || 'Failed to load sales report')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => {
    const id = setTimeout(() => {
      loadReport()
    }, 0)
    return () => clearTimeout(id)
  }, [loadReport])

  const productRevenueRows = useMemo(() => {
    const prodMap = new Map(products.map((p) => [p.id, p]))
    const agg = new Map()
    sales.forEach((sale) => {
      const prod = prodMap.get(sale.product_id)
      const name = prod?.name || `Product #${sale.product_id}`
      const sku = prod?.sku || '—'
      const cur = agg.get(sale.product_id) || {
        product_id: sale.product_id,
        name,
        sku,
        orders: 0,
        units: 0,
        revenue: 0,
      }
      cur.orders += 1
      cur.units += Number(sale.quantity_sold || 0)
      cur.revenue += Number(sale.total_price || 0)
      agg.set(sale.product_id, cur)
    })
    return Array.from(agg.values()).sort((a, b) => b.revenue - a.revenue)
  }, [sales, products])

  const rangeTotals = useMemo(() => {
    return sales.reduce(
      (acc, s) => {
        acc.units += Number(s.quantity_sold || 0)
        acc.revenue += Number(s.total_price || 0)
        return acc
      },
      { units: 0, revenue: 0 }
    )
  }, [sales])

  const columns = [
    {
      key: 'name',
      label: 'Product',
      render: (row) => (
        <div>
          <div style={{ fontWeight: 600 }}>{row.name}</div>
          <div style={{ fontSize: '0.72rem', color: 'var(--erp-text-muted)' }}>SKU: {row.sku}</div>
        </div>
      ),
    },
    { key: 'orders', label: 'Orders', render: (row) => row.orders },
    { key: 'units', label: 'Units Sold', render: (row) => row.units.toLocaleString() },
    {
      key: 'revenue',
      label: 'Revenue',
      render: (row) => <strong>{formatCurrency(row.revenue)}</strong>,
    },
  ]

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('reports.salesTitle')}
        subtitle={t('reports.salesSubtitle')}
        actions={
          <>
            <CsvExportButton
              data={sales}
              filename="sales_report"
              title="Export CSV"
            />
            <button type="button" className="btn btn-secondary" onClick={loadReport} disabled={loading}>
              <RefreshCw size={15} />
              <span>{t('common.refresh')}</span>
            </button>
          </>
        }
      />

      <div className="section-card" style={{ padding: '0.9rem 1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}>
            <Calendar size={15} />
            <span>Date Window:</span>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem' }}>
            <span>From</span>
            <input
              type="date"
              className="form-control"
              style={{ width: 'auto', padding: '0.35rem 0.6rem' }}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem' }}>
            <span>To</span>
            <input
              type="date"
              className="form-control"
              style={{ width: 'auto', padding: '0.35rem 0.6rem' }}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
          <span style={{ marginLeft: 'auto', fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
            Showing {sales.length} of {totalSalesInRange} orders in selected range
          </span>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={loadReport} />}

      {loading ? (
        <LoadingState message="Loading live sales analytics..." />
      ) : (
        <>
          <div className="erp-grid-4">
            <KpiCard
              title="Today's Revenue"
              value={formatCurrency(metrics?.todays_revenue)}
              subtitle={`${metrics?.sales_count_today ?? 0} orders today`}
              icon={DollarSign}
              color="emerald"
            />
            <KpiCard
              title="This Week Revenue"
              value={formatCurrency(metrics?.this_weeks_revenue)}
              subtitle={`${metrics?.sales_count_this_week ?? 0} orders this week`}
              icon={TrendingUp}
              color="blue"
            />
            <KpiCard
              title="This Month Revenue"
              value={formatCurrency(metrics?.this_months_revenue)}
              subtitle={`${metrics?.sales_count_this_month ?? 0} orders this month`}
              icon={ShoppingBag}
              color="purple"
            />
            <KpiCard
              title="Loaded Range Revenue"
              value={formatCurrency(rangeTotals.revenue)}
              subtitle={`${rangeTotals.units.toLocaleString()} units across ${sales.length} orders`}
              icon={Calendar}
              color="amber"
            />
          </div>

          <div className="dashboard-grid-2">
            <RevenueTrendChart sales={sales} />
            <TopProductsChart sales={sales} products={products} />
          </div>

          <div className="section-card">
            <div className="section-card-header">
              <h2 className="section-card-title">Revenue Breakdown by Product</h2>
            </div>
            <DataTable
              columns={columns}
              data={productRevenueRows}
              keyField="product_id"
              pageSize={10}
              emptyMessage="No sales recorded in the selected date window."
            />
          </div>
        </>
      )}
    </div>
  )
}
