import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  Package,
  IndianRupee,
  TrendingUp,
  AlertTriangle,
  ClipboardList,
  Boxes,
  RefreshCw,
  Plus,
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  ShoppingCart,
  Clock,
} from 'lucide-react'
import {
  fetchDashboardMetrics,
  selectDashboardMetrics,
  selectDashboardLoading,
} from '../store/dashboardSlice'
import { selectAllProducts, selectLowStockProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSales, fetchSales } from '../store/salesSlice'
import { selectAllPurchaseOrders, fetchPurchaseOrders } from '../store/purchaseOrdersSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import KpiCard from '../components/common/KpiCard'
import Badge from '../components/Badge'
import {
  RevenueTrendChart,
  StockMovementChart,
  CategoryValuationChart,
  TopProductsChart,
  OperationsRadarChart,
} from '../components/charts'

export default function DashboardPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const metrics = useSelector(selectDashboardMetrics)
  const loading = useSelector(selectDashboardLoading)
  const products = useSelector(selectAllProducts)
  const lowStockList = useSelector(selectLowStockProducts)
  const sales = useSelector(selectAllSales)
  const orders = useSelector(selectAllPurchaseOrders)
  const suppliers = useSelector(selectAllSuppliers)

  const [period, setPeriod] = useState('month') // 'today' | 'week' | 'month'

  useEffect(() => {
    dispatch(fetchDashboardMetrics())
    dispatch(fetchProducts())
    dispatch(fetchSales())
    dispatch(fetchPurchaseOrders())
    dispatch(fetchSuppliers())
  }, [dispatch])

  const summary = metrics?.summary
  const poMetrics = metrics?.poMetrics
  const movementMetrics = metrics?.movementMetrics
  const salesMetrics = metrics?.salesMetrics

  // Calculated metrics from active Redux collections for instant reactivity
  const calculatedTotalStock = useMemo(() => {
    return products.reduce((acc, p) => acc + (Number(p.current_stock) || 0), 0)
  }, [products])

  const calculatedValuation = useMemo(() => {
    return products.reduce(
      (acc, p) => acc + (Number(p.current_stock) || 0) * (Number(p.cost_price) || 0),
      0
    )
  }, [products])

  const calculatedSalesForPeriod = useMemo(() => {
    const now = new Date()
    const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    const weekAgo = new Date(now)
    weekAgo.setDate(weekAgo.getDate() - 7)
    const monthAgo = new Date(now)
    monthAgo.setDate(monthAgo.getDate() - 30)

    let rev = 0
    let count = 0

    ;(sales || []).forEach((s) => {
      const rawDate = s.sales_date || s.sale_date || s.created_at
      if (!rawDate) return
      const d = new Date(rawDate)
      if (isNaN(d.getTime())) return

      const r = Number(s.revenue) || (Number(s.selling_price || 0) * Number(s.quantity_sold || 0)) || 0

      if (period === 'today') {
        const dStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        if (dStr === todayStr) {
          rev += r
          count += 1
        }
      } else if (period === 'week') {
        if (d >= weekAgo) {
          rev += r
          count += 1
        }
      } else {
        if (d >= monthAgo) {
          rev += r
          count += 1
        }
      }
    })

    return { rev, count }
  }, [sales, period])

  const netProfitData = useMemo(() => {
    let totalRevenue = 0
    let totalCOGS = 0
    ;(sales || []).forEach((s) => {
      const p = (products || []).find((prod) => prod.id === s.product_id)
      const rev = Number(s.revenue) || (Number(s.selling_price || 0) * Number(s.quantity_sold || 0)) || 0
      const cost = p ? (Number(p.cost_price || 0) * Number(s.quantity_sold || 0)) : 0
      totalRevenue += rev
      totalCOGS += cost
    })
    const netProfit = totalRevenue - totalCOGS
    const margin = totalRevenue > 0 ? ((netProfit / totalRevenue) * 100).toFixed(1) : '0.0'
    return {
      totalRevenue,
      totalCOGS,
      netProfit,
      margin,
    }
  }, [sales, products])

  // Dynamic period metrics with live Redux fallback
  const revenueForPeriod =
    calculatedSalesForPeriod.rev > 0
      ? calculatedSalesForPeriod.rev
      : period === 'today'
      ? salesMetrics?.todays_revenue
      : period === 'week'
      ? salesMetrics?.this_weeks_revenue
      : salesMetrics?.this_months_revenue

  const salesCountForPeriod =
    calculatedSalesForPeriod.count > 0
      ? calculatedSalesForPeriod.count
      : period === 'today'
      ? salesMetrics?.sales_count_today
      : period === 'week'
      ? salesMetrics?.sales_count_this_week
      : salesMetrics?.sales_count_this_month

  // Low Stock Table Columns
  const lowStockColumns = useMemo(
    () => [
      {
        key: 'sku',
        label: 'SKU',
        sortable: true,
        render: (p) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 700, color: '#dc2626' }}>
            {p.sku}
          </span>
        ),
      },
      {
        key: 'name',
        label: 'Product',
        sortable: true,
        render: (p) => (
          <div>
            <div style={{ fontWeight: 600 }}>{p.name}</div>
            <div style={{ fontSize: '0.725rem', color: '#64748b' }}>Unit: {p.unit}</div>
          </div>
        ),
      },
      {
        key: 'current_stock',
        label: 'In Stock',
        numeric: true,
        sortable: true,
        render: (p) => (
          <span style={{ fontWeight: 800, color: p.current_stock === 0 ? '#dc2626' : '#d97706' }}>
            {p.current_stock} {p.unit}
          </span>
        ),
      },
      {
        key: 'reorder_level',
        label: 'Reorder Point',
        numeric: true,
        sortable: true,
        render: (p) => `${p.reorder_level} ${p.unit}`,
      },
      {
        key: 'action',
        label: 'Action',
        center: true,
        sortable: false,
        render: (p) => (
          <button
            className="btn btn-primary btn-sm"
            onClick={() => navigate(`/purchase-orders?supplier_id=${p.supplier_id || ''}`)}
          >
            <Plus size={12} />
            <span>Reorder</span>
          </button>
        ),
      },
    ],
    [navigate]
  )

  // Recent Sales Columns
  const recentSalesColumns = useMemo(
    () => [
      {
        key: 'id',
        label: 'Sale ID',
        sortable: true,
        render: (s) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 600 }}>
            #SO-{String(s.id).padStart(4, '0')}
          </span>
        ),
      },
      {
        key: 'product',
        label: 'Product',
        sortable: false,
        render: (s) => {
          const prod = products.find((p) => p.id === s.product_id)
          return (
            <div>
              <div style={{ fontWeight: 600 }}>{prod ? prod.name : `Product #${s.product_id}`}</div>
              <div style={{ fontSize: '0.725rem', color: '#64748b' }}>{prod?.sku}</div>
            </div>
          )
        },
      },
      {
        key: 'quantity_sold',
        label: 'Quantity',
        numeric: true,
        sortable: true,
        render: (s) => {
          const prod = products.find((p) => p.id === s.product_id)
          return `${s.quantity_sold} ${prod?.unit || ''}`
        },
      },
      {
        key: 'revenue',
        label: 'Revenue',
        numeric: true,
        sortable: true,
        render: (s) => (
          <span style={{ fontWeight: 700, color: '#059669' }}>
            ₹{Number(s.revenue).toFixed(2)}
          </span>
        ),
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        sortable: false,
        render: () => <Badge status="RECEIVED" label="Completed" />,
      },
    ],
    [products]
  )

  return (
    <div className="dashboard-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Executive Control"
        activePage="Operations Dashboard"
        onRefresh={() => {
          dispatch(fetchDashboardMetrics())
          dispatch(fetchProducts())
          dispatch(fetchSales())
          dispatch(fetchPurchaseOrders())
        }}
        loading={loading}
        filters={
          <div
            style={{
              display: 'flex',
              background: 'var(--erp-surface-subtle)',
              borderRadius: '6px',
              padding: '2px',
              border: '1px solid var(--erp-border)',
            }}
          >
            <button
              className={`btn btn-sm ${period === 'today' ? 'btn-primary' : 'btn-subtle'}`}
              style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
              onClick={() => setPeriod('today')}
            >
              Today
            </button>
            <button
              className={`btn btn-sm ${period === 'week' ? 'btn-primary' : 'btn-subtle'}`}
              style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
              onClick={() => setPeriod('week')}
            >
              Past 7 Days
            </button>
            <button
              className={`btn btn-sm ${period === 'month' ? 'btn-primary' : 'btn-subtle'}`}
              style={{ padding: '0.25rem 0.65rem', fontSize: '0.75rem' }}
              onClick={() => setPeriod('month')}
            >
              Past 30 Days
            </button>
          </div>
        }
      />

      {/* Main KPI Cards Grid */}
      <div className="kpi-grid">
        <KpiCard
          label="Product Catalog"
          value={products.length > 0 ? products.length : (summary?.total_products || 0)}
          subtitle={`${(products.length > 0 ? calculatedTotalStock : (summary?.total_stock_units || 0)).toLocaleString()} units in warehouse`}
          icon={Package}
          onClick={() => navigate('/products')}
        />
        <KpiCard
          label="Total Stock Valuation"
          value={`₹${Number(products.length > 0 ? calculatedValuation : (summary?.total_inventory_value || 0)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle="Inventory cost value on hand"
          icon={IndianRupee}
          variant="emerald"
          onClick={() => navigate('/inventory')}
        />
        <KpiCard
          label={`Sales Revenue (${period === 'today' ? 'Today' : period === 'week' ? 'Past 7 Days' : 'Past 30 Days'})`}
          value={`₹${Number(revenueForPeriod || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle={`${salesCountForPeriod || 0} orders executed`}
          icon={TrendingUp}
          variant="blue"
          onClick={() => navigate('/sales')}
        />
        <KpiCard
          label="Total Net Profit"
          value={`₹${netProfitData.netProfit.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle={`${netProfitData.margin}% profit margin so far`}
          icon={TrendingUp}
          variant="purple"
          onClick={() => navigate('/sales')}
        />
        <KpiCard
          label="Low Stock Alerts"
          value={summary?.low_stock_products || lowStockList.length}
          subtitle={
            (summary?.low_stock_products || lowStockList.length) > 0
              ? 'Replenish required'
              : 'All stocks healthy'
          }
          icon={AlertTriangle}
          variant={(summary?.low_stock_products || lowStockList.length) > 0 ? 'rose' : 'emerald'}
          onClick={() => navigate('/inventory')}
        />
      </div>

      {/* Visual Analytics & Improvement Charts Suite */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginBottom: '1.5rem' }}>
        {/* Row 1: Line Chart (Revenue Trend) & Grouped Bar Chart (Stock Movements) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <RevenueTrendChart sales={sales} />
          <StockMovementChart sales={sales} purchaseOrders={orders} products={products} />
        </div>

        {/* Row 2: Doughnut/Pie Chart (Categories), Horizontal Bar (Top Products), and Radar Chart (Operations Health) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <CategoryValuationChart products={products} />
          <TopProductsChart sales={sales} products={products} />
          <OperationsRadarChart
            products={products}
            sales={sales}
            purchaseOrders={orders}
            suppliers={suppliers}
          />
        </div>
      </div>

      {/* Procurement & Today's Movement Blocks */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1.25rem',
          marginBottom: '1.5rem',
        }}
      >
        {/* Purchase Order Pipeline */}
        <div
          style={{
            background: 'var(--erp-surface)',
            border: '1px solid var(--erp-border)',
            borderRadius: '8px',
            padding: '1.25rem',
            boxShadow: 'var(--shadow-xs)',
            transition: 'background-color 0.25s ease, border-color 0.25s ease',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '6px', background: 'var(--erp-brand-subtle)', color: 'var(--erp-brand)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <ClipboardList size={18} />
              </div>
              <h3 style={{ fontSize: '1rem', color: 'var(--erp-text-main)' }}>Purchase Order Pipeline</h3>
            </div>
            <button className="btn btn-subtle btn-sm" onClick={() => navigate('/purchase-orders')}>
              <span>View All</span>
              <ArrowRight size={13} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem' }}>
            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Total POs</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800 }}>{poMetrics?.total_purchase_orders || orders.length}</div>
            </div>
            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Pending Orders</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#d97706' }}>
                {poMetrics?.pending_purchase_orders || 0}
              </div>
            </div>
            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Incomplete Deliveries</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#2563eb' }}>
                {poMetrics?.incomplete_deliveries || 0}
              </div>
            </div>
            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Expected Stock</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#059669' }}>
                +{poMetrics?.expected_stock || 0} units
              </div>
            </div>
          </div>
        </div>

        {/* Daily Inventory Movement */}
        <div
          style={{
            background: 'var(--erp-surface)',
            border: '1px solid var(--erp-border)',
            borderRadius: '8px',
            padding: '1.25rem',
            boxShadow: 'var(--shadow-xs)',
            transition: 'background-color 0.25s ease, border-color 0.25s ease',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '6px', background: 'var(--status-success-bg)', color: '#059669', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Boxes size={18} />
              </div>
              <h3 style={{ fontSize: '1rem', color: 'var(--erp-text-main)' }}>Today's Movement</h3>
            </div>
            <button className="btn btn-subtle btn-sm" onClick={() => navigate('/inventory')}>
              <span>Audit Trail</span>
              <ArrowRight size={13} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem' }}>
            <div style={{ backgroundColor: 'var(--status-success-bg)', padding: '0.75rem', borderRadius: '6px', border: '1px solid var(--status-success-border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--status-success-text)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                <ArrowUpRight size={13} /> Inbound Today
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--status-success-text)' }}>
                +{movementMetrics?.stock_in_today || 0} units
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--status-danger-bg)', padding: '0.75rem', borderRadius: '6px', border: '1px solid var(--status-danger-border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--status-danger-text)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                <ArrowDownRight size={13} /> Dispatched Today
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--status-danger-text)' }}>
                -{movementMetrics?.stock_out_today || 0} units
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Net Stock Delta</div>
              <div
                style={{
                  fontSize: '1.25rem',
                  fontWeight: 800,
                  color: (movementMetrics?.net_stock_movement_today || 0) >= 0 ? '#059669' : '#dc2626',
                }}
              >
                {(movementMetrics?.net_stock_movement_today || 0) >= 0 ? '+' : ''}
                {movementMetrics?.net_stock_movement_today || 0} units
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', padding: '0.75rem', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Transactions Logged</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800 }}>
                {movementMetrics?.inventory_transaction_count_today || 0}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Two-Column Feeds with Reusable DataTable & Pagination */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))',
          gap: '1.5rem',
        }}
      >
        <div>
          <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertTriangle size={18} color="#d97706" />
            <span>Critical Stock Replenishment Alerts ({lowStockList.length})</span>
          </div>
          <DataTable
            columns={lowStockColumns}
            data={lowStockList}
            keyField="id"
            defaultPageSize={5}
            emptyTitle="All inventory levels healthy"
            emptyMessage="No products are at or below reorder threshold."
            emptyIcon={Package}
          />
        </div>

        <div>
          <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--erp-text-main)' }}>
            <ShoppingCart size={18} color="var(--erp-brand)" />
            <span>Recent Sales Transactions</span>
          </div>
          <DataTable
            columns={recentSalesColumns}
            data={sales}
            keyField="id"
            defaultPageSize={5}
            emptyTitle="No sales recorded"
            emptyMessage="Record customer sales to see transactions here."
            emptyIcon={ShoppingCart}
          />
        </div>
      </div>
    </div>
  )
}
