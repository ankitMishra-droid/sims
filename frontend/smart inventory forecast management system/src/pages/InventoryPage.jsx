import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import {
  Boxes,
  AlertTriangle,
  History,
  ArrowUpRight,
  ArrowDownRight,
  Plus,
  RefreshCw,
  Search,
  CheckCircle,
  Clock,
  Layers,
} from 'lucide-react'
import {
  selectAllProducts,
  selectLowStockProducts,
  selectProductsLoading,
  fetchProducts,
  stockInProduct,
} from '../store/productsSlice'
import {
  fetchInventoryLogs,
  selectLogsForProduct,
} from '../store/inventorySlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import KpiCard from '../components/common/KpiCard'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import SearchableSelect from '../components/common/SearchableSelect'

export default function InventoryPage() {
  const dispatch = useDispatch()
  const products = useSelector(selectAllProducts)
  const lowStockProducts = useSelector(selectLowStockProducts)
  const loading = useSelector(selectProductsLoading)

  const [activeTab, setActiveTab] = useState('stock') // 'stock' | 'low-stock' | 'logs'
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedProductForLogs, setSelectedProductForLogs] = useState('')

  // Selected product logs from Redux
  const logs = useSelector(selectLogsForProduct(selectedProductForLogs))

  // Quick Stock-In modal
  const [isStockInOpen, setIsStockInOpen] = useState(false)
  const [stockInData, setStockInData] = useState({
    product_id: '',
    quantity: 10,
    reason: 'purchase',
  })
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  // Memoized product options for searchable typeahead
  const productOptions = useMemo(() => {
    return products.map((p) => ({
      value: p.id,
      label: p.name,
      subLabel: `${p.category || 'General'} • Stock: ${p.current_stock} ${p.unit}`,
      badge: p.sku,
      meta: `₹${p.selling_price}`,
    }))
  }, [products])

  // Select initial product for logs when products load
  useEffect(() => {
    if (products.length > 0 && !selectedProductForLogs) {
      const firstId = String(products[0].id)
      setSelectedProductForLogs(firstId)
      dispatch(fetchInventoryLogs(firstId))
    }
  }, [products, selectedProductForLogs, dispatch])

  const handleSelectProductForLogs = (pid) => {
    setSelectedProductForLogs(pid)
    dispatch(fetchInventoryLogs(pid))
  }

  // Aggregate KPI metrics
  const totalStockUnits = useMemo(() => {
    return products.reduce((acc, p) => acc + (Number(p.current_stock) || 0), 0)
  }, [products])

  const totalInventoryValuation = useMemo(() => {
    return products.reduce((acc, p) => {
      const stock = Number(p.current_stock) || 0
      const cost = Number(p.cost_price) || 0
      return acc + stock * cost
    }, 0)
  }, [products])

  // Open Stock In Modal
  const openStockInModal = useCallback(
    (prod = null) => {
      setStockInData({
        product_id: prod ? String(prod.id) : products[0] ? String(products[0].id) : '',
        quantity: 10,
        reason: 'purchase',
      })
      setFormError('')
      setIsStockInOpen(true)
    },
    [products]
  )

  // Submit Stock In
  const handleStockInSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')

    const pid = parseInt(stockInData.product_id, 10)
    const qty = parseInt(stockInData.quantity, 10)

    if (!pid) {
      setFormError('Please select a product.')
      setSubmitting(false)
      return
    }

    const res = await dispatch(
      stockInProduct({
        product_id: pid,
        quantity: qty,
        reason: stockInData.reason,
      })
    )

    if (stockInProduct.rejected.match(res)) {
      setFormError(res.payload || 'Failed to adjust stock.')
    } else {
      setIsStockInOpen(false)
      if (selectedProductForLogs === String(pid)) {
        dispatch(fetchInventoryLogs(pid))
      }
    }
    setSubmitting(false)
  }

  // Stock Overview Columns
  const stockColumns = useMemo(
    () => [
      {
        key: 'sku',
        label: 'SKU',
        sortable: true,
        render: (p) => (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              color: 'var(--erp-brand)',
              backgroundColor: 'var(--erp-brand-subtle)',
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '0.775rem',
            }}
          >
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
            <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>{p.name}</div>
            <div style={{ fontSize: '0.725rem', color: 'var(--erp-text-muted)' }}>Unit: {p.unit}</div>
          </div>
        ),
      },
      {
        key: 'category',
        label: 'Category',
        sortable: true,
        render: (p) => p.category || 'General',
      },
      {
        key: 'current_stock',
        label: 'In-Stock Units',
        numeric: true,
        sortable: true,
        render: (p) => {
          const isLow = p.current_stock <= p.reorder_level
          const isOut = p.current_stock === 0
          return (
            <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>
              <span style={{ color: isOut ? '#dc2626' : isLow ? '#d97706' : '#059669' }}>
                {p.current_stock}
              </span>{' '}
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>{p.unit}</span>
            </div>
          )
        },
      },
      {
        key: 'reorder_level',
        label: 'Reorder Point',
        numeric: true,
        sortable: true,
        render: (p) => `${p.reorder_level} ${p.unit}`,
      },
      {
        key: 'status',
        label: 'Health Status',
        sortable: false,
        render: (p) => {
          const isLow = p.current_stock <= p.reorder_level
          const isOut = p.current_stock === 0
          return isOut ? (
            <Badge status="OUT OF STOCK" label="Out of Stock" />
          ) : isLow ? (
            <Badge status="LOW STOCK" label="Low Stock Alert" />
          ) : (
            <Badge status="HEALTHY" label="Healthy Stock" />
          )
        },
      },
      {
        key: 'cost_price',
        label: 'Unit Cost',
        numeric: true,
        sortable: true,
        render: (p) => `₹${Number(p.cost_price).toFixed(2)}`,
      },
      {
        key: 'total_value',
        label: 'Asset Value',
        numeric: true,
        sortable: true,
        render: (p) => {
          const val = (Number(p.current_stock) || 0) * (Number(p.cost_price) || 0)
          return <span style={{ fontWeight: 600 }}>₹{val.toFixed(2)}</span>
        },
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (p) => (
          <div className="actions-group">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => openStockInModal(p)}
              title="Add units"
            >
              <Plus size={13} />
              <span>Stock In</span>
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                handleSelectProductForLogs(String(p.id))
                setActiveTab('logs')
              }}
              title="Audit Log"
            >
              <History size={13} />
              <span>Logs</span>
            </button>
          </div>
        ),
      },
    ],
    [openStockInModal]
  )

  // Low Stock Columns
  const lowStockColumns = useMemo(
    () => [
      {
        key: 'sku',
        label: 'SKU',
        sortable: true,
        render: (p) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#dc2626' }}>
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
        label: 'Current Stock',
        numeric: true,
        sortable: true,
        render: (p) => (
          <span style={{ fontWeight: 800, color: '#dc2626', fontSize: '1rem' }}>
            {p.current_stock} {p.unit}
          </span>
        ),
      },
      {
        key: 'reorder_level',
        label: 'Reorder Threshold',
        numeric: true,
        sortable: true,
        render: (p) => `${p.reorder_level} ${p.unit}`,
      },
      {
        key: 'deficit',
        label: 'Deficit Needed',
        numeric: true,
        sortable: false,
        render: (p) => {
          const def = Math.max(0, p.reorder_level - p.current_stock)
          return (
            <span style={{ color: '#d97706', fontWeight: 700 }}>
              +{def + 10} {p.unit} (recommended)
            </span>
          )
        },
      },
      {
        key: 'status',
        label: 'Alert Level',
        center: true,
        sortable: false,
        render: (p) => (
          <Badge
            status={p.current_stock === 0 ? 'OUT OF STOCK' : 'LOW STOCK'}
            label={p.current_stock === 0 ? 'Depleted (0)' : 'Critical Low'}
          />
        ),
      },
      {
        key: 'action',
        label: 'Replenish',
        center: true,
        sortable: false,
        render: (p) => (
          <button className="btn btn-primary btn-sm" onClick={() => openStockInModal(p)}>
            <Plus size={13} />
            <span>Replenish Stock</span>
          </button>
        ),
      },
    ],
    [openStockInModal]
  )

  // Movement Logs Columns
  const logColumns = useMemo(
    () => [
      {
        key: 'id',
        label: 'Log ID',
        sortable: true,
        render: (log) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: '#64748b' }}>
            #{log.id}
          </span>
        ),
      },
      {
        key: 'timestamp',
        label: 'Date & Time',
        sortable: true,
        render: (log) => {
          const dateStr = log.timestamp
            ? new Date(log.timestamp).toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })
            : '—'
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8rem', color: '#475569' }}>
              <Clock size={13} color="#94a3b8" />
              <span>{dateStr}</span>
            </div>
          )
        },
      },
      {
        key: 'movement_type',
        label: 'Movement Type',
        sortable: false,
        render: (log) => {
          const isStockIn = log.stock_in > 0
          return isStockIn ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#059669', fontWeight: 600 }}>
              <ArrowUpRight size={14} /> Stock In
            </span>
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#dc2626', fontWeight: 600 }}>
              <ArrowDownRight size={14} /> Stock Out
            </span>
          )
        },
      },
      {
        key: 'stock_in',
        label: 'Stock In (+)',
        numeric: true,
        sortable: true,
        render: (log) => (
          <span style={{ color: log.stock_in > 0 ? '#059669' : '#94a3b8', fontWeight: log.stock_in > 0 ? 700 : 400 }}>
            {log.stock_in > 0 ? `+${log.stock_in}` : '—'}
          </span>
        ),
      },
      {
        key: 'stock_out',
        label: 'Stock Out (-)',
        numeric: true,
        sortable: true,
        render: (log) => (
          <span style={{ color: log.stock_out > 0 ? '#dc2626' : '#94a3b8', fontWeight: log.stock_out > 0 ? 700 : 400 }}>
            {log.stock_out > 0 ? `-${log.stock_out}` : '—'}
          </span>
        ),
      },
      {
        key: 'closing_stock',
        label: 'Closing Stock',
        numeric: true,
        sortable: true,
        render: (log) => <span style={{ fontWeight: 800 }}>{log.closing_stock}</span>,
      },
      {
        key: 'reason',
        label: 'Reason / Reference',
        sortable: true,
        render: (log) => <Badge status={log.reason} />,
      },
    ],
    []
  )

  return (
    <div className="inventory-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Warehouse"
        activePage="Inventory Tracking"
        itemCount={activeTab === 'stock' ? products.length : activeTab === 'low-stock' ? lowStockProducts.length : logs.length}
        primaryAction={{
          label: 'Stock In / Adjustment',
          icon: Plus,
          onClick: () => openStockInModal(),
          id: 'btn-stock-in-inventory',
        }}
        onRefresh={() => {
          dispatch(fetchProducts())
          if (selectedProductForLogs) dispatch(fetchInventoryLogs(selectedProductForLogs))
        }}
        loading={loading}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="Search inventory by SKU, name, or category..."
        exportData={activeTab === 'stock' ? products : activeTab === 'low-stock' ? lowStockProducts : logs}
        exportFilename={activeTab === 'stock' ? 'inventory_stock' : activeTab === 'low-stock' ? 'low_stock_alerts' : 'movement_history'}
        filters={
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className={`btn btn-sm ${activeTab === 'stock' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('stock')}
            >
              <Boxes size={14} />
              <span>Stock Overview</span>
            </button>
            <button
              type="button"
              className={`btn btn-sm ${activeTab === 'low-stock' ? 'btn-danger' : 'btn-secondary'}`}
              onClick={() => setActiveTab('low-stock')}
            >
              <AlertTriangle size={14} />
              <span>Low Stock Alerts ({lowStockProducts.length})</span>
            </button>
            <button
              type="button"
              className={`btn btn-sm ${activeTab === 'logs' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActiveTab('logs')}
            >
              <History size={14} />
              <span>Movement History</span>
            </button>
          </div>
        }
      />

      {/* KPI Cards */}
      <div className="kpi-grid">
        <KpiCard
          label="Total In-Stock Units"
          value={totalStockUnits.toLocaleString()}
          subtitle={`Across ${products.length} master items`}
          icon={Boxes}
          variant="blue"
        />
        <KpiCard
          label="Inventory Valuation"
          value={`₹${totalInventoryValuation.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle="Warehouse inventory cost basis"
          icon={Layers}
          variant="emerald"
        />
        <KpiCard
          label="Low Stock Alert SKUs"
          value={lowStockProducts.length}
          subtitle={lowStockProducts.length > 0 ? 'Requires immediate replenishment' : 'All items healthy'}
          icon={AlertTriangle}
          variant={lowStockProducts.length > 0 ? 'rose' : 'emerald'}
        />
      </div>

      {/* TAB 1: Stock Overview */}
      {activeTab === 'stock' && (
        <DataTable
          columns={stockColumns}
          data={products}
          keyField="id"
          defaultPageSize={10}
          searchQuery={searchQuery}
          searchFields={['name', 'sku', 'category']}
          loading={loading}
          emptyTitle="No inventory records found"
          emptyMessage="Add products to warehouse catalog to see stock tracking."
          emptyIcon={Boxes}
        />
      )}

      {/* TAB 2: Low-Stock Alerts */}
      {activeTab === 'low-stock' && (
        <DataTable
          columns={lowStockColumns}
          data={lowStockProducts}
          keyField="id"
          defaultPageSize={10}
          searchQuery={searchQuery}
          searchFields={['name', 'sku', 'category']}
          loading={loading}
          emptyTitle="All inventory stock levels are healthy!"
          emptyMessage="No items currently at or below their safety reorder threshold."
          emptyIcon={CheckCircle}
        />
      )}

      {/* TAB 3: Movement History */}
      {activeTab === 'logs' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* Product Selector for Logs */}
          <div
            style={{
              background: 'var(--erp-surface)',
              border: '1px solid var(--erp-border)',
              borderRadius: '8px',
              padding: '0.85rem 1.25rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '1rem',
              transition: 'background-color 0.25s ease, border-color 0.25s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, minWidth: '320px', maxWidth: '520px' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--erp-text-main)', whiteSpace: 'nowrap' }}>
                Audit Log For Product:
              </span>
              <div style={{ flex: 1 }}>
                <SearchableSelect
                  options={productOptions}
                  value={selectedProductForLogs}
                  onChange={(val) => handleSelectProductForLogs(val)}
                  placeholder="Type to search product by name or SKU..."
                  id="select-inventory-log-product"
                />
              </div>
            </div>

            <button
              className="btn btn-secondary btn-sm"
              onClick={() => dispatch(fetchInventoryLogs(selectedProductForLogs))}
            >
              <RefreshCw size={13} />
              <span>Refresh Log</span>
            </button>
          </div>

          <DataTable
            columns={logColumns}
            data={logs}
            keyField="id"
            defaultPageSize={10}
            loading={loading}
            emptyTitle="No movement logs found for this item"
            emptyMessage="No stock transactions logged yet."
            emptyIcon={History}
          />
        </div>
      )}

      {/* Stock In Modal */}
      <Modal
        isOpen={isStockInOpen}
        onClose={() => setIsStockInOpen(false)}
        title="Stock Adjustment / Stock In"
        subtitle="Backend automatically validates quantity > 0 and creates an inventory movement log."
      >
        <form onSubmit={handleStockInSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>
                  <strong>Backend Validation Rule:</strong> {formError}
                </div>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">
                Select Product <span className="required">*</span>
              </label>
              <SearchableSelect
                options={productOptions}
                value={stockInData.product_id}
                onChange={(val) => setStockInData({ ...stockInData, product_id: val })}
                placeholder="Search product item by name or SKU..."
                id="select-stock-in-product"
              />
            </div>

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">
                  Quantity to Add <span className="required">*</span>
                </label>
                <input
                  type="number"
                  min="1"
                  required
                  className="form-control"
                  value={stockInData.quantity}
                  onChange={(e) => setStockInData({ ...stockInData, quantity: e.target.value })}
                />
                <span className="form-hint">Backend validates quantity &gt; 0.</span>
              </div>

              <div className="form-group">
                <label className="form-label">Reason / Transaction Type</label>
                <select
                  className="form-control"
                  value={stockInData.reason}
                  onChange={(e) => setStockInData({ ...stockInData, reason: e.target.value })}
                >
                  <option value="purchase">Purchase (New Stock)</option>
                  <option value="return">Customer Return</option>
                  <option value="adjustment">Stock Count Adjustment</option>
                  <option value="production">Production / Internal Transfer</option>
                </select>
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsStockInOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              id="btn-confirm-stock-in"
            >
              {submitting ? 'Applying...' : 'Confirm Stock Addition'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
