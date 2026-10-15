import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import {
  Package,
  Plus,
  RefreshCw,
  AlertTriangle,
  Boxes,
  Edit2,
  Power,
  TrendingUp,
} from 'lucide-react'
import {
  selectAllProducts,
  selectProductsLoading,
  selectProductCategories,
  fetchProducts,
  createProduct,
  updateProduct,
  toggleProductActive,
  stockInProduct,
} from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import SearchableSelect from '../components/common/SearchableSelect'

export default function ProductsPage() {
  const dispatch = useDispatch()
  const products = useSelector(selectAllProducts)
  const loading = useSelector(selectProductsLoading)
  const categories = useSelector(selectProductCategories)
  const suppliers = useSelector(selectAllSuppliers)

  // Local UI State
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('ALL')
  const [stockFilter, setStockFilter] = useState('ALL')
  const [viewMode, setViewMode] = useState('table') // 'table' | 'kanban'

  // Modals state
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isStockInOpen, setIsStockInOpen] = useState(false)
  const [selectedProduct, setSelectedProduct] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  // Form states
  const [formData, setFormData] = useState({
    sku: '',
    name: '',
    category: '',
    unit: 'piece',
    cost_price: 10,
    selling_price: 15,
    current_stock: 0,
    reorder_level: 10,
    supplier_id: '',
  })

  const [stockInData, setStockInData] = useState({
    quantity: 10,
    reason: 'purchase',
  })

  useEffect(() => {
    dispatch(fetchProducts())
    dispatch(fetchSuppliers())
  }, [dispatch])

  // Memoized searchable supplier options
  const supplierOptions = useMemo(() => {
    return [
      { value: '', label: '-- No Supplier Assigned --' },
      ...suppliers.map((s) => ({
        value: s.id,
        label: s.name,
        subLabel: s.contact_person ? `${s.contact_person} • ${s.email || ''}` : (s.email || 'Supplier'),
        badge: `ID #${s.id}`,
      })),
    ]
  }, [suppliers])

  // Memoized filtered list
  const filteredProducts = useMemo(() => {
    return products.filter((p) => {
      const q = searchQuery.toLowerCase().trim()
      const matchesSearch =
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        (p.category && p.category.toLowerCase().includes(q))

      const matchesCategory = categoryFilter === 'ALL' || p.category === categoryFilter

      let matchesStock = true
      if (stockFilter === 'LOW') {
        matchesStock = p.current_stock <= p.reorder_level && p.current_stock > 0
      } else if (stockFilter === 'OUT') {
        matchesStock = p.current_stock === 0
      } else if (stockFilter === 'HEALTHY') {
        matchesStock = p.current_stock > p.reorder_level
      }

      return matchesSearch && matchesCategory && matchesStock
    })
  }, [products, searchQuery, categoryFilter, stockFilter])

  // Open Add modal with clean state
  const openAddModal = useCallback(() => {
    setFormData({
      sku: `SKU-${String(products.length + 1).padStart(4, '0')}`,
      name: '',
      category: categories[0] || 'General',
      unit: 'piece',
      cost_price: 10,
      selling_price: 15,
      current_stock: 0,
      reorder_level: 10,
      supplier_id: suppliers[0]?.id || '',
    })
    setFormError('')
    setIsAddOpen(true)
  }, [products.length, categories, suppliers])

  // Handle Add Product Submit
  const handleAddSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')

    const payload = {
      sku: formData.sku.trim(),
      name: formData.name.trim(),
      category: formData.category.trim() || null,
      unit: formData.unit.trim() || 'piece',
      cost_price: parseFloat(formData.cost_price) || 0,
      selling_price: parseFloat(formData.selling_price) || 0,
      current_stock: parseInt(formData.current_stock, 10) || 0,
      reorder_level: parseInt(formData.reorder_level, 10) || 10,
      supplier_id: formData.supplier_id ? parseInt(formData.supplier_id, 10) : null,
    }

    const res = await dispatch(createProduct(payload))
    if (createProduct.rejected.match(res)) {
      setFormError(res.payload || 'Failed to create product.')
    } else {
      setIsAddOpen(false)
    }
    setSubmitting(false)
  }

  // Open Edit
  const openEdit = useCallback((product) => {
    setSelectedProduct(product)
    setFormData({
      sku: product.sku,
      name: product.name,
      category: product.category || '',
      unit: product.unit || 'piece',
      cost_price: product.cost_price,
      selling_price: product.selling_price,
      current_stock: product.current_stock,
      reorder_level: product.reorder_level,
      supplier_id: product.supplier_id || '',
    })
    setFormError('')
    setIsEditOpen(true)
  }, [])

  // Handle Edit Submit
  const handleEditSubmit = async (e) => {
    e.preventDefault()
    if (!selectedProduct) return
    setSubmitting(true)
    setFormError('')

    const payload = {
      sku: formData.sku.trim(),
      name: formData.name.trim(),
      category: formData.category.trim() || null,
      unit: formData.unit.trim() || 'piece',
      cost_price: parseFloat(formData.cost_price) || 0,
      selling_price: parseFloat(formData.selling_price) || 0,
      current_stock: parseInt(formData.current_stock, 10) || 0,
      reorder_level: parseInt(formData.reorder_level, 10) || 10,
      supplier_id: formData.supplier_id ? parseInt(formData.supplier_id, 10) : null,
    }

    const res = await dispatch(updateProduct({ id: selectedProduct.id, payload }))
    if (updateProduct.rejected.match(res)) {
      setFormError(res.payload || 'Failed to update product.')
    } else {
      setIsEditOpen(false)
    }
    setSubmitting(false)
  }

  // Open Stock In
  const openStockIn = useCallback((product) => {
    setSelectedProduct(product)
    setStockInData({ quantity: 10, reason: 'purchase' })
    setFormError('')
    setIsStockInOpen(true)
  }, [])

  // Handle Stock In Submit
  const handleStockInSubmit = async (e) => {
    e.preventDefault()
    if (!selectedProduct) return
    setSubmitting(true)
    setFormError('')

    const qty = parseInt(stockInData.quantity, 10)
    const res = await dispatch(
      stockInProduct({
        product_id: selectedProduct.id,
        quantity: qty,
        reason: stockInData.reason,
      })
    )

    if (stockInProduct.rejected.match(res)) {
      setFormError(res.payload || 'Stock adjustment failed.')
    } else {
      setIsStockInOpen(false)
    }
    setSubmitting(false)
  }

  // Table Column Definitions
  const columns = useMemo(
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
        label: 'Product Name',
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
        render: (p) => (
          <span
            style={{
              backgroundColor: 'var(--erp-surface-subtle)',
              padding: '3px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              color: 'var(--erp-text-muted)',
              border: '1px solid var(--erp-border)',
            }}
          >
            {p.category || 'General'}
          </span>
        ),
      },
      {
        key: 'stock_meter',
        label: 'Stock Health',
        sortable: false,
        render: (p) => {
          const isLow = p.current_stock <= p.reorder_level
          const isOut = p.current_stock === 0
          const ratio = Math.min(100, Math.round((p.current_stock / (p.reorder_level * 2 || 1)) * 100))

          return (
            <div className="stock-meter-wrapper">
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.725rem' }}>
                {isOut ? (
                  <Badge status="OUT OF STOCK" label="Out of Stock" />
                ) : isLow ? (
                  <Badge status="LOW STOCK" label="Low Stock" />
                ) : (
                  <Badge status="HEALTHY" label="Normal" />
                )}
              </div>
              <div className="stock-meter-bar">
                <div
                  className={`stock-meter-fill ${isOut ? 'critical' : isLow ? 'warning' : 'healthy'}`}
                  style={{ width: `${Math.max(5, ratio)}%` }}
                />
              </div>
            </div>
          )
        },
      },
      {
        key: 'current_stock',
        label: 'In Stock',
        numeric: true,
        sortable: true,
        render: (p) => {
          const isLow = p.current_stock <= p.reorder_level
          const isOut = p.current_stock === 0
          return (
            <div>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: '0.95rem',
                  color: isOut ? '#dc2626' : isLow ? '#d97706' : '#059669',
                }}
              >
                {p.current_stock}
              </span>{' '}
              <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>{p.unit}</span>
            </div>
          )
        },
      },
      {
        key: 'reorder_level',
        label: 'Reorder Point',
        numeric: true,
        sortable: true,
        render: (p) => (
          <span style={{ color: 'var(--erp-text-muted)' }}>
            {p.reorder_level} {p.unit}
          </span>
        ),
      },
      {
        key: 'cost_price',
        label: 'Cost Price',
        numeric: true,
        sortable: true,
        render: (p) => `₹${Number(p.cost_price).toFixed(2)}`,
      },
      {
        key: 'selling_price',
        label: 'Selling Price',
        numeric: true,
        sortable: true,
        render: (p) => (
          <span style={{ fontWeight: 600 }}>₹{Number(p.selling_price).toFixed(2)}</span>
        ),
      },
      {
        key: 'margin',
        label: 'Margin %',
        numeric: true,
        sortable: false,
        render: (p) => {
          const cost = Number(p.cost_price) || 0
          const sell = Number(p.selling_price) || 0
          const margin = sell > 0 ? (((sell - cost) / sell) * 100).toFixed(1) : 0
          return (
            <span
              style={{
                fontSize: '0.775rem',
                fontWeight: 600,
                color: margin > 20 ? '#059669' : margin > 0 ? '#d97706' : '#dc2626',
              }}
            >
              {margin}%
            </span>
          )
        },
      },
      {
        key: 'supplier',
        label: 'Supplier',
        sortable: false,
        render: (p) => {
          const supp = suppliers.find((s) => s.id === p.supplier_id)
          return (
            <span style={{ fontSize: '0.8rem', color: 'var(--erp-text-main)' }}>
              {supp ? supp.name : p.supplier_id ? `Supplier #${p.supplier_id}` : '—'}
            </span>
          )
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
              onClick={() => openStockIn(p)}
              title="Stock In / Adjustment"
            >
              <Boxes size={13} />
              <span>Stock In</span>
            </button>
            <button
              className="btn-action-icon"
              onClick={() => openEdit(p)}
              title="Edit Product"
            >
              <Edit2 size={13} />
            </button>
            <button
              className={`btn-action-icon ${p.is_active ? 'danger' : 'success'}`}
              onClick={() => dispatch(toggleProductActive(p))}
              title={p.is_active ? 'Deactivate Product' : 'Activate Product'}
            >
              <Power size={13} />
            </button>
          </div>
        ),
      },
    ],
    [suppliers, openStockIn, openEdit, dispatch]
  )

  return (
    <div className="products-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Inventory"
        activePage="Products Catalog"
        itemCount={filteredProducts.length}
        primaryAction={{
          label: 'New Product',
          icon: Plus,
          onClick: openAddModal,
          id: 'btn-add-product',
        }}
        onRefresh={() => dispatch(fetchProducts())}
        loading={loading}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="Search by SKU, product name, or category..."
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        exportData={filteredProducts}
        exportFilename="products_catalog"
        filters={
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {/* Category Filter */}
            <select
              className="form-control"
              style={{ width: '150px', padding: '0.45rem 0.65rem' }}
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              <option value="ALL">All Categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            {/* Stock Level Filter */}
            <select
              className="form-control"
              style={{ width: '145px', padding: '0.45rem 0.65rem' }}
              value={stockFilter}
              onChange={(e) => setStockFilter(e.target.value)}
            >
              <option value="ALL">All Stock Levels</option>
              <option value="HEALTHY">In Stock (Healthy)</option>
              <option value="LOW">Low Stock Alert</option>
              <option value="OUT">Out of Stock (0)</option>
            </select>
          </div>
        }
      />

      {/* Content Rendering: Reusable Table with Pagination OR Kanban */}
      {viewMode === 'table' ? (
        <DataTable
          columns={columns}
          data={filteredProducts}
          keyField="id"
          defaultPageSize={10}
          loading={loading}
          emptyTitle="No products match your criteria"
          emptyMessage="Try adjusting your search query or add a new product."
          emptyIcon={Package}
        />
      ) : (
        /* Kanban Grid View */
        <div className="kanban-grid">
          {filteredProducts.map((p) => {
            const supplier = suppliers.find((s) => s.id === p.supplier_id)
            const isLow = p.current_stock <= p.reorder_level
            const isOut = p.current_stock === 0

            return (
              <div key={p.id} className="kanban-card">
                <div className="kanban-header">
                  <div>
                    <div className="kanban-sku">{p.sku}</div>
                    <div className="kanban-title">{p.name}</div>
                  </div>
                  {isOut ? (
                    <Badge status="OUT OF STOCK" label="Out" />
                  ) : isLow ? (
                    <Badge status="LOW STOCK" label="Low" />
                  ) : (
                    <Badge status="HEALTHY" label="In Stock" />
                  )}
                </div>

                <div className="kanban-body">
                  <div className="kanban-row">
                    <span>Category:</span>
                    <strong>{p.category || 'General'}</strong>
                  </div>
                  <div className="kanban-row">
                    <span>Available Stock:</span>
                    <strong style={{ color: isOut ? '#dc2626' : isLow ? '#d97706' : '#059669', fontSize: '1rem' }}>
                      {p.current_stock} {p.unit}
                    </strong>
                  </div>
                  <div className="kanban-row">
                    <span>Reorder Threshold:</span>
                    <span>{p.reorder_level} {p.unit}</span>
                  </div>
                  <div className="kanban-row">
                    <span>Cost / Selling:</span>
                    <strong>
                      ₹{Number(p.cost_price).toFixed(2)} / ₹{Number(p.selling_price).toFixed(2)}
                    </strong>
                  </div>
                  <div className="kanban-row">
                    <span>Supplier:</span>
                    <span style={{ fontSize: '0.8rem' }}>{supplier ? supplier.name : '—'}</span>
                  </div>
                </div>

                <div className="kanban-footer">
                  <button className="btn btn-secondary btn-sm" onClick={() => openStockIn(p)}>
                    <Boxes size={13} />
                    <span>Stock In</span>
                  </button>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button className="btn btn-subtle btn-sm" onClick={() => openEdit(p)} title="Edit">
                      <Edit2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Modal: Add Product */}
      <Modal
        isOpen={isAddOpen}
        onClose={() => setIsAddOpen(false)}
        title="Create New Product"
        subtitle="Backend strictly validates SKU uniqueness and initial stock audit logging."
        size="lg"
      >
        <form onSubmit={handleAddSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>
                  <strong>Backend Validation Rule:</strong> {formError}
                </div>
              </div>
            )}

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">
                  SKU (Unique Code) <span className="required">*</span>
                </label>
                <input
                  type="text"
                  required
                  className="form-control"
                  placeholder="e.g. SKU-0006"
                  value={formData.sku}
                  onChange={(e) => setFormData({ ...formData, sku: e.target.value })}
                />
                <span className="form-hint">Backend validates uniqueness across database.</span>
              </div>

              <div className="form-group">
                <label className="form-label">
                  Product Name <span className="required">*</span>
                </label>
                <input
                  type="text"
                  required
                  className="form-control"
                  placeholder="e.g. Industrial Hydraulic Valve"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Category</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="e.g. Machinery, Electronics"
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Unit of Measure</label>
                <select
                  className="form-control"
                  value={formData.unit}
                  onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                >
                  <option value="piece">piece</option>
                  <option value="kg">kg</option>
                  <option value="box">box</option>
                  <option value="pack">pack</option>
                  <option value="meter">meter</option>
                  <option value="liter">liter</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">Cost Price (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="form-control"
                  value={formData.cost_price}
                  onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Selling Price (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="form-control"
                  value={formData.selling_price}
                  onChange={(e) => setFormData({ ...formData, selling_price: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Initial Stock Units</label>
                <input
                  type="number"
                  min="0"
                  className="form-control"
                  value={formData.current_stock}
                  onChange={(e) => setFormData({ ...formData, current_stock: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Reorder Level (Alert Threshold)</label>
                <input
                  type="number"
                  min="0"
                  className="form-control"
                  value={formData.reorder_level}
                  onChange={(e) => setFormData({ ...formData, reorder_level: e.target.value })}
                />
              </div>

              <div className="form-group col-span-2">
                <label className="form-label">Vendor / Supplier</label>
                <SearchableSelect
                  options={supplierOptions}
                  value={formData.supplier_id}
                  onChange={(val) => setFormData({ ...formData, supplier_id: val })}
                  placeholder="Search and select vendor / supplier..."
                  id="select-product-supplier"
                />
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsAddOpen(false)}
            >
              Discard
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              id="btn-save-new-product"
            >
              {submitting ? 'Creating in Backend...' : 'Save Product'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Edit Product */}
      <Modal
        isOpen={isEditOpen}
        onClose={() => setIsEditOpen(false)}
        title={`Edit Product: ${selectedProduct?.name}`}
        subtitle={`SKU: ${selectedProduct?.sku}`}
        size="lg"
      >
        <form onSubmit={handleEditSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>{formError}</div>
              </div>
            )}

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">SKU</label>
                <input
                  type="text"
                  required
                  className="form-control"
                  value={formData.sku}
                  onChange={(e) => setFormData({ ...formData, sku: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Product Name</label>
                <input
                  type="text"
                  required
                  className="form-control"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Category</label>
                <input
                  type="text"
                  className="form-control"
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Unit</label>
                <input
                  type="text"
                  className="form-control"
                  value={formData.unit}
                  onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Cost Price (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="form-control"
                  value={formData.cost_price}
                  onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Selling Price (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="form-control"
                  value={formData.selling_price}
                  onChange={(e) => setFormData({ ...formData, selling_price: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Reorder Level</label>
                <input
                  type="number"
                  min="0"
                  className="form-control"
                  value={formData.reorder_level}
                  onChange={(e) => setFormData({ ...formData, reorder_level: e.target.value })}
                />
              </div>

              <div className="form-group col-span-2">
                <label className="form-label">Supplier</label>
                <SearchableSelect
                  options={supplierOptions}
                  value={formData.supplier_id}
                  onChange={(val) => setFormData({ ...formData, supplier_id: val })}
                  placeholder="Search and select vendor / supplier..."
                  id="select-edit-product-supplier"
                />
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsEditOpen(false)}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Updating...' : 'Update Product'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Quick Stock In */}
      <Modal
        isOpen={isStockInOpen}
        onClose={() => setIsStockInOpen(false)}
        title="Stock In / Adjustment"
        subtitle={`Add units for ${selectedProduct?.name} (${selectedProduct?.sku})`}
      >
        <form onSubmit={handleStockInSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>{formError}</div>
              </div>
            )}

            <div style={{ backgroundColor: 'var(--erp-surface-subtle)', border: '1px solid var(--erp-border)', padding: '0.85rem', borderRadius: '6px', marginBottom: '0.5rem' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>Current Warehouse Stock:</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--erp-brand)' }}>
                {selectedProduct?.current_stock} {selectedProduct?.unit}
              </div>
            </div>

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
              <label className="form-label">Transaction Reason</label>
              <select
                className="form-control"
                value={stockInData.reason}
                onChange={(e) => setStockInData({ ...stockInData, reason: e.target.value })}
              >
                <option value="purchase">Purchase (Direct Inbound)</option>
                <option value="return">Customer Return</option>
                <option value="adjustment">Stock Count Audit Adjustment</option>
                <option value="production">Production / Internal Transfer</option>
              </select>
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
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Applying...' : 'Confirm Stock Addition'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
