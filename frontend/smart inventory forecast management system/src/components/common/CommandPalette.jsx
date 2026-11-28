import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  Search,
  Package,
  ShoppingCart,
  Boxes,
  Truck,
  ClipboardList,
  Inbox,
  LayoutDashboard,
  ArrowRight,
  BrainCircuit,
  Sliders,
  CheckCircle2,
} from 'lucide-react'
import { selectAllProducts } from '../../store/productsSlice'
import { selectAllSuppliers } from '../../store/suppliersSlice'
import { selectAllPurchaseOrders } from '../../store/purchaseOrdersSlice'
import { setCommandPaletteOpen } from '../../store/uiSlice'

const NAVIGATION_ITEMS = [
  { type: 'Page', title: 'Dashboard', path: '/dashboard', icon: LayoutDashboard, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Supplier Portal', path: '/supplier-portal', icon: ClipboardList, businessTypes: ['supplier'] },
  { type: 'Page', title: 'Products', path: '/products', icon: Package, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Stock Management', path: '/inventory', icon: Boxes, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Stock History', path: '/inventory/history', icon: Boxes, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Stock Adjustments', path: '/inventory/adjustments', icon: Sliders, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Record Sale', path: '/sales/new', icon: ShoppingCart, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Sales History', path: '/sales', icon: ShoppingCart, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Suppliers', path: '/suppliers', icon: Truck, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Purchase Orders', path: '/purchase-orders', icon: ClipboardList, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Receive Orders', path: '/receive-order', icon: Inbox, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Intelligence Overview', path: '/intelligence', icon: BrainCircuit, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Reorder Suggestions', path: '/reorder-planner', icon: CheckCircle2, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Demand Forecasts', path: '/forecasting', icon: BrainCircuit, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'What-If Simulator', path: '/simulator', icon: Sliders, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Stock Alerts', path: '/stock-alerts', icon: BrainCircuit, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'AI Knowledge Base', path: '/ai-knowledge', icon: BrainCircuit },
  { type: 'Page', title: 'AI Usage & Credits', path: '/ai-usage', icon: BrainCircuit },
  { type: 'Page', title: 'Inventory Reports', path: '/reports/inventory', icon: LayoutDashboard, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Sales Reports', path: '/reports/sales', icon: LayoutDashboard, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Procurement Reports', path: '/reports/procurement', icon: LayoutDashboard, businessTypes: ['retailer', 'wholesaler'] },
  { type: 'Page', title: 'Workspaces', path: '/workspaces', icon: LayoutDashboard },
  { type: 'Page', title: 'Setup Wizard', path: '/onboarding', icon: CheckCircle2 },
  { type: 'Page', title: 'Business Settings', path: '/settings/business', icon: Sliders },
  { type: 'Page', title: 'Team & Roles', path: '/settings/team', icon: Truck },
  { type: 'Page', title: 'Security & Password', path: '/settings/security', icon: Sliders },
  { type: 'Page', title: 'Language Settings', path: '/settings/language', icon: Sliders },
]

export default function CommandPalette() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const isOpen = useSelector((state) => state.ui.commandPaletteOpen)
  const currentWorkspace = useSelector((state) => state.auth.currentWorkspace)
  const activeBusinessType = String(currentWorkspace?.business?.business_type || 'retailer').toLowerCase()

  const products = useSelector(selectAllProducts)
  const suppliers = useSelector(selectAllSuppliers)
  const orders = useSelector(selectAllPurchaseOrders)

  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)

  // Listen for Ctrl+K / Cmd+K shortcut
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        dispatch(setCommandPaletteOpen(!isOpen))
      } else if (e.key === 'Escape' && isOpen) {
        dispatch(setCommandPaletteOpen(false))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, dispatch])

  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => {
        setQuery('')
        setSelectedIndex(0)
        inputRef.current?.focus()
      }, 0)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  // Filtered search results
  const results = useMemo(() => {
    const allowedPages = NAVIGATION_ITEMS.filter(
      (n) => !n.businessTypes || n.businessTypes.includes(activeBusinessType)
    )
    const q = query.toLowerCase().trim()
    if (!q) {
      return allowedPages.map((n) => ({ ...n, subtitle: 'Go to module' }))
    }

    const items = []

    // Match pages
    allowedPages.forEach((n) => {
      if (n.title.toLowerCase().includes(q)) {
        items.push({ ...n, subtitle: 'Go to module' })
      }
    })

    if (activeBusinessType === 'supplier') {
      return items.slice(0, 10)
    }

    // Match products
    products.forEach((p) => {
      if (
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        (p.category && p.category.toLowerCase().includes(q))
      ) {
        items.push({
          type: 'Product',
          title: `${p.name} (${p.sku})`,
          subtitle: `In Stock: ${p.current_stock} ${p.unit} • ₹${Number(p.selling_price).toFixed(2)}`,
          path: `/products?search=${encodeURIComponent(p.sku)}`,
          icon: Package,
        })
      }
    })

    // Match suppliers
    suppliers.forEach((s) => {
      if (
        s.name.toLowerCase().includes(q) ||
        (s.email && s.email.toLowerCase().includes(q)) ||
        (s.contact_person && s.contact_person.toLowerCase().includes(q))
      ) {
        items.push({
          type: 'Supplier',
          title: s.name,
          subtitle: `Contact: ${s.contact_person || s.email || 'Vendor'} • Lead Time: ${s.lead_time_days || 7}d`,
          path: `/suppliers?search=${encodeURIComponent(s.name)}`,
          icon: Truck,
        })
      }
    })

    // Match POs
    orders.forEach((o) => {
      if (String(o.id).includes(q) || (o.notes && o.notes.toLowerCase().includes(q))) {
        items.push({
          type: 'Purchase Order',
          title: `PO-${String(o.id).padStart(4, '0')}`,
          subtitle: `Status: ${o.status} • ${o.items?.length || 0} line(s)`,
          path: `/receive-order?order_id=${o.id}`,
          icon: ClipboardList,
        })
      }
    })

    return items.slice(0, 10)
  }, [query, products, suppliers, orders, activeBusinessType])

  const handleSelect = (item) => {
    dispatch(setCommandPaletteOpen(false))
    navigate(item.path)
  }

  // Keyboard navigation within list
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, results.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev - 1 + results.length) % Math.max(1, results.length))
    } else if (e.key === 'Enter' && results[selectedIndex]) {
      e.preventDefault()
      handleSelect(results[selectedIndex])
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) dispatch(setCommandPaletteOpen(false))
      }}
    >
      <div
        className="modal-sheet"
        style={{ maxWidth: '600px', maxHeight: '520px', overflow: 'hidden' }}
      >
        {/* Search Input Bar */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--erp-border)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            backgroundColor: 'var(--erp-surface)',
          }}
        >
          <Search size={20} color="var(--erp-brand)" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a product, SKU, PO number, vendor, or page..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
            style={{
              border: 'none',
              outline: 'none',
              width: '100%',
              fontSize: '1rem',
              color: 'var(--erp-text-main)',
              fontFamily: 'inherit',
              backgroundColor: 'transparent',
            }}
          />
          <span
            style={{
              fontSize: '0.7rem',
              backgroundColor: 'var(--erp-surface-subtle)',
              padding: '2px 6px',
              borderRadius: '4px',
              color: 'var(--erp-text-muted)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            ESC to close
          </span>
        </div>

        {/* Results List */}
        <div style={{ maxHeight: '420px', overflowY: 'auto', padding: '0.5rem', backgroundColor: 'var(--erp-surface)' }}>
          {results.length === 0 ? (
            <div style={{ padding: '2.5rem 1rem', textAlign: 'center', color: 'var(--erp-text-muted)', fontSize: '0.85rem' }}>
              No matches found for "{query}".
            </div>
          ) : (
            results.map((item, idx) => {
              const Icon = item.icon
              const isSelected = selectedIndex === idx

              return (
                <div
                  key={idx}
                  onClick={() => handleSelect(item)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.65rem 0.85rem',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'var(--erp-brand-subtle)' : 'transparent',
                    color: isSelected ? 'var(--erp-brand)' : 'var(--erp-text-main)',
                    transition: 'background-color 0.1s ease',
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div
                      style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: '6px',
                        backgroundColor: isSelected ? 'var(--erp-surface)' : 'var(--erp-surface-subtle)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: isSelected ? 'var(--erp-brand)' : 'var(--erp-text-muted)',
                      }}
                    >
                      <Icon size={16} />
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>{item.title}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                        {item.subtitle}
                      </div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span
                      style={{
                        fontSize: '0.675rem',
                        textTransform: 'uppercase',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        backgroundColor: '#f1f5f9',
                        color: '#64748b',
                        fontWeight: 600,
                      }}
                    >
                      {item.type}
                    </span>
                    <ArrowRight size={14} color="#94a3b8" />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
