import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Plus, Edit2, Power, Eye, RefreshCw } from 'lucide-react'
import {
  selectAllProducts,
  selectProductsLoading,
  selectProductsError,
  selectProductCategories,
  fetchProducts,
  createProduct,
  updateProduct,
  toggleProductActive,
} from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import CsvExportButton from '../components/common/CsvExportButton'
import ProductCsvImportButton from '../components/products/ProductCsvImportButton'
import Badge from '../components/Badge'
import Modal from '../components/Modal'
import ProductFormModal from '../components/products/ProductFormModal'
import { ErrorState, ConfirmDialog } from '../components/common/StateBlocks'
import { useTranslation } from '../hooks/useTranslation'

export default function ProductsPage() {
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const products = useSelector(selectAllProducts)
  const loading = useSelector(selectProductsLoading)
  const error = useSelector(selectProductsError)
  const categories = useSelector(selectProductCategories)
  const suppliers = useSelector(selectAllSuppliers)

  const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || '')
  const [categoryFilter, setCategoryFilter] = useState('ALL')
  const [stockFilter, setStockFilter] = useState('ALL')

  const [formMode, setFormMode] = useState(null) // 'add' | 'edit' | null
  const [selectedProduct, setSelectedProduct] = useState(null)
  const [detailProduct, setDetailProduct] = useState(null)
  const [confirmToggle, setConfirmToggle] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  useEffect(() => {
    dispatch(fetchProducts())
    dispatch(fetchSuppliers())
  }, [dispatch])

  const filteredProducts = useMemo(() => {
    const q = searchQuery.toLowerCase().trim()
    return products.filter((p) => {
      const matchesSearch =
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.sku.toLowerCase().includes(q) ||
        (p.category && p.category.toLowerCase().includes(q))
      const matchesCat = categoryFilter === 'ALL' || p.category === categoryFilter
      let matchesStock = true
      if (stockFilter === 'OUT') matchesStock = p.current_stock === 0
      else if (stockFilter === 'LOW') matchesStock = p.current_stock > 0 && p.current_stock <= p.reorder_level
      else if (stockFilter === 'HEALTHY') matchesStock = p.current_stock > p.reorder_level
      return matchesSearch && matchesCat && matchesStock
    })
  }, [products, searchQuery, categoryFilter, stockFilter])

  const handleSaveProduct = async (payload) => {
    setSubmitting(true)
    setFormError('')
    const action =
      formMode === 'edit' && selectedProduct
        ? updateProduct({ id: selectedProduct.id, payload })
        : createProduct(payload)
    const res = await dispatch(action)
    if (res.meta.requestStatus === 'rejected') {
      setFormError(res.payload || 'Operation failed.')
    } else {
      setFormMode(null)
      setSelectedProduct(null)
    }
    setSubmitting(false)
  }

  const handleConfirmToggle = async () => {
    if (!confirmToggle) return
    setSubmitting(true)
    await dispatch(toggleProductActive(confirmToggle))
    setConfirmToggle(null)
    setSubmitting(false)
  }

  const columns = useMemo(
    () => [
      {
        key: 'sku',
        label: 'SKU',
        sortable: true,
        render: (p) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{p.sku}</span>,
      },
      {
        key: 'name',
        label: 'Product Name',
        sortable: true,
        render: (p) => (
          <div>
            <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
              <span>{p.name}</span>
              {p.is_synthetic && (
                <span
                  className="badge badge-draft"
                  title="Historical simulation / synthetic demo SKU"
                  style={{ fontSize: '0.68rem', padding: '0.1rem 0.4rem' }}
                >
                  {t('intelligence.syntheticDemoTag', 'Synthetic Demo')}
                </span>
              )}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
              {p.category || 'General'} • {p.unit}
            </div>
          </div>
        ),
      },
      {
        key: 'cost_price',
        label: 'Cost Price',
        numeric: true,
        sortable: true,
        render: (p) => `₹${Number(p.cost_price || 0).toFixed(2)}`,
      },
      {
        key: 'selling_price',
        label: 'Selling Price',
        numeric: true,
        sortable: true,
        render: (p) => `₹${Number(p.selling_price || 0).toFixed(2)}`,
      },
      {
        key: 'current_stock',
        label: 'On Hand',
        numeric: true,
        sortable: true,
        render: (p) => {
          const isLow = p.current_stock <= p.reorder_level
          return (
            <span style={{ fontWeight: 700, color: p.current_stock === 0 ? '#dc2626' : isLow ? '#d97706' : '#059669' }}>
              {p.current_stock} {p.unit}
            </span>
          )
        },
      },
      {
        key: 'incoming_stock',
        label: 'Incoming',
        numeric: true,
        sortable: true,
        render: (p) => `${p.incoming_stock ?? 0} ${p.unit}`,
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        render: (p) =>
          p.current_stock === 0 ? (
            <Badge status="OUT OF STOCK" />
          ) : p.current_stock <= p.reorder_level ? (
            <Badge status="LOW STOCK" />
          ) : (
            <Badge status="HEALTHY" label="In Stock" />
          ),
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (p) => (
          <div className="actions-group">
            <button type="button" className="btn-action-icon" title="Details" onClick={() => setDetailProduct(p)}>
              <Eye size={14} />
            </button>
            <button
              type="button"
              className="btn-action-icon"
              title="Edit"
              onClick={() => {
                setSelectedProduct(p)
                setFormError('')
                setFormMode('edit')
              }}
            >
              <Edit2 size={14} />
            </button>
            <button
              type="button"
              className="btn-action-icon danger"
              title={p.is_active ? 'Deactivate' : 'Activate'}
              onClick={() => setConfirmToggle(p)}
            >
              <Power size={14} />
            </button>
          </div>
        ),
      },
    ],
    [t]
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Products Catalog"
        subtitle={`${filteredProducts.length} active products`}
        actions={
          <>
            <ProductCsvImportButton onImported={() => dispatch(fetchProducts())} />
            <CsvExportButton data={filteredProducts} filename="products" />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => dispatch(fetchProducts())} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setSelectedProduct(null)
                setFormError('')
                setFormMode('add')
              }}
            >
              <Plus size={14} />
              <span>Add Product</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={() => dispatch(fetchProducts())} />}

      <div className="section-card" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          className="form-control"
          style={{ flex: '1 1 240px', maxWidth: '360px' }}
          placeholder={t('placeholders.searchProducts', 'Search by product name, SKU, or category...')}
          aria-label="Search products"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select
          className="form-control"
          style={{ width: '180px' }}
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
        <select
          className="form-control"
          style={{ width: '170px' }}
          value={stockFilter}
          onChange={(e) => setStockFilter(e.target.value)}
        >
          <option value="ALL">All Stock Levels</option>
          <option value="HEALTHY">Healthy</option>
          <option value="LOW">Low Stock</option>
          <option value="OUT">Out of Stock</option>
        </select>
      </div>

      <DataTable
        columns={columns}
        data={filteredProducts}
        keyField="id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No products found"
        emptyMessage="Add your first product or adjust your search filters."
      />

      <ProductFormModal
        isOpen={Boolean(formMode)}
        onClose={() => setFormMode(null)}
        mode={formMode || 'add'}
        initialProduct={selectedProduct}
        suppliers={suppliers}
        defaultSku={`SKU-${String(products.length + 1).padStart(4, '0')}`}
        defaultCategory={categories[0] || 'General'}
        onSubmit={handleSaveProduct}
        submitting={submitting}
        error={formError}
      />

      <Modal
        isOpen={Boolean(detailProduct)}
        onClose={() => setDetailProduct(null)}
        title={detailProduct?.name || 'Product Details'}
        subtitle={detailProduct ? `SKU: ${detailProduct.sku}` : ''}
      >
        {detailProduct && (
          <div className="modal-body">
            <div className="form-grid">
              <div><strong>Category:</strong> {detailProduct.category || 'General'}</div>
              <div><strong>Unit:</strong> {detailProduct.unit}</div>
              <div><strong>Cost Price:</strong> ₹{Number(detailProduct.cost_price).toFixed(2)}</div>
              <div><strong>Selling Price:</strong> ₹{Number(detailProduct.selling_price).toFixed(2)}</div>
              <div><strong>On-Hand Stock:</strong> {detailProduct.current_stock}</div>
              <div><strong>Incoming Stock:</strong> {detailProduct.incoming_stock ?? 0}</div>
              <div><strong>Inventory Position:</strong> {detailProduct.inventory_position ?? detailProduct.current_stock}</div>
              <div><strong>Reorder Level:</strong> {detailProduct.reorder_level}</div>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(confirmToggle)}
        onClose={() => setConfirmToggle(null)}
        onConfirm={handleConfirmToggle}
        title={confirmToggle?.is_active ? 'Deactivate Product' : 'Activate Product'}
        message={`Are you sure you want to ${confirmToggle?.is_active ? 'deactivate' : 'activate'} "${confirmToggle?.name}"?`}
        confirmLabel={confirmToggle?.is_active ? 'Deactivate' : 'Activate'}
        danger={Boolean(confirmToggle?.is_active)}
        loading={submitting}
      />
    </div>
  )
}
