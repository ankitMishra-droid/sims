import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  Inbox,
  CheckCircle2,
  AlertTriangle,
  Check,
  Package,
} from 'lucide-react'
import {
  selectAllPurchaseOrders,
  selectPurchaseOrdersLoading,
  fetchPurchaseOrders,
  receivePurchaseOrder,
  partiallyReceivePOItem,
} from '../store/purchaseOrdersSlice'
import { selectAllProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import Badge from '../components/Badge'
import SearchableSelect from '../components/common/SearchableSelect'

export default function ReceiveOrderPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const orders = useSelector(selectAllPurchaseOrders)
  const loading = useSelector(selectPurchaseOrdersLoading)
  const products = useSelector(selectAllProducts)
  const suppliers = useSelector(selectAllSuppliers)

  const [selectedOrderId, setSelectedOrderId] = useState(searchParams.get('order_id') || '')
  const [receivingItemId, setReceivingItemId] = useState(null)
  const [receivingAll, setReceivingAll] = useState(false)
  const [formError, setFormError] = useState('')

  // State for quantity to receive per line item: { [itemId]: number }
  const [receiveQuantities, setReceiveQuantities] = useState({})

  useEffect(() => {
    dispatch(fetchPurchaseOrders())
    dispatch(fetchProducts())
    dispatch(fetchSuppliers())
  }, [dispatch])

  // If no order selected, pick first active pending order
  useEffect(() => {
    const pendingOrders = orders.filter((o) =>
      ['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(o.status)
    )
    if (!selectedOrderId && pendingOrders.length > 0) {
      const firstId = String(pendingOrders[0].id)
      setSelectedOrderId(firstId)
      setSearchParams({ order_id: firstId })
    }
  }, [orders, selectedOrderId, setSearchParams])

  // Current selected order
  const selectedOrder = useMemo(() => {
    if (!selectedOrderId) return null
    return orders.find((o) => o.id === parseInt(selectedOrderId, 10)) || null
  }, [orders, selectedOrderId])

  // Initialize line item quantities to remaining
  useEffect(() => {
    if (selectedOrder?.items) {
      const initialQtys = {}
      selectedOrder.items.forEach((item) => {
        const rem = Math.max(0, item.ordered_quantity - item.received_quantity)
        initialQtys[item.id] = rem
      })
      setReceiveQuantities(initialQtys)
    }
  }, [selectedOrder])

  const handleSelectOrder = (orderId) => {
    setSelectedOrderId(orderId)
    setSearchParams({ order_id: orderId })
    setFormError('')
  }

  // Memoized searchable PO options
  const orderOptions = useMemo(() => {
    return [
      { value: '', label: '-- Choose Purchase Order --' },
      ...orders.map((o) => {
        const supp = suppliers.find((s) => s.id === o.supplier_id)
        return {
          value: o.id,
          label: `PO-${String(o.id).padStart(4, '0')}`,
          subLabel: `${supp?.name || `Vendor #${o.supplier_id}`} • ${o.items?.length || 0} line items`,
          badge: o.status,
          meta: `₹${Number(o.total_amount || 0).toLocaleString()}`,
        }
      }),
    ]
  }, [orders, suppliers])

  const handleQtyChange = (itemId, val) => {
    const num = parseInt(val, 10)
    setReceiveQuantities((prev) => ({
      ...prev,
      [itemId]: isNaN(num) ? '' : num,
    }))
  }

  // Receive single line item
  const handleReceiveLine = async (item) => {
    const qtyToReceive = parseInt(receiveQuantities[item.id], 10)

    if (!qtyToReceive || qtyToReceive <= 0) {
      setFormError('Please enter a quantity greater than 0.')
      return
    }

    setReceivingItemId(item.id)
    setFormError('')

    const res = await dispatch(
      partiallyReceivePOItem({
        orderId: selectedOrder.id,
        payload: {
          purchase_order_item_id: item.id,
          received_quantity: qtyToReceive,
        },
      })
    )

    if (partiallyReceivePOItem.rejected.match(res)) {
      setFormError(res.payload || 'Failed to receive line item.')
    }
    setReceivingItemId(null)
  }

  // Receive entire order
  const handleReceiveAll = async () => {
    if (!selectedOrder) return
    setReceivingAll(true)
    setFormError('')

    const res = await dispatch(receivePurchaseOrder(selectedOrder.id))
    if (receivePurchaseOrder.rejected.match(res)) {
      setFormError(res.payload || 'Failed to receive order.')
    }
    setReceivingAll(false)
  }

  // Progress metrics
  const progressMetrics = useMemo(() => {
    if (!selectedOrder || !selectedOrder.items) return { total: 0, received: 0, percent: 0 }
    const total = selectedOrder.items.reduce((acc, i) => acc + i.ordered_quantity, 0)
    const received = selectedOrder.items.reduce((acc, i) => acc + i.received_quantity, 0)
    const percent = total > 0 ? Math.round((received / total) * 100) : 0
    return { total, received, percent }
  }, [selectedOrder])

  const supplier = suppliers.find((s) => s.id === selectedOrder?.supplier_id)

  // Columns for line items
  const columns = useMemo(
    () => [
      {
        key: 'product',
        label: 'Item & Product',
        sortable: false,
        render: (item) => {
          const prod = products.find((p) => p.id === item.product_id)
          return (
            <div>
              <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
                {prod ? prod.name : `Product #${item.product_id}`}
              </div>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  color: 'var(--erp-brand)',
                  backgroundColor: 'var(--erp-brand-subtle)',
                  padding: '2px 6px',
                  borderRadius: '4px',
                }}
              >
                {prod ? prod.sku : `ID: ${item.product_id}`}
              </span>
            </div>
          )
        },
      },
      {
        key: 'category',
        label: 'Category',
        sortable: false,
        render: (item) => {
          const prod = products.find((p) => p.id === item.product_id)
          return prod?.category || 'General'
        },
      },
      {
        key: 'ordered_quantity',
        label: 'Ordered Units',
        numeric: true,
        sortable: true,
        render: (item) => {
          const prod = products.find((p) => p.id === item.product_id)
          return `${item.ordered_quantity} ${prod?.unit || ''}`
        },
      },
      {
        key: 'received_quantity',
        label: 'Received So Far',
        numeric: true,
        sortable: true,
        render: (item) => {
          const prod = products.find((p) => p.id === item.product_id)
          return (
            <span style={{ color: '#059669', fontWeight: 700 }}>
              {item.received_quantity} {prod?.unit || ''}
            </span>
          )
        },
      },
      {
        key: 'remaining',
        label: 'Remaining Due',
        numeric: true,
        sortable: true,
        render: (item) => {
          const prod = products.find((p) => p.id === item.product_id)
          const remaining = Math.max(0, item.ordered_quantity - item.received_quantity)
          return (
            <span style={{ color: remaining > 0 ? '#d97706' : '#10b981', fontWeight: 800 }}>
              {remaining} {prod?.unit || ''}
            </span>
          )
        },
      },
      {
        key: 'input_qty',
        label: 'Quantity to Receive Now',
        sortable: false,
        render: (item) => {
          const remaining = Math.max(0, item.ordered_quantity - item.received_quantity)
          const isFullyReceived = remaining === 0
          const currentVal = receiveQuantities[item.id] !== undefined ? receiveQuantities[item.id] : remaining

          if (isFullyReceived) {
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#16a34a', fontSize: '0.8rem', fontWeight: 600 }}>
                <CheckCircle2 size={16} /> Fully Received
              </div>
            )
          }

          return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <input
                type="number"
                min="1"
                max={remaining}
                className="form-control numeric"
                style={{ width: '90px', padding: '0.35rem 0.5rem' }}
                value={currentVal}
                onChange={(e) => handleQtyChange(item.id, e.target.value)}
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => handleQtyChange(item.id, remaining)}
                title="Fill maximum remaining"
                style={{ padding: '0.35rem 0.55rem' }}
              >
                Max
              </button>
            </div>
          )
        },
      },
      {
        key: 'action',
        label: 'Action',
        center: true,
        sortable: false,
        render: (item) => {
          const remaining = Math.max(0, item.ordered_quantity - item.received_quantity)
          const isFullyReceived = remaining === 0
          const isReceivingThis = receivingItemId === item.id
          const currentVal = receiveQuantities[item.id] !== undefined ? receiveQuantities[item.id] : remaining

          if (isFullyReceived) {
            return <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Complete</span>
          }

          return (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => handleReceiveLine(item)}
              disabled={isReceivingThis || currentVal <= 0}
            >
              <Check size={13} />
              <span>{isReceivingThis ? 'Saving...' : 'Confirm Line'}</span>
            </button>
          )
        },
      },
    ],
    [products, receiveQuantities, receivingItemId]
  )

  return (
    <div className="receive-order-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Warehouse Inbound"
        activePage="Receive Order Items"
        itemCount={selectedOrder?.items?.length || 0}
        primaryAction={
          selectedOrder && ['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(selectedOrder.status)
            ? {
                label: receivingAll ? 'Receiving...' : 'Receive All Lines at Once',
                icon: CheckCircle2,
                onClick: handleReceiveAll,
                id: 'btn-receive-all-items',
              }
            : null
        }
        onRefresh={() => dispatch(fetchPurchaseOrders())}
        loading={loading}
        filters={
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', width: '100%', maxWidth: '650px' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--erp-text-main)', whiteSpace: 'nowrap' }}>
              Select Inbound Order:
            </span>
            <div style={{ flex: 1 }}>
              <SearchableSelect
                options={orderOptions}
                value={selectedOrderId}
                onChange={(val) => handleSelectOrder(val)}
                placeholder="Search PO by ID, supplier, or status..."
                id="select-po-to-receive"
              />
            </div>
          </div>
        }
      />

      {/* Backend Error Banner */}
      {formError && (
        <div className="form-error-banner" style={{ marginBottom: '1.25rem' }}>
          <AlertTriangle size={20} style={{ flexShrink: 0 }} />
          <div>
            <strong>Backend Rule Violation:</strong> {formError}
          </div>
        </div>
      )}

      {!selectedOrder ? (
        <div className="table-card empty-state">
          <div className="empty-state-icon">
            <Inbox size={32} />
          </div>
          <div className="empty-state-title">Select a purchase order to receive</div>
          <p className="empty-state-desc">
            Choose an order from the dropdown above to inspect incoming items and record received quantities.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Header Card: Order Metadata & Status */}
          <div
            style={{
              background: 'var(--erp-surface)',
              border: '1px solid var(--erp-border)',
              borderRadius: '8px',
              padding: '1.25rem 1.5rem',
              boxShadow: 'var(--shadow-xs)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
              transition: 'background-color 0.25s ease, border-color 0.25s ease',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '1rem',
                borderBottom: '1px solid var(--erp-border)',
                paddingBottom: '0.85rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
                <div
                  style={{
                    width: '44px',
                    height: '44px',
                    borderRadius: '8px',
                    backgroundColor: 'var(--erp-brand-subtle)',
                    color: 'var(--erp-brand)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 800,
                  }}
                >
                  <Inbox size={22} />
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <h2 style={{ fontSize: '1.25rem', color: 'var(--erp-brand)', margin: 0 }}>
                      PO-{String(selectedOrder.id).padStart(4, '0')}
                    </h2>
                    <Badge status={selectedOrder.status} />
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)', marginTop: '2px' }}>
                    Order Date: {new Date(selectedOrder.order_date).toLocaleDateString()}
                  </div>
                </div>
              </div>

              {/* Inbound Completion Progress */}
              <div style={{ minWidth: '220px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.775rem', marginBottom: '0.25rem' }}>
                  <span style={{ color: 'var(--erp-text-muted)' }}>Receipt Progress:</span>
                  <strong style={{ color: progressMetrics.percent === 100 ? '#10b981' : 'var(--erp-brand)' }}>
                    {progressMetrics.received} of {progressMetrics.total} units ({progressMetrics.percent}%)
                  </strong>
                </div>
                <div style={{ height: '8px', backgroundColor: 'var(--erp-border)', borderRadius: '999px', overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${progressMetrics.percent}%`,
                      backgroundColor: progressMetrics.percent === 100 ? '#10b981' : 'var(--erp-brand)',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Vendor & Schedule Details */}
            <div className="form-grid">
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                  Vendor / Supplier
                </span>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--erp-text-main)' }}>
                  {supplier?.name || `Supplier #${selectedOrder.supplier_id}`}
                </div>
                {supplier?.email && (
                  <div style={{ fontSize: '0.775rem', color: 'var(--erp-text-muted)' }}>{supplier.email}</div>
                )}
              </div>

              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                  Expected Delivery
                </span>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--erp-text-main)' }}>
                  {selectedOrder.expected_delivery_date
                    ? new Date(selectedOrder.expected_delivery_date).toLocaleDateString()
                    : 'Flexible schedule'}
                </div>
              </div>
            </div>
          </div>

          {/* Reusable Data Table for Line Items */}
          <DataTable
            columns={columns}
            data={selectedOrder.items || []}
            keyField="id"
            defaultPageSize={10}
            loading={loading}
            emptyTitle="No items in this order"
            emptyMessage="There are no line items attached to this purchase order."
            emptyIcon={Inbox}
          />
        </div>
      )}
    </div>
  )
}
