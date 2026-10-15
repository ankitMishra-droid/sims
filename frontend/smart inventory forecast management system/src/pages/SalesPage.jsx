import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import {
  ShoppingCart,
  Plus,
  IndianRupee,
  Receipt,
  TrendingUp,
  AlertTriangle,
  Clock,
} from 'lucide-react'
import {
  selectAllSales,
  selectSalesLoading,
  selectSalesSummary,
  fetchSales,
  recordSale,
} from '../store/salesSlice'
import { selectAllProducts, fetchProducts } from '../store/productsSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import KpiCard from '../components/common/KpiCard'
import Modal from '../components/Modal'
import Badge from '../components/Badge'

export default function SalesPage() {
  const dispatch = useDispatch()
  const sales = useSelector(selectAllSales)
  const loading = useSelector(selectSalesLoading)
  const salesSummary = useSelector(selectSalesSummary)
  const products = useSelector(selectAllProducts)

  // Search query
  const [searchQuery, setSearchQuery] = useState('')

  // Modal State
  const [isRecordOpen, setIsRecordOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  const [formData, setFormData] = useState({
    product_id: '',
    quantity_sold: 1,
    selling_price: '',
  })

  useEffect(() => {
    dispatch(fetchSales())
    dispatch(fetchProducts())
  }, [dispatch])

  // Selected product object
  const selectedProduct = useMemo(() => {
    if (!formData.product_id) return null
    return products.find((p) => p.id === parseInt(formData.product_id, 10)) || null
  }, [formData.product_id, products])

  const productOptions = useMemo(
    () =>
      products.map((p) => ({
        value: p.id,
        label: p.name,
        subLabel: `Available Stock: ${p.current_stock} ${p.unit} • ${p.category || 'General'}`,
        badge: p.sku,
        meta: `₹${Number(p.selling_price || 0).toFixed(2)}`,
      })),
    [products]
  )

  // Live active price
  const activePrice = useMemo(() => {
    if (formData.selling_price !== '') {
      return parseFloat(formData.selling_price) || 0
    }
    return selectedProduct?.selling_price || 0
  }, [formData.selling_price, selectedProduct])

  // Computed Revenue preview
  const calculatedRevenue = useMemo(() => {
    const qty = parseInt(formData.quantity_sold, 10) || 0
    return qty * activePrice
  }, [formData.quantity_sold, activePrice])

  // Remaining stock preview
  const remainingStockPreview = useMemo(() => {
    if (!selectedProduct) return null
    const qty = parseInt(formData.quantity_sold, 10) || 0
    return selectedProduct.current_stock - qty
  }, [selectedProduct, formData.quantity_sold])

  // Total Realized Profit & Margin calculation
  const netProfitSummary = useMemo(() => {
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

  // Open Record Sale Modal
  const openRecordModal = useCallback(
    (presetProductId = null) => {
      const target = presetProductId
        ? products.find((p) => p.id === presetProductId)
        : products[0]

      setFormData({
        product_id: target ? String(target.id) : '',
        quantity_sold: 1,
        selling_price: target ? String(target.selling_price) : '',
      })
      setFormError('')
      setIsRecordOpen(true)
    },
    [products]
  )

  // Submit Sale
  const handleRecordSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')

    const pid = parseInt(formData.product_id, 10)
    const qty = parseInt(formData.quantity_sold, 10)

    if (!pid) {
      setFormError('Please select a product.')
      setSubmitting(false)
      return
    }

    const payload = {
      product_id: pid,
      quantity_sold: qty,
      selling_price: formData.selling_price !== '' ? parseFloat(formData.selling_price) : null,
    }

    const res = await dispatch(recordSale(payload))
    if (recordSale.rejected.match(res)) {
      setFormError(res.payload || 'Sale submission failed.')
    } else {
      setIsRecordOpen(false)
    }
    setSubmitting(false)
  }

  // Table Columns
  const columns = useMemo(
    () => [
      {
        key: 'id',
        label: 'Sale ID',
        sortable: true,
        render: (s) => (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: 'var(--erp-brand)',
            }}
          >
            #SO-{String(s.id).padStart(4, '0')}
          </span>
        ),
      },
      {
        key: 'sales_date',
        label: 'Date & Time',
        sortable: true,
        render: (s) => {
          const dateStr = s.sales_date
            ? new Date(s.sales_date).toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })
            : '—'
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-text-muted)', fontSize: '0.8rem' }}>
              <Clock size={13} color="var(--erp-text-subtle)" />
              <span>{dateStr}</span>
            </div>
          )
        },
      },
      {
        key: 'product_name',
        label: 'Product',
        sortable: true,
        render: (s) => {
          const prod = products.find((p) => p.id === s.product_id)
          return (
            <div>
              <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
                {prod ? prod.name : `Product #${s.product_id}`}
              </div>
              {prod?.category && (
                <span style={{ fontSize: '0.725rem', color: 'var(--erp-text-muted)' }}>{prod.category}</span>
              )}
            </div>
          )
        },
      },
      {
        key: 'sku',
        label: 'SKU',
        sortable: false,
        render: (s) => {
          const prod = products.find((p) => p.id === s.product_id)
          return (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                backgroundColor: 'var(--erp-surface-subtle)',
                color: 'var(--erp-text-main)',
                border: '1px solid var(--erp-border)',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              {prod ? prod.sku : `ID-${s.product_id}`}
            </span>
          )
        },
      },
      {
        key: 'quantity_sold',
        label: 'Quantity Sold',
        numeric: true,
        sortable: true,
        render: (s) => {
          const prod = products.find((p) => p.id === s.product_id)
          return (
            <div style={{ fontWeight: 700, color: 'var(--erp-text-main)' }}>
              {s.quantity_sold}{' '}
              <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>{prod?.unit || 'units'}</span>
            </div>
          )
        },
      },
      {
        key: 'selling_price',
        label: 'Unit Price',
        numeric: true,
        sortable: true,
        render: (s) => `₹${Number(s.selling_price).toFixed(2)}`,
      },
      {
        key: 'revenue',
        label: 'Total Revenue',
        numeric: true,
        sortable: true,
        render: (s) => (
          <span style={{ fontWeight: 800, color: '#059669', fontSize: '0.95rem' }}>
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
    <div className="sales-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Sales & POS"
        activePage="Order Transactions"
        itemCount={sales.length}
        primaryAction={{
          label: 'Record Sale',
          icon: Plus,
          onClick: () => openRecordModal(),
          id: 'btn-record-sale',
        }}
        onRefresh={() => dispatch(fetchSales())}
        loading={loading}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="Search by Sale ID, Product name, or Date..."
        exportData={sales}
        exportFilename="sales_transactions"
      />

      {/* KPI Cards */}
      <div className="kpi-grid">
        <KpiCard
          label="Total Realized Revenue"
          value={`₹${netProfitSummary.totalRevenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle="All confirmed sales transactions"
          icon={IndianRupee}
          variant="emerald"
        />
        <KpiCard
          label="Total Net Profit"
          value={`₹${netProfitSummary.netProfit.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle={`${netProfitSummary.margin}% net profit margin`}
          icon={TrendingUp}
          variant="purple"
        />
        <KpiCard
          label="Total Orders Executed"
          value={sales.length}
          subtitle="Processed through inventory"
          icon={Receipt}
          variant="blue"
        />
        <KpiCard
          label="Total Units Dispatched"
          value={salesSummary.totalUnits.toLocaleString()}
          subtitle="Deducted from warehouse stock"
          icon={TrendingUp}
          variant="amber"
        />
      </div>

      {/* Reusable Data Table with Pagination & Sorting */}
      <DataTable
        columns={columns}
        data={sales}
        keyField="id"
        defaultPageSize={10}
        searchQuery={searchQuery}
        searchFields={['id', 'sales_date']}
        loading={loading}
        emptyTitle="No sales recorded yet"
        emptyMessage="Record your first customer sale to deduct inventory stock and generate revenue."
        emptyIcon={ShoppingCart}
      />

      {/* Modal: Record Sale */}
      <Modal
        isOpen={isRecordOpen}
        onClose={() => setIsRecordOpen(false)}
        title="Record New Customer Sale"
        subtitle="Backend strictly validates available inventory stock before confirming the sale."
        size="md"
      >
        <form onSubmit={handleRecordSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>
                  <strong>Backend Validation Rule:</strong> {formError}
                </div>
              </div>
            )}

            {/* Product Picker */}
            <div className="form-group">
              <label className="form-label">
                Select Product <span className="required">*</span>
              </label>
              <SearchableSelect
                options={productOptions}
                value={formData.product_id}
                placeholder="-- Search & Choose Product --"
                searchPlaceholder="Type product name, SKU, or category..."
                required
                id="select-sale-product"
                onChange={(pid) => {
                  const found = products.find((p) => p.id === parseInt(pid, 10))
                  setFormData({
                    ...formData,
                    product_id: pid,
                    selling_price: found ? String(found.selling_price) : '',
                  })
                  setFormError('')
                }}
              />
            </div>

            {/* Live Stock & Remaining Calculator */}
            {selectedProduct && (
              <div
                style={{
                  backgroundColor: 'var(--erp-surface-subtle)',
                  border: '1px solid var(--erp-border)',
                  borderRadius: '8px',
                  padding: '1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.5rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>Current Warehouse Stock:</span>
                  <strong style={{ fontSize: '1rem', color: selectedProduct.current_stock > 0 ? '#059669' : '#dc2626' }}>
                    {selectedProduct.current_stock} {selectedProduct.unit} available
                  </strong>
                </div>

                {remainingStockPreview !== null && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem' }}>
                    <span style={{ color: 'var(--erp-text-muted)' }}>Stock Remaining After Sale:</span>
                    <strong style={{ color: remainingStockPreview >= 0 ? '#2563eb' : '#dc2626' }}>
                      {remainingStockPreview} {selectedProduct.unit}{' '}
                      {remainingStockPreview < 0 ? '(INSUFFICIENT STOCK)' : ''}
                    </strong>
                  </div>
                )}
              </div>
            )}

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">
                  Quantity Sold <span className="required">*</span>
                </label>
                <input
                  type="number"
                  min="1"
                  required
                  className="form-control"
                  value={formData.quantity_sold}
                  onChange={(e) => setFormData({ ...formData, quantity_sold: e.target.value })}
                />
                <span className="form-hint">Backend validates quantity &le; current stock.</span>
              </div>

              <div className="form-group">
                <label className="form-label">Selling Price Per Unit (₹)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  className="form-control"
                  placeholder={selectedProduct ? String(selectedProduct.selling_price) : '0.00'}
                  value={formData.selling_price}
                  onChange={(e) => setFormData({ ...formData, selling_price: e.target.value })}
                />
                <span className="form-hint">Leave blank for default catalog price.</span>
              </div>
            </div>

            {/* Computed Revenue Box */}
            <div
              style={{
                backgroundColor: 'var(--erp-brand-subtle)',
                border: '1px solid var(--erp-border)',
                borderRadius: '8px',
                padding: '1rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--erp-brand)', fontWeight: 700 }}>
                  Calculated Sale Revenue
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>
                  {formData.quantity_sold || 0} &times; ₹{activePrice.toFixed(2)}
                </div>
              </div>
              <div style={{ fontSize: '1.45rem', fontWeight: 800, color: 'var(--erp-brand)', fontFamily: 'var(--font-heading)' }}>
                ₹{calculatedRevenue.toFixed(2)}
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsRecordOpen(false)}
            >
              Discard
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              id="btn-confirm-sale"
            >
              {submitting ? 'Recording Sale...' : 'Confirm Sale'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
