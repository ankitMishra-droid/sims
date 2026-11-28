import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Plus, Trash2, Eye, Send, XCircle, Inbox, RefreshCw, AlertTriangle, Share2 } from 'lucide-react'
import { addToast } from '../store/uiSlice'
import {
  selectAllPurchaseOrders,
  selectPurchaseOrdersLoading,
  selectPurchaseOrdersError,
  fetchPurchaseOrders,
  createPurchaseOrder,
  sendPurchaseOrder,
  cancelPurchaseOrder,
} from '../store/purchaseOrdersSlice'
import { selectAllProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import { api } from '../api'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import FormField from '../components/common/FormField'
import CsvExportButton from '../components/common/CsvExportButton'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import { ErrorState, ConfirmDialog } from '../components/common/StateBlocks'
import { useTranslation } from '../hooks/useTranslation'
import { createStableRowKey, validateAndBuildPurchaseOrderPayload } from '../utils/formHelpers'

export default function PurchaseOrdersPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()

  const orders = useSelector(selectAllPurchaseOrders)
  const loading = useSelector(selectPurchaseOrdersLoading)
  const error = useSelector(selectPurchaseOrdersError)
  const products = useSelector(selectAllProducts)
  const suppliers = useSelector(selectAllSuppliers)

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [detailOrder, setDetailOrder] = useState(null)
  const [detailReceipts, setDetailReceipts] = useState([])
  const [cancelTarget, setCancelTarget] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [poForm, setPoForm] = useState({
    supplier_id: '',
    expected_delivery_date: '',
    notes: '',
    items: [],
  })

  useEffect(() => {
    dispatch(fetchPurchaseOrders())
    dispatch(fetchProducts())
    dispatch(fetchSuppliers())
  }, [dispatch])

  const openCreateModal = useCallback(
    (presetSupplierId = null) => {
      const suppId = presetSupplierId || (suppliers[0] ? String(suppliers[0].id) : '')
      const supp = suppliers.find((s) => String(s.id) === String(suppId))
      const d = new Date()
      d.setDate(d.getDate() + (supp?.lead_time_days || 7))
      const defaultProd = products[0]
      setPoForm({
        supplier_id: suppId,
        expected_delivery_date: d.toISOString().split('T')[0],
        notes: '',
        items: defaultProd
          ? [
              {
                _key: createStableRowKey('po-item'),
                product_id: defaultProd.id,
                ordered_quantity: '25',
                unit_cost: String(defaultProd.cost_price ?? 0),
              },
            ]
          : [],
      })
      setFormError('')
      setIsCreateOpen(true)
    },
    [suppliers, products]
  )

  const handledQuerySupplierRef = useRef(null)

  useEffect(() => {
    const qSupp = searchParams.get('supplier_id')
    if (!qSupp) {
      handledQuerySupplierRef.current = null
      return undefined
    }
    if (suppliers.length > 0 && handledQuerySupplierRef.current !== qSupp) {
      handledQuerySupplierRef.current = qSupp
      const timer = setTimeout(() => openCreateModal(qSupp), 0)
      return () => clearTimeout(timer)
    }
    return undefined
  }, [searchParams, suppliers.length, openCreateModal])

  const openDetailModal = async (order) => {
    setDetailOrder(order)
    setDetailReceipts([])
    try {
      const recs = await api.getGoodsReceipts(order.id)
      setDetailReceipts(recs)
    } catch {
      setDetailReceipts([])
    }
  }

  const filteredOrders = useMemo(() => {
    const q = searchQuery.toLowerCase().trim()
    return orders.filter((o) => {
      const supp = suppliers.find((s) => s.id === o.supplier_id)
      const matchSearch =
        !q ||
        (o.order_number || '').toLowerCase().includes(q) ||
        String(o.id).includes(q) ||
        (supp && supp.name.toLowerCase().includes(q)) ||
        (o.notes && o.notes.toLowerCase().includes(q))
      const matchStatus = statusFilter === 'ALL' || o.status === statusFilter
      return matchSearch && matchStatus
    })
  }, [orders, suppliers, searchQuery, statusFilter])

  const supplierOptions = useMemo(
    () =>
      suppliers.map((s) => ({
        value: s.id,
        label: s.name,
        subLabel: `Lead time: ${s.lead_time_days || 7}d`,
        badge: `#${s.id}`,
      })),
    [suppliers]
  )

  const productOptions = useMemo(
    () =>
      products.map((p) => ({
        value: p.id,
        label: p.name,
        subLabel: `Stock: ${p.current_stock} ${p.unit}`,
        badge: p.sku,
        meta: `₹${Number(p.cost_price || 0).toFixed(2)}`,
      })),
    [products]
  )

  const addLineItem = () => {
    const p = products[0]
    if (!p) return
    setPoForm((prev) => ({
      ...prev,
      items: [
        ...prev.items,
        {
          _key: createStableRowKey('po-item'),
          product_id: p.id,
          ordered_quantity: '10',
          unit_cost: String(p.cost_price ?? 0),
        },
      ],
    }))
  }

  const updateLineItem = (rowKey, field, val) => {
    setPoForm((prev) => ({
      ...prev,
      items: prev.items.map((item) => {
        if (item._key !== rowKey) return item
        const row = { ...item }
        if (field === 'product_id') {
          if (val === '' || val === null || val === undefined) {
            row.product_id = ''
          } else {
            const pid = parseInt(val, 10)
            row.product_id = Number.isNaN(pid) ? '' : pid
            const prod = products.find((p) => p.id === pid)
            if (prod) row.unit_cost = String(prod.cost_price ?? 0)
          }
        } else if (field === 'ordered_quantity') {
          row.ordered_quantity = val
        } else if (field === 'unit_cost') {
          row.unit_cost = val
        }
        return row
      }),
    }))
  }

  const previewTotal = poForm.items.reduce((sum, i) => {
    const qty = Number(i.ordered_quantity)
    const cost = Number(i.unit_cost)
    return sum + (Number.isFinite(qty) && qty > 0 ? qty : 0) * (Number.isFinite(cost) && cost >= 0 ? cost : 0)
  }, 0)

  const handleCreateSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setFormError('')
    const { error: validationError, payload } = validateAndBuildPurchaseOrderPayload(poForm)
    if (validationError || !payload) {
      setFormError(validationError || 'Please fix form validation errors.')
      return
    }
    setSubmitting(true)
    const res = await dispatch(createPurchaseOrder(payload))
    if (createPurchaseOrder.rejected.match(res)) {
      setFormError(res.payload || 'Failed to create purchase order.')
    } else {
      setIsCreateOpen(false)
    }
    setSubmitting(false)
  }

  const handleConfirmCancel = async () => {
    if (!cancelTarget) return
    setSubmitting(true)
    await dispatch(cancelPurchaseOrder(cancelTarget.id))
    setCancelTarget(null)
    setSubmitting(false)
  }

  const columns = useMemo(
    () => [
      {
        key: 'id',
        label: 'PO Number',
        sortable: true,
        render: (o) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--erp-brand)' }}>
            {o.order_number || `PO-${String(o.id).padStart(4, '0')}`}
          </span>
        ),
      },
      {
        key: 'order_date',
        label: 'Order Date',
        sortable: true,
        render: (o) => (o.order_date ? new Date(o.order_date).toLocaleDateString() : '—'),
      },
      {
        key: 'supplier_id',
        label: 'Supplier',
        render: (o) => suppliers.find((s) => s.id === o.supplier_id)?.name || `Supplier #${o.supplier_id}`,
      },
      {
        key: 'items',
        label: 'Received / Ordered',
        render: (o) => {
          const ord = (o.items || []).reduce((a, i) => a + i.ordered_quantity, 0)
          const rec = (o.items || []).reduce((a, i) => a + i.received_quantity, 0)
          return `${rec} / ${ord}`
        },
      },
      {
        key: 'total_amount',
        label: 'Total',
        numeric: true,
        sortable: true,
        render: (o) => <strong>₹{Number(o.total_amount || 0).toFixed(2)}</strong>,
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        sortable: true,
        render: (o) => <Badge status={o.status} />,
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (o) => (
          <div className="actions-group">
            {o.status === 'DRAFT' && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => dispatch(sendPurchaseOrder(o.id))}
                title="Send PO to Supplier"
              >
                <Send size={12} />
                <span>Send</span>
              </button>
            )}
            {['SENT', 'PARTIALLY_RECEIVED'].includes(o.status) && !o.shared_with_supplier && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                title="Explicitly share PO with linked supplier workspace"
                onClick={async () => {
                  try {
                    await api.sharePurchaseOrder(o.id)
                    dispatch(addToast({ type: 'success', message: `${o.order_number || 'PO'} shared with supplier portal.` }))
                    dispatch(fetchPurchaseOrders())
                  } catch (err) {
                    dispatch(addToast({ type: 'error', message: err.message || 'Could not share PO.' }))
                  }
                }}
              >
                <Share2 size={12} />
                <span>Share</span>
              </button>
            )}
            {o.shared_with_supplier && (
              <Badge status="ACTIVE" label={o.supplier_status || 'Shared'} />
            )}
            {['SENT', 'PARTIALLY_RECEIVED'].includes(o.status) && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => navigate(`/receive-order?order_id=${o.id}`)}
              >
                <Inbox size={12} />
                <span>Receive</span>
              </button>
            )}
            <button type="button" className="btn-action-icon" title="Details" onClick={() => openDetailModal(o)}>
              <Eye size={14} />
            </button>
            {['DRAFT', 'SENT'].includes(o.status) && (
              <button
                type="button"
                className="btn-action-icon danger"
                title="Cancel PO"
                onClick={() => setCancelTarget(o)}
              >
                <XCircle size={14} />
              </button>
            )}
          </div>
        ),
      },
    ],
    [suppliers, dispatch, navigate]
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Purchase Orders"
        subtitle="Manage procurement lifecycle: DRAFT -> SENT -> PARTIALLY_RECEIVED -> RECEIVED"
        actions={
          <>
            <CsvExportButton data={filteredOrders} filename="purchase_orders" />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => dispatch(fetchPurchaseOrders())} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => openCreateModal()}>
              <Plus size={14} />
              <span>New Purchase Order</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={() => dispatch(fetchPurchaseOrders())} />}

      <div className="section-card" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="form-control"
          style={{ flex: '1 1 240px', maxWidth: '340px' }}
          placeholder={t('placeholders.searchOrders', 'Search by PO number, supplier name, or notes...')}
          aria-label="Search purchase orders"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select className="form-control" style={{ width: '200px' }} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="ALL">All Statuses</option>
          <option value="DRAFT">DRAFT</option>
          <option value="SENT">SENT</option>
          <option value="PARTIALLY_RECEIVED">PARTIALLY_RECEIVED</option>
          <option value="RECEIVED">RECEIVED</option>
          <option value="CANCELLED">CANCELLED</option>
        </select>
      </div>

      <DataTable
        columns={columns}
        data={filteredOrders}
        keyField="id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No purchase orders"
        emptyMessage="Create a purchase order to replenish stock from a supplier."
      />

      <Modal isOpen={isCreateOpen} onClose={() => setIsCreateOpen(false)} title="Create Purchase Order" size="lg">
        <form onSubmit={handleCreateSubmit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} />
                <div>{formError}</div>
              </div>
            )}
            <div className="form-grid">
              <FormField label="Supplier" htmlFor="po-supplier-select" required>
                <SearchableSelect
                  id="po-supplier-select"
                  options={supplierOptions}
                  value={poForm.supplier_id}
                  onChange={(val) => setPoForm((prev) => ({ ...prev, supplier_id: val }))}
                  placeholder="Select supplier..."
                />
              </FormField>
              <FormField label="Expected Delivery" htmlFor="po-eta-date">
                <input
                  id="po-eta-date"
                  type="date"
                  className="form-control"
                  value={poForm.expected_delivery_date}
                  onChange={(e) => setPoForm((prev) => ({ ...prev, expected_delivery_date: e.target.value }))}
                />
              </FormField>
              <FormField
                label="Purchase Order Notes & Reference"
                htmlFor="po-notes-input"
                className="col-span-2"
                hint="Include internal PO reference or delivery instructions if needed."
              >
                <input
                  id="po-notes-input"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.poNotes', 'e.g. PO-2026-001 urgent festive restock')}
                  value={poForm.notes}
                  onChange={(e) => setPoForm((prev) => ({ ...prev, notes: e.target.value }))}
                />
              </FormField>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong>Order Items</strong>
              <button type="button" className="btn btn-secondary btn-sm" onClick={addLineItem}>
                <Plus size={13} /> Add Line
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {poForm.items.map((item) => (
                <div key={item._key} className="po-line-grid">
                  <SearchableSelect
                    options={productOptions}
                    value={item.product_id}
                    placeholder="Select product..."
                    onChange={(val) => updateLineItem(item._key, 'product_id', val)}
                  />
                  <input
                    type="number"
                    min="1"
                    step="1"
                    className="form-control"
                    placeholder={t('placeholders.poQuantity', 'e.g. 100')}
                    value={item.ordered_quantity}
                    onChange={(e) => updateLineItem(item._key, 'ordered_quantity', e.target.value)}
                    aria-label="Ordered quantity"
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="form-control"
                    placeholder={t('placeholders.poUnitCost', 'e.g. 42.50')}
                    value={item.unit_cost}
                    onChange={(e) => updateLineItem(item._key, 'unit_cost', e.target.value)}
                    aria-label="Unit cost"
                  />
                  <button
                    type="button"
                    className="btn-action-icon danger"
                    onClick={() =>
                      setPoForm((prev) => ({
                        ...prev,
                        items: prev.items.filter((row) => row._key !== item._key),
                      }))
                    }
                    title="Remove line"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>

            <div style={{ textAlign: 'right', fontWeight: 700 }}>
              Estimated Order Total: ₹{previewTotal.toFixed(2)}
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Creating...' : 'Create Draft PO'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(detailOrder)}
        onClose={() => setDetailOrder(null)}
        title={detailOrder ? `${detailOrder.order_number || `PO-${detailOrder.id}`} Details` : 'PO Details'}
        size="lg"
      >
        {detailOrder && (
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="form-grid">
              <div><strong>Status:</strong> <Badge status={detailOrder.status} /></div>
              <div><strong>Total Amount:</strong> ₹{Number(detailOrder.total_amount || 0).toFixed(2)}</div>
              <div><strong>Order Date:</strong> {new Date(detailOrder.order_date).toLocaleString()}</div>
              <div><strong>Notes:</strong> {detailOrder.notes || '—'}</div>
            </div>
            <div className="table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="numeric">Ordered</th>
                    <th className="numeric">Received</th>
                    <th className="numeric">Unit Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {(detailOrder.items || []).map((itm) => (
                    <tr key={itm.id}>
                      <td>{products.find((p) => p.id === itm.product_id)?.name || `Product #${itm.product_id}`}</td>
                      <td className="numeric">{itm.ordered_quantity}</td>
                      <td className="numeric">{itm.received_quantity}</td>
                      <td className="numeric">₹{Number(itm.unit_cost).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {detailReceipts.length > 0 && (
              <div>
                <strong style={{ fontSize: '0.85rem' }}>Goods Receipts ({detailReceipts.length})</strong>
                <ul style={{ marginTop: '0.4rem', paddingLeft: '1.25rem', fontSize: '0.82rem' }}>
                  {detailReceipts.map((gr) => (
                    <li key={gr.id}>
                      <strong>{gr.receipt_number}</strong> — {new Date(gr.received_at).toLocaleString()} ({gr.items.length} line(s))
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(cancelTarget)}
        onClose={() => setCancelTarget(null)}
        onConfirm={handleConfirmCancel}
        title="Cancel Purchase Order"
        message={`Cancel ${cancelTarget?.order_number || `PO #${cancelTarget?.id}`}?`}
        confirmLabel="Cancel PO"
        danger
        loading={submitting}
      />
    </div>
  )
}
