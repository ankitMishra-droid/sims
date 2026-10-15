import React, { useState, useEffect, useMemo, useRef } from 'react'
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
  X,
  Command,
} from 'lucide-react'
import { selectAllProducts } from '../../store/productsSlice'
import { selectAllSuppliers } from '../../store/suppliersSlice'
import { selectAllPurchaseOrders } from '../../store/purchaseOrdersSlice'
import { setCommandPaletteOpen } from '../../store/uiSlice'

export default function CommandPalette() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const isOpen = useSelector((state) => state.ui.commandPaletteOpen)

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
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Static navigation routes
  const navigationItems = [
    { type: 'Page', title: 'Products Catalog', path: '/products', icon: Package },
    { type: 'Page', title: 'Sales & POS', path: '/sales', icon: ShoppingCart },
    { type: 'Page', title: 'Inventory & Stock History', path: '/inventory', icon: Boxes },
    { type: 'Page', title: 'Vendors & Suppliers', path: '/suppliers', icon: Truck },
    { type: 'Page', title: 'Purchase Orders', path: '/purchase-orders', icon: ClipboardList },
    { type: 'Page', title: 'Receive Inbound Orders', path: '/receive-order', icon: Inbox },
    { type: 'Page', title: 'Executive Dashboard', path: '/dashboard', icon: LayoutDashboard },
  ]

  // Filtered search results
  const results = useMemo(() => {
    const q = query.toLowerCase().trim()
    if (!q) {
      return navigationItems.map((n) => ({ ...n, subtitle: 'Go to module' }))
    }

    const items = []

    // Match pages
    navigationItems.forEach((n) => {
      if (n.title.toLowerCase().includes(q)) {
        items.push({ ...n, subtitle: 'Go to module' })
      }
    })

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
          subtitle: `In Stock: ${p.current_stock} ${p.unit} &bull; ₹${Number(p.selling_price).toFixed(2)}`,
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
          subtitle: `Contact: ${s.contact_person || s.email || 'Vendor'} &bull; Lead Time: ${s.lead_time_days || 7}d`,
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
          subtitle: `Status: ${o.status} &bull; ${o.items?.length || 0} line(s)`,
          path: `/receive-order?order_id=${o.id}`,
          icon: ClipboardList,
        })
      }
    })

    return items.slice(0, 10)
  }, [query, products, suppliers, orders])

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
                      <div
                        style={{ fontSize: '0.75rem', color: '#64748b' }}
                        dangerouslySetInnerHTML={{ __html: item.subtitle }}
                      />
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
