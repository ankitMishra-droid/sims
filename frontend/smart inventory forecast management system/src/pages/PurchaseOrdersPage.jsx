import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  ClipboardList,
  Plus,
  Trash2,
  Calendar,
  Eye,
  CheckCircle,
  XCircle,
  Clock,
  Inbox,
  AlertTriangle,
} from 'lucide-react'
import {
  selectAllPurchaseOrders,
  selectPurchaseOrdersLoading,
  fetchPurchaseOrders,
  createPurchaseOrder,
  cancelPurchaseOrder,
  receivePurchaseOrder,
} from '../store/purchaseOrdersSlice'
import { selectAllProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import Modal from '../components/Modal'
import Badge from '../components/Badge'

export default function PurchaseOrdersPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const dispatch = useDispatch()

  const orders = useSelector(selectAllPurchaseOrders)
  const loading = useSelector(selectPurchaseOrdersLoading)
  const products = useSelector(selectAllProducts)
  const suppliers = useSelector(selectAllSuppliers)

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')

  // Modals state
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  // Create PO Form State
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

  // Check if supplier_id was passed in URL query
  useEffect(() => {
    const qSupplierId = searchParams.get('supplier_id')
    if (qSupplierId && suppliers.length > 0) {
      openCreateModal(qSupplierId)
    }
  }, [searchParams, suppliers])

  // Filtered orders
  const filteredOrders = useMemo(() => {
    return orders.filter((o) => {
      const supp = suppliers.find((s) => s.id === o.supplier_id)
      const q = searchQuery.toLowerCase().trim()

      const matchesSearch =
        !q ||
        String(o.id).includes(q) ||
        (supp && supp.name.toLowerCase().includes(q)) ||
        (o.notes && o.notes.toLowerCase().includes(q))

      const matchesStatus = statusFilter === 'ALL' || o.status === statusFilter

      return matchesSearch && matchesStatus
    })
  }, [orders, suppliers, searchQuery, statusFilter])

  // Open Create Modal
  const openCreateModal = useCallback(
    (presetSupplierId = null) => {
      const suppId = presetSupplierId || (suppliers[0] ? String(suppliers[0].id) : '')
      const selectedSupp = suppliers.find((s) => s.id === parseInt(suppId, 10))
      const leadDays = selectedSupp?.lead_time_days || 7

      const delivery = new Date()
      delivery.setDate(delivery.getDate() + leadDays)
      const expectedStr = delivery.toISOString().split('T')[0]

      const defaultProduct = products[0]
      const initialItems = defaultProduct
        ? [
            {
              product_id: defaultProduct.id,
              ordered_quantity: 50,
              unit_cost: defaultProduct.cost_price || 10,
            },
          ]
        : []

      setPoForm({
        supplier_id: suppId,
        expected_delivery_date: expectedStr,
        notes: '',
        items: initialItems,
      })
      setFormError('')
      setIsCreateOpen(true)
    },
    [suppliers, products]
  )

  // Line item manipulation
  const addLineItem = () => {
    const firstProd = products[0]
    if (!firstProd) return
    setPoForm((prev) => ({
      ...prev,
      items: [
        ...prev.items,
        {
          product_id: firstProd.id,
          ordered_quantity: 10,
          unit_cost: firstProd.cost_price || 0,
        },
      ],
    }))
  }

  const removeLineItem = (index) => {
    setPoForm((prev) => ({
      ...prev,
      items: prev.items.filter((_, i) => i !== index),
    }))
  }

  const updateLineItem = (index, field, value) => {
    setPoForm((prev) => {
      const updated = [...prev.items]
      const current = { ...updated[index] }

      if (field === 'product_id') {
        const prod = products.find((p) => p.id === parseInt(value, 10))
        current.product_id = parseInt(value, 10)
        if (prod) current.unit_cost = prod.cost_price || 0
      } else if (field === 'ordered_quantity') {
        current.ordered_quantity = parseInt(value, 10) || 1
      } else if (field === 'unit_cost') {
        current.unit_cost = parseFloat(value) || 0
      }

      updated[index] = current
      return { ...prev, items: updated }
    })
  }

  const orderTotal = useMemo(() => {
    return poForm.items.reduce((acc, item) => {
      return acc + (item.ordered_quantity || 0) * (item.unit_cost || 0)
    }, 0)
  }, [poForm.items])

  const supplierOptions = useMemo(
    () =>
      suppliers.map((s) => ({
        value: s.id,
        label: s.name,
        subLabel: `Lead time: ${s.lead_time_days || 7} days • ${s.email || ''}`,
        badge: `ID #${s.id}`,
      })),
    [suppliers]
  )

  const productOptions = useMemo(
    () =>
      products.map((p) => ({
        value: p.id,
        label: p.name,
        subLabel: `Current Stock: ${p.current_stock} ${p.unit} • ${p.category || 'General'}`,
        badge: p.sku,
        meta: `₹${Number(p.cost_price || 0).toFixed(2)}`,
      })),
    [products]
  )

  // Submit PO
  const handleCreateSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')

    const suppId = parseInt(poForm.supplier_id, 10)
    if (!suppId) {
      setFormError('Please select a supplier.')
      setSubmitting(false)
      return
    }

    if (!poForm.items.length) {
      setFormError('At least one line item is required.')
      setSubmitting(false)
      return
    }

    const payload = {
      supplier_id: suppId,
      expected_delivery_date: poForm.expected_delivery_date || null,
      notes: poForm.notes.trim() || null,
      items: poForm.items.map((i) => ({
        product_id: parseInt(i.product_id, 10),
        ordered_quantity: parseInt(i.ordered_quantity, 10),
        unit_cost: parseFloat(i.unit_cost),
      })),
    }

    const res = await dispatch(createPurchaseOrder(payload))
    if (createPurchaseOrder.rejected.match(res)) {
      setFormError(res.payload || 'Failed to create purchase order.')
    } else {
      setIsCreateOpen(false)
    }
    setSubmitting(false)
  }

  // Cancel PO
  const handleCancel = async (orderId) => {
    if (!window.confirm(`Cancel Purchase Order #${orderId}?`)) return
    await dispatch(cancelPurchaseOrder(orderId))
    if (selectedOrder?.id === orderId) setIsDetailOpen(false)
  }

  // Receive Full PO
  const handleReceiveFull = async (orderId) => {
    await dispatch(receivePurchaseOrder(orderId))
    if (selectedOrder?.id === orderId) setIsDetailOpen(false)
  }

  const openDetail = (order) => {
    setSelectedOrder(order)
    setIsDetailOpen(true)
  }

  // Columns definition
  const columns = useMemo(
    () => [
      {
        key: 'id',
        label: 'PO Ref',
        sortable: true,
        render: (o) => (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: 'var(--erp-brand)',
              backgroundColor: 'var(--erp-brand-subtle)',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.825rem',
            }}
          >
            PO-{String(o.id).padStart(4, '0')}
          </span>
        ),
      },
      {
        key: 'order_date',
        label: 'Order Date',
        sortable: true,
        render: (o) => {
          const dateStr = o.order_date
            ? new Date(o.order_date).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
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
        key: 'supplier',
        label: 'Vendor / Supplier',
        sortable: false,
        render: (o) => {
          const supp = suppliers.find((s) => s.id === o.supplier_id)
          return (
            <div>
              <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
                {supp ? supp.name : `Supplier #${o.supplier_id}`}
              </div>
              {supp?.contact_person && (
                <div style={{ fontSize: '0.725rem', color: 'var(--erp-text-muted)' }}>
                  Attn: {supp.contact_person}
                </div>
              )}
            </div>
          )
        },
      },
      {
        key: 'items_summary',
        label: 'Lines & Quantities',
        sortable: false,
        render: (o) => {
          const totalUnits = (o.items || []).reduce((acc, i) => acc + (i.ordered_quantity || 0), 0)
          const totalReceived = (o.items || []).reduce((acc, i) => acc + (i.received_quantity || 0), 0)
          return (
            <div style={{ fontSize: '0.825rem', color: 'var(--erp-text-main)' }}>
              <strong>{o.items?.length || 0}</strong> line(s) &bull;{' '}
              <span>
                {totalReceived} / {totalUnits} received
              </span>
            </div>
          )
        },
      },
      {
        key: 'total_value',
        label: 'Total Value',
        numeric: true,
        sortable: true,
        render: (o) => {
          const totalVal = (o.items || []).reduce(
            (acc, i) => acc + (i.ordered_quantity || 0) * (Number(i.unit_cost) || 0),
            0
          )
          return <span style={{ fontWeight: 700, color: 'var(--erp-text-main)' }}>₹{totalVal.toFixed(2)}</span>
        },
      },
      {
        key: 'expected_delivery_date',
        label: 'Expected Delivery',
        sortable: true,
        render: (o) => {
          const dateStr = o.expected_delivery_date
            ? new Date(o.expected_delivery_date).toLocaleDateString()
            : 'Not specified'
          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>
              <Calendar size={13} color="var(--erp-text-subtle)" />
              <span>{dateStr}</span>
            </div>
          )
        },
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
            {['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(o.status) && (
              <button
                className="btn btn-primary btn-sm"
                onClick={() => navigate(`/receive-order?order_id=${o.id}`)}
                title="Enter received quantities"
              >
                <Inbox size={13} />
                <span>Receive</span>
              </button>
            )}
            <button
              className="btn-action-icon primary"
              onClick={() => openDetail(o)}
              title="View PO Details"
            >
              <Eye size={13} />
            </button>
            {['DRAFT', 'SENT'].includes(o.status) && (
              <button
                className="btn-action-icon danger"
                onClick={() => handleCancel(o.id)}
                title="Cancel PO"
              >
                <XCircle size={13} />
              </button>
            )}
          </div>
        ),
      },
    ],
    [suppliers, navigate]
  )

  return (
    <div className="purchase-orders-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Procurement"
        activePage="Purchase Orders"
        itemCount={filteredOrders.length}
        primaryAction={{
          label: 'New Purchase Order',
          icon: Plus,
          onClick: () => openCreateModal(),
          id: 'btn-create-po',
        }}
        onRefresh={() => dispatch(fetchPurchaseOrders())}
        loading={loading}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="Search PO by ID, vendor name, or notes..."
        exportData={filteredOrders}
        exportFilename="purchase_orders"
        filters={
          <select
            className="form-control"
            style={{ width: '180px', padding: '0.45rem 0.65rem' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="ALL">All Statuses</option>
            <option value="DRAFT">DRAFT</option>
            <option value="SENT">SENT</option>
            <option value="PARTIALLY_RECEIVED">PARTIALLY_RECEIVED</option>
            <option value="RECEIVED">RECEIVED (Completed)</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
        }
      />

      {/* Table with Pagination & Sorting */}
      <DataTable
        columns={columns}
        data={filteredOrders}
        keyField="id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No purchase orders found"
        emptyMessage="Create a new purchase order to request shipments from suppliers."
        emptyIcon={ClipboardList}
      />

      {/* Modal: Create Purchase Order (Document Sheet View) */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Create Purchase Order"
        subtitle="Specify vendor, delivery schedule, and line items."
        size="lg"
      >
        <form onSubmit={handleCreateSubmit}>
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
                  Vendor / Supplier <span className="required">*</span>
                </label>
                <SearchableSelect
                  options={supplierOptions}
                  value={poForm.supplier_id}
                  placeholder="-- Search & Choose Vendor --"
                  searchPlaceholder="Type vendor name, email, or ID..."
                  required
                  id="select-po-supplier"
                  onChange={(sid) => {
                    const supp = suppliers.find((s) => s.id === parseInt(sid, 10))
                    let expStr = poForm.expected_delivery_date
                    if (supp?.lead_time_days) {
                      const d = new Date()
                      d.setDate(d.getDate() + supp.lead_time_days)
                      expStr = d.toISOString().split('T')[0]
                    }
                    setPoForm({
                      ...poForm,
                      supplier_id: sid,
                      expected_delivery_date: expStr,
                    })
                  }}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Expected Delivery Date</label>
                <input
                  type="date"
                  className="form-control"
                  value={poForm.expected_delivery_date}
                  onChange={(e) =>
                    setPoForm({ ...poForm, expected_delivery_date: e.target.value })
                  }
                />
              </div>

              <div className="form-group col-span-2">
                <label className="form-label">Purchase Order Notes / Instructions</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="e.g. Expedited freight, invoice payment net-30, dock delivery"
                  value={poForm.notes}
                  onChange={(e) => setPoForm({ ...poForm, notes: e.target.value })}
                />
              </div>
            </div>

            {/* Line Items Builder */}
            <div style={{ marginTop: '0.5rem' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '0.5rem',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--erp-text-main)' }}>
                  Order Products & Quantities <span className="required">*</span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={addLineItem}
                >
                  <Plus size={13} />
                  <span>Add Line Item</span>
                </button>
              </div>

              <div
                style={{
                  border: '1px solid var(--erp-border)',
                  borderRadius: '6px',
                  overflow: 'visible',
                  background: 'var(--erp-surface-subtle)',
                }}
              >
                <table className="erp-table" style={{ margin: 0, overflow: 'visible' }}>
                  <thead>
                    <tr>
                      <th style={{ width: '45%' }}>Product</th>
                      <th style={{ width: '22%' }} className="numeric">Ordered Qty</th>
                      <th style={{ width: '22%' }} className="numeric">Unit Cost (₹)</th>
                      <th style={{ width: '11%' }} className="center"></th>
                    </tr>
                  </thead>
                  <tbody style={{ overflow: 'visible' }}>
                    {poForm.items.map((item, idx) => (
                      <tr key={idx} style={{ background: 'var(--erp-surface)', overflow: 'visible' }}>
                        <td style={{ overflow: 'visible' }}>
                          <SearchableSelect
                            options={productOptions}
                            value={item.product_id}
                            placeholder="Search & choose product..."
                            searchPlaceholder="Type name, SKU, or category..."
                            required
                            onChange={(val) => {
                              updateLineItem(idx, 'product_id', val)
                            }}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            min="1"
                            required
                            className="form-control numeric"
                            value={item.ordered_quantity}
                            onChange={(e) => updateLineItem(idx, 'ordered_quantity', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            required
                            className="form-control numeric"
                            value={item.unit_cost}
                            onChange={(e) => updateLineItem(idx, 'unit_cost', e.target.value)}
                          />
                        </td>
                        <td className="center">
                          <button
                            type="button"
                            className="btn btn-subtle btn-sm"
                            onClick={() => removeLineItem(idx)}
                            disabled={poForm.items.length <= 1}
                            style={{ color: '#dc2626' }}
                          >
                            <Trash2 size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Grand Total */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  alignItems: 'center',
                  gap: '1rem',
                  marginTop: '0.75rem',
                  padding: '0.5rem 0.75rem',
                  backgroundColor: 'var(--erp-brand-subtle)',
                  borderRadius: '6px',
                  border: '1px solid var(--erp-border)',
                }}
              >
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--erp-brand)' }}>
                  Total Order Value:
                </span>
                <span style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--erp-brand)' }}>
                  ₹{orderTotal.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsCreateOpen(false)}
            >
              Discard
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              id="btn-confirm-save-po"
            >
              {submitting ? 'Creating Order...' : 'Create Purchase Order (DRAFT)'}
            </button>
          </div>
        </form>
      </Modal>

      {/* PO Details Drawer / Modal */}
      {selectedOrder && (
        <Modal
          isOpen={isDetailOpen}
          onClose={() => setIsDetailOpen(false)}
          title={`Purchase Order: PO-${String(selectedOrder.id).padStart(4, '0')}`}
          subtitle={`Created on ${new Date(selectedOrder.order_date).toLocaleDateString()}`}
          size="lg"
        >
          <div className="modal-body">
            {/* Workflow Status Ribbon */}
            <div className="pipeline-statusbar">
              <div className={`pipeline-stage ${selectedOrder.status === 'DRAFT' ? 'active' : 'passed'}`}>
                1. Draft Order
              </div>
              <div className={`pipeline-stage ${selectedOrder.status === 'SENT' ? 'active' : ['PARTIALLY_RECEIVED', 'RECEIVED'].includes(selectedOrder.status) ? 'passed' : ''}`}>
                2. Sent to Vendor
              </div>
              <div className={`pipeline-stage ${selectedOrder.status === 'PARTIALLY_RECEIVED' ? 'active' : selectedOrder.status === 'RECEIVED' ? 'passed' : ''}`}>
                3. Partially Received
              </div>
              <div className={`pipeline-stage ${selectedOrder.status === 'RECEIVED' ? 'active' : ''}`}>
                4. Completed / Received
              </div>
            </div>

            <div className="form-grid">
              <div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Supplier Name</div>
                <div style={{ fontWeight: 700, fontSize: '1rem' }}>
                  {suppliers.find((s) => s.id === selectedOrder.supplier_id)?.name || `Supplier #${selectedOrder.supplier_id}`}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Current Status</div>
                <Badge status={selectedOrder.status} />
              </div>

              <div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Expected Delivery Date</div>
                <div style={{ fontWeight: 600 }}>
                  {selectedOrder.expected_delivery_date
                    ? new Date(selectedOrder.expected_delivery_date).toLocaleDateString()
                    : 'Not specified'}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>Order Notes</div>
                <div style={{ fontStyle: 'italic', color: 'var(--erp-text-main)' }}>
                  {selectedOrder.notes || 'None provided'}
                </div>
              </div>
            </div>

            {/* Items Breakdown Table */}
            <div style={{ marginTop: '1rem' }}>
              <div style={{ fontWeight: 700, fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--erp-text-main)' }}>
                Order Line Items
              </div>
              <div className="table-responsive" style={{ border: '1px solid var(--erp-border)', borderRadius: '6px' }}>
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="numeric">Ordered</th>
                      <th className="numeric">Received</th>
                      <th className="numeric">Remaining</th>
                      <th className="numeric">Unit Cost</th>
                      <th className="numeric">Line Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedOrder.items?.map((item) => {
                      const prod = products.find((p) => p.id === item.product_id)
                      const remaining = item.ordered_quantity - item.received_quantity
                      const lineTotal = item.ordered_quantity * Number(item.unit_cost)

                      return (
                        <tr key={item.id}>
                          <td>
                            <div style={{ fontWeight: 600 }}>
                              {prod ? prod.name : `Product #${item.product_id}`}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                              {prod ? prod.sku : ''}
                            </div>
                          </td>
                          <td className="numeric" style={{ fontWeight: 600 }}>
                            {item.ordered_quantity} {prod?.unit || ''}
                          </td>
                          <td className="numeric" style={{ color: '#059669', fontWeight: 700 }}>
                            {item.received_quantity} {prod?.unit || ''}
                          </td>
                          <td className="numeric" style={{ color: remaining > 0 ? '#d97706' : '#10b981', fontWeight: 700 }}>
                            {remaining} {prod?.unit || ''}
                          </td>
                          <td className="numeric">₹{Number(item.unit_cost).toFixed(2)}</td>
                          <td className="numeric" style={{ fontWeight: 700 }}>
                            ₹{lineTotal.toFixed(2)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
            <div>
              {['DRAFT', 'SENT'].includes(selectedOrder.status) && (
                <button
                  type="button"
                  className="btn btn-subtle btn-sm"
                  onClick={() => handleCancel(selectedOrder.id)}
                  style={{ color: '#dc2626' }}
                >
                  <XCircle size={15} /> Cancel Order
                </button>
              )}
            </div>

            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setIsDetailOpen(false)}
              >
                Close
              </button>
              {['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(selectedOrder.status) && (
                <>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => {
                      setIsDetailOpen(false)
                      navigate(`/receive-order?order_id=${selectedOrder.id}`)
                    }}
                  >
                    <Inbox size={15} /> Receive Line by Line
                  </button>
                  <button
                    type="button"
                    className="btn btn-accent"
                    onClick={() => handleReceiveFull(selectedOrder.id)}
                  >
                    <CheckCircle size={15} /> Receive All at Once
                  </button>
                </>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
