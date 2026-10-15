import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  Package,
  ShoppingCart,
  Boxes,
  Truck,
  ClipboardList,
  Inbox,
  LayoutDashboard,
  ArrowRight,
  Plus,
  Search,
  Sparkles,
  Command,
  TrendingUp,
  AlertTriangle,
  Server,
  Layers,
  Database,
  ShieldCheck,
} from 'lucide-react'
import { selectAllProducts, selectLowStockProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSales, fetchSales } from '../store/salesSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import { selectPendingPurchaseOrders, fetchPurchaseOrders } from '../store/purchaseOrdersSlice'
import { setCommandPaletteOpen } from '../store/uiSlice'
import { RevenueTrendChart, CategoryValuationChart } from '../components/charts'

export default function LandingPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const products = useSelector(selectAllProducts)
  const lowStock = useSelector(selectLowStockProducts)
  const sales = useSelector(selectAllSales)
  const suppliers = useSelector(selectAllSuppliers)
  const pendingPOs = useSelector(selectPendingPurchaseOrders)

  useEffect(() => {
    dispatch(fetchProducts())
    dispatch(fetchSales())
    dispatch(fetchSuppliers())
    dispatch(fetchPurchaseOrders())
  }, [dispatch])

  // Aggregate metrics
  const totalStockUnits = products.reduce((acc, p) => acc + (Number(p.current_stock) || 0), 0)
  const totalValuation = products.reduce(
    (acc, p) => acc + (Number(p.current_stock) || 0) * (Number(p.cost_price) || 0),
    0
  )
  const totalSalesRevenue = sales.reduce((acc, s) => acc + (Number(s.revenue) || 0), 0)

  // Module Launcher cards
  const apps = [
    {
      id: 'products',
      name: 'Products Catalog',
      category: 'Inventory Master',
      desc: 'Master product items, SKU registry, pricing models, and stock thresholds.',
      path: '/products',
      icon: Package,
      gradient: 'linear-gradient(135deg, #714b67, #9a658c)',
      counter: `${products.length} Items`,
      counterType: 'neutral',
      badge: `${totalStockUnits.toLocaleString()} units in stock`,
    },
    {
      id: 'sales',
      name: 'Sales & POS',
      category: 'Point of Sale',
      desc: 'Customer orders, inventory stock dispatching, and revenue records.',
      path: '/sales',
      icon: ShoppingCart,
      gradient: 'linear-gradient(135deg, #059669, #10b981)',
      counter: `${sales.length} Orders`,
      counterType: 'success',
      badge: `₹${totalSalesRevenue.toFixed(0)} realized revenue`,
    },
    {
      id: 'inventory',
      name: 'Inventory Tracking',
      category: 'Warehouse Ops',
      desc: 'Real-time stock valuation, critical low-stock alerts, and movement audit logs.',
      path: '/inventory',
      icon: Boxes,
      gradient: 'linear-gradient(135deg, #2563eb, #3b82f6)',
      counter: lowStock.length > 0 ? `${lowStock.length} Low Stock` : 'Healthy',
      counterType: lowStock.length > 0 ? 'warning' : 'success',
      badge: `₹${totalValuation.toFixed(0)} total asset value`,
    },
    {
      id: 'suppliers',
      name: 'Suppliers & Vendors',
      category: 'Vendor Directory',
      desc: 'Vendor profiles, lead time schedules, contact directories, and procurement.',
      path: '/suppliers',
      icon: Truck,
      gradient: 'linear-gradient(135deg, #d97706, #f59e0b)',
      counter: `${suppliers.length} Vendors`,
      counterType: 'neutral',
      badge: 'Active supply network',
    },
    {
      id: 'purchase-orders',
      name: 'Purchase Orders',
      category: 'Procurement',
      desc: 'Vendor requisitions, multi-line order sheets, and lifecycle management.',
      path: '/purchase-orders',
      icon: ClipboardList,
      gradient: 'linear-gradient(135deg, #4f46e5, #6366f1)',
      counter: `${pendingPOs.length} Pending`,
      counterType: pendingPOs.length > 0 ? 'warning' : 'neutral',
      badge: 'Order management',
    },
    {
      id: 'receive-order',
      name: 'Receive Orders',
      category: 'Dock & Inbound',
      desc: 'Verify incoming dock shipments, enter received quantities, and update stock.',
      path: '/receive-order',
      icon: Inbox,
      gradient: 'linear-gradient(135deg, #0891b2, #06b6d4)',
      counter: 'Inbound Dock',
      counterType: 'info',
      badge: 'Line-by-line verification',
    },
    {
      id: 'dashboard',
      name: 'Executive Dashboard',
      category: 'Analytics & BI',
      desc: 'High-level executive metrics, periodic revenue, and warehouse activity.',
      path: '/dashboard',
      icon: LayoutDashboard,
      gradient: 'linear-gradient(135deg, #e11d48, #f43f5e)',
      counter: 'KPI Center',
      counterType: 'neutral',
      badge: 'Live Operations Performance',
    },
  ]

  return (
    <div className="landing-page" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Portal Hero Section */}
      <div
        style={{
          background: 'linear-gradient(135deg, var(--erp-surface) 0%, var(--erp-surface-subtle) 100%)',
          border: '1px solid var(--erp-border)',
          borderRadius: '12px',
          padding: '2.25rem 2rem',
          boxShadow: 'var(--shadow-sm)',
          position: 'relative',
          overflow: 'hidden',
          transition: 'background 0.25s ease, border-color 0.25s ease',
        }}
      >
        <div style={{ maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
            <span
              style={{
                backgroundColor: '#714b67',
                color: 'white',
                padding: '0.2rem 0.6rem',
                borderRadius: '999px',
                fontSize: '0.725rem',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
              }}
            >
              <Sparkles size={12} /> Operations Hub
            </span>
          </div>

          <h1
            style={{
              fontSize: '2.1rem',
              color: 'var(--erp-text-main)',
              lineHeight: 1.2,
              letterSpacing: '-0.025em',
            }}
          >
            Welcome to <span style={{ color: '#714b67' }}>StockSangati Operations Portal</span>
          </h1>

          <p style={{ color: '#64748b', fontSize: '0.95rem', lineHeight: 1.5 }}>
            Centralized inventory, point-of-sale, procurement, and warehouse operations portal.
            Select any business application below or press{' '}
            <kbd
              style={{
                background: 'var(--erp-surface)',
                border: '1px solid var(--erp-border)',
                padding: '2px 6px',
                borderRadius: '4px',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                color: 'var(--erp-text-main)',
              }}
            >
              Ctrl + K
            </kbd>{' '}
            for instant global search.
          </p>

          {/* Quick Search Launcher Bar */}
          <div
            onClick={() => dispatch(setCommandPaletteOpen(true))}
            style={{
              marginTop: '0.5rem',
              backgroundColor: 'var(--erp-surface)',
              border: '1px solid var(--erp-border)',
              borderRadius: '8px',
              padding: '0.65rem 1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              cursor: 'pointer',
              boxShadow: 'var(--shadow-xs)',
              maxWidth: '540px',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', color: 'var(--erp-text-muted)', fontSize: '0.875rem' }}>
              <Search size={18} color="var(--erp-brand)" />
              <span>Search products, purchase orders, or suppliers...</span>
            </div>
            <span
              style={{
                backgroundColor: 'var(--erp-surface-subtle)',
                color: 'var(--erp-text-muted)',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontFamily: 'var(--font-mono)',
              }}
            >
              ⌘K
            </span>
          </div>
        </div>
      </div>

      {/* Quick Stats Ticker Ribbon */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
          gap: '1rem',
        }}
      >
        <div style={{ background: 'var(--erp-surface)', border: '1px solid var(--erp-border)', borderRadius: '8px', padding: '1rem', boxShadow: 'var(--shadow-xs)', transition: 'all 0.2s ease' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Active Catalog</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--erp-text-main)' }}>{products.length} Products</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>{totalStockUnits.toLocaleString()} total units</div>
        </div>

        <div style={{ background: 'var(--erp-surface)', border: '1px solid var(--erp-border)', borderRadius: '8px', padding: '1rem', boxShadow: 'var(--shadow-xs)', transition: 'all 0.2s ease' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Stock Valuation</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#059669' }}>₹{totalValuation.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Current inventory asset value</div>
        </div>

        <div style={{ background: 'var(--erp-surface)', border: '1px solid var(--erp-border)', borderRadius: '8px', padding: '1rem', boxShadow: 'var(--shadow-xs)', transition: 'all 0.2s ease' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Recorded Sales</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#2563eb' }}>₹{totalSalesRevenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>From {sales.length} customer orders</div>
        </div>

        <div style={{ background: 'var(--erp-surface)', border: '1px solid var(--erp-border)', borderRadius: '8px', padding: '1rem', boxShadow: 'var(--shadow-xs)', transition: 'all 0.2s ease' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Vendor Network</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--erp-text-main)' }}>{suppliers.length} Suppliers</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>{pendingPOs.length} active purchase orders</div>
        </div>
      </div>

      {/* Signature App Launcher Grid */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.25rem', color: 'var(--erp-text-main)' }}>Operations & Business Modules</h2>
            <p style={{ fontSize: '0.825rem', color: '#64748b' }}>
              Core operational modules configured with Redux Toolkit and real-time backend synchronization.
            </p>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '1.25rem',
          }}
        >
          {apps.map((app) => {
            const Icon = app.icon

            return (
              <div
                key={app.id}
                onClick={() => navigate(app.path)}
                style={{
                  background: 'var(--erp-surface)',
                  border: '1px solid var(--erp-border)',
                  borderRadius: '10px',
                  padding: '1.4rem',
                  boxShadow: 'var(--shadow-xs)',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  position: 'relative',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-3px)'
                  e.currentTarget.style.boxShadow = 'var(--shadow-md)'
                  e.currentTarget.style.borderColor = 'var(--erp-brand-light)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)'
                  e.currentTarget.style.boxShadow = 'var(--shadow-xs)'
                  e.currentTarget.style.borderColor = 'var(--erp-border)'
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.85rem' }}>
                    <div
                      style={{
                        width: '48px',
                        height: '48px',
                        borderRadius: '10px',
                        background: app.gradient,
                        color: '#ffffff',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)',
                      }}
                    >
                      <Icon size={24} />
                    </div>

                    <span
                      style={{
                        fontSize: '0.725rem',
                        fontWeight: 700,
                        padding: '3px 8px',
                        borderRadius: '4px',
                        backgroundColor:
                          app.counterType === 'warning'
                            ? 'var(--status-warning-bg)'
                            : app.counterType === 'success'
                            ? 'var(--status-success-bg)'
                            : '#f1f5f9',
                        color:
                          app.counterType === 'warning'
                            ? 'var(--status-warning-text)'
                            : app.counterType === 'success'
                            ? 'var(--status-success-text)'
                            : '#475569',
                      }}
                    >
                      {app.counter}
                    </span>
                  </div>

                  <div style={{ fontSize: '0.725rem', textTransform: 'uppercase', color: '#64748b', fontWeight: 600 }}>
                    {app.category}
                  </div>
                  <h3 style={{ fontSize: '1.1rem', color: 'var(--erp-text-main)', marginTop: '2px' }}>
                    {app.name}
                  </h3>
                  <p style={{ fontSize: '0.825rem', color: '#64748b', marginTop: '0.35rem', lineHeight: 1.4 }}>
                    {app.desc}
                  </p>
                </div>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingTop: '0.75rem',
                    borderTop: '1px solid #f1f5f9',
                    fontSize: '0.8rem',
                    color: '#714b67',
                    fontWeight: 600,
                  }}
                >
                  <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 500 }}>
                    {app.badge}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                    <span>Launch</span>
                    <ArrowRight size={14} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Live Analytics & Performance Graphs */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <h2 style={{ fontSize: '1.25rem', color: 'var(--erp-text-main)' }}>Live Analytics & Improvement Trends</h2>
            <p style={{ fontSize: '0.825rem', color: 'var(--erp-text-muted)' }}>
              Real-time operational visualizations tracking revenue trajectory and asset allocation.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => navigate('/dashboard')}
            style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}
          >
            <span>Open Executive BI Center</span>
            <ArrowRight size={14} />
          </button>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <RevenueTrendChart sales={sales} />
          <CategoryValuationChart products={products} />
        </div>
      </div>

      {/* Quick Action Dock */}
      <div
        style={{
          background: 'var(--erp-surface)',
          border: '1px solid var(--erp-border)',
          borderRadius: '10px',
          padding: '1.25rem 1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
          transition: 'all 0.2s ease',
        }}
      >
        <div>
          <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--erp-text-main)' }}>
            Quick Operations Dock
          </div>
          <div style={{ fontSize: '0.775rem', color: '#64748b' }}>
            Fast-track transactions directly into backend business logic
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.625rem', flexWrap: 'wrap' }}>
          <button className="btn btn-primary btn-sm" onClick={() => navigate('/sales')}>
            <ShoppingCart size={14} />
            <span>+ Record Sale</span>
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/products')}>
            <Package size={14} />
            <span>+ New Product</span>
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/inventory')}>
            <Boxes size={14} />
            <span>+ Stock In</span>
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/purchase-orders')}>
            <ClipboardList size={14} />
            <span>+ New PO</span>
          </button>
        </div>
      </div>
    </div>
  )
}
