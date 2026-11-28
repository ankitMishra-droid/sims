import { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { CheckCircle2, Send, AlertTriangle, RefreshCw, Inbox } from 'lucide-react'
import {
  selectAllPurchaseOrders,
  selectPurchaseOrdersLoading,
  fetchPurchaseOrders,
  sendPurchaseOrder,
  receivePurchaseOrder,
} from '../store/purchaseOrdersSlice'
import { selectAllProducts, fetchProducts } from '../store/productsSlice'
import { selectAllSuppliers, fetchSuppliers } from '../store/suppliersSlice'
import { showToast } from '../store/uiSlice'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import { parseStrictNonNegativeInt } from '../utils/formHelpers'
import PageHeader from '../components/common/PageHeader'
import SearchableSelect from '../components/common/SearchableSelect'
import Badge from '../components/Badge'
import { EmptyState } from '../components/common/StateBlocks'

function newReceiptKey() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return `gr-${crypto.randomUUID()}`
  return `gr-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export default function ReceiveOrderPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const orders = useSelector(selectAllPurchaseOrders)
  const loading = useSelector(selectPurchaseOrdersLoading)
  const products = useSelector(selectAllProducts)
  const suppliers = useSelector(selectAllSuppliers)

  const [selectedOrderId, setSelectedOrderId] = useState(searchParams.get('order_id') || '')
  const [receiveQuantities, setReceiveQuantities] = useState({})
  const [receiptNotes, setReceiptNotes] = useState('')
  const [receiptsHistory, setReceiptsHistory] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [idemKey, setIdemKey] = useState(() => newReceiptKey())

  useEffect(() => {
    dispatch(fetchPurchaseOrders())
    dispatch(fetchProducts())
    dispatch(fetchSuppliers())
  }, [dispatch])

  const activeOrderId = useMemo(() => {
    if (selectedOrderId) return selectedOrderId
    const open = orders.find((o) => ['SENT', 'PARTIALLY_RECEIVED', 'DRAFT'].includes(o.status))
    return open ? String(open.id) : ''
  }, [orders, selectedOrderId])

  const selectedOrder = useMemo(
    () => orders.find((o) => String(o.id) === String(activeOrderId)) || null,
    [orders, activeOrderId]
  )

  const loadReceipts = useCallback(async (orderId) => {
    if (!orderId) {
      setReceiptsHistory([])
      return
    }
    try {
      const list = await api.getGoodsReceipts(orderId)
      setReceiptsHistory(list)
    } catch {
      setReceiptsHistory([])
    }
  }, [])

  useEffect(() => {
    if (!selectedOrder?.id) return undefined
    const id = setTimeout(() => {
      loadReceipts(selectedOrder.id)
    }, 0)
    return () => clearTimeout(id)
  }, [selectedOrder?.id, loadReceipts])

  const orderOptions = useMemo(
    () =>
      orders.map((o) => {
        const supp = suppliers.find((s) => s.id === o.supplier_id)
        return {
          value: o.id,
          label: o.order_number || `PO-${String(o.id).padStart(4, '0')}`,
          subLabel: `${supp?.name || `Supplier #${o.supplier_id}`} • ${(o.items || []).length} lines`,
          badge: o.status,
          meta: `₹${Number(o.total_amount || 0).toFixed(2)}`,
        }
      }),
    [orders, suppliers]
  )

  const handleSelectOrder = (val) => {
    setSelectedOrderId(String(val))
    setReceiveQuantities({})
    setFormError('')
    setIdemKey(newReceiptKey())
    setSearchParams(val ? { order_id: String(val) } : {})
  }

  const handleQtyChange = (itemId, val) => {
    setReceiveQuantities((prev) => ({ ...prev, [itemId]: val }))
  }

  const handleSubmitReceipt = async (e) => {
    e.preventDefault()
    if (!selectedOrder || submitting) return
    setFormError('')

    const itemsPayload = []
    for (const item of selectedOrder.items || []) {
      const remaining = Math.max(0, item.ordered_quantity - item.received_quantity)
      if (remaining === 0) continue
      const raw = receiveQuantities[item.id] !== undefined ? receiveQuantities[item.id] : remaining
      const rawStr = String(raw).trim()
      if (rawStr === '') continue
      const qty = parseStrictNonNegativeInt(rawStr)
      if (qty === null) {
        setFormError(`Quantity for line #${item.id} must be a whole number of 0 or more.`)
        return
      }
      if (qty > remaining) {
        setFormError(`Quantity for line #${item.id} (${qty}) exceeds remaining due (${remaining}).`)
        return
      }
      if (qty > 0) {
        itemsPayload.push({ purchase_order_item_id: item.id, received_quantity: qty })
      }
    }

    if (itemsPayload.length === 0) {
      setFormError('Enter a received quantity greater than 0 for at least one outstanding item.')
      return
    }

    setSubmitting(true)
    try {
      await api.createGoodsReceipt(
        selectedOrder.id,
        { items: itemsPayload, notes: receiptNotes.trim() || null },
        idemKey
      )
      dispatch(showToast('Goods Received', 'Inventory and stock ledger updated.', 'success'))
      setReceiveQuantities({})
      setReceiptNotes('')
      setIdemKey(newReceiptKey())
      await dispatch(fetchPurchaseOrders())
      await dispatch(fetchProducts())
      await loadReceipts(selectedOrder.id)
    } catch (err) {
      setFormError(err.message || 'Goods receipt failed.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReceiveAll = async () => {
    if (!selectedOrder) return
    setSubmitting(true)
    setFormError('')
    const res = await dispatch(receivePurchaseOrder(selectedOrder.id))
    if (receivePurchaseOrder.rejected.match(res)) {
      setFormError(res.payload || 'Failed to receive order.')
    } else {
      await loadReceipts(selectedOrder.id)
    }
    setSubmitting(false)
  }

  const canReceive = selectedOrder && ['SENT', 'PARTIALLY_RECEIVED'].includes(selectedOrder.status)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Receive Orders (Goods Receipt)"
        subtitle="Verify delivered quantities and record partial or full receipts into inventory."
        actions={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => dispatch(fetchPurchaseOrders())} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        }
      />

      <div className="section-card" style={{ maxWidth: '540px' }}>
        <label className="form-label" style={{ marginBottom: '0.4rem', display: 'block' }}>
          Select Purchase Order
        </label>
        <SearchableSelect
          options={orderOptions}
          value={activeOrderId}
          onChange={handleSelectOrder}
          placeholder="Search PO..."
        />
      </div>

      {formError && (
        <div className="form-error-banner">
          <AlertTriangle size={18} />
          <div>{formError}</div>
        </div>
      )}

      {!selectedOrder ? (
        <EmptyState
          title="No purchase order selected"
          description="Select a sent or partially received purchase order to record inbound goods."
          icon={Inbox}
        />
      ) : (
        <>
          <div className="section-card" style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem', alignItems: 'center' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <strong style={{ fontSize: '1.1rem', fontFamily: 'var(--font-mono)' }}>
                  {selectedOrder.order_number || `PO-${String(selectedOrder.id).padStart(4, '0')}`}
                </strong>
                <Badge status={selectedOrder.status} />
              </div>
              <div style={{ fontSize: '0.82rem', color: 'var(--erp-text-muted)', marginTop: '4px' }}>
                Supplier: {suppliers.find((s) => s.id === selectedOrder.supplier_id)?.name || `#${selectedOrder.supplier_id}`} •
                Total: ₹{Number(selectedOrder.total_amount || 0).toFixed(2)}
              </div>
            </div>

            {selectedOrder.status === 'DRAFT' && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => dispatch(sendPurchaseOrder(selectedOrder.id))}
              >
                <Send size={14} />
                <span>Send PO Before Receiving</span>
              </button>
            )}

            {canReceive && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleReceiveAll} disabled={submitting}>
                <CheckCircle2 size={14} />
                <span>Receive All Remaining</span>
              </button>
            )}
          </div>

          <form className="section-card" onSubmit={handleSubmitReceipt} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="numeric">Ordered</th>
                    <th className="numeric">Received</th>
                    <th className="numeric">Remaining</th>
                    <th className="numeric">Receive Now</th>
                  </tr>
                </thead>
                <tbody>
                  {(selectedOrder.items || []).map((item) => {
                    const prod = products.find((p) => p.id === item.product_id)
                    const remaining = Math.max(0, item.ordered_quantity - item.received_quantity)
                    const val = receiveQuantities[item.id] !== undefined ? receiveQuantities[item.id] : remaining
                    return (
                      <tr key={item.id}>
                        <td>
                          <strong>{prod?.name || `Product #${item.product_id}`}</strong>
                          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>{prod?.sku}</div>
                        </td>
                        <td className="numeric">{item.ordered_quantity}</td>
                        <td className="numeric">{item.received_quantity}</td>
                        <td className="numeric" style={{ fontWeight: 700, color: remaining > 0 ? '#d97706' : '#059669' }}>
                          {remaining}
                        </td>
                        <td className="numeric">
                          {remaining === 0 ? (
                            <span style={{ color: '#059669', fontSize: '0.8rem', fontWeight: 600 }}>Complete</span>
                          ) : (
                            <input
                              type="number"
                              min="0"
                              max={remaining}
                              disabled={!canReceive}
                              placeholder={`e.g. ${remaining}`}
                              aria-label={`Receive quantity for ${prod?.name || `Product #${item.product_id}`}`}
                              className="form-control numeric"
                              style={{ width: '96px', marginLeft: 'auto' }}
                              value={val}
                              onChange={(e) => handleQtyChange(item.id, e.target.value)}
                            />
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {canReceive && (
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                <input
                  type="text"
                  className="form-control"
                  style={{ flex: '1 1 260px' }}
                  placeholder={t('placeholders.receiptNotes', 'e.g. Challan #DC-8841 verified at dock')}
                  aria-label="Receipt notes or challan number"
                  value={receiptNotes}
                  onChange={(e) => setReceiptNotes(e.target.value)}
                />
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  <CheckCircle2 size={15} />
                  <span>{submitting ? 'Recording Receipt...' : 'Confirm Goods Receipt'}</span>
                </button>
              </div>
            )}
          </form>

          {receiptsHistory.length > 0 && (
            <section className="section-card">
              <h2 className="section-card-title" style={{ marginBottom: '0.75rem' }}>
                Recorded Receipts ({receiptsHistory.length})
              </h2>
              <div className="table-responsive">
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>Receipt #</th>
                      <th>Date</th>
                      <th>Lines Received</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {receiptsHistory.map((gr) => (
                      <tr key={gr.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{gr.receipt_number}</td>
                        <td>{new Date(gr.received_at).toLocaleString()}</td>
                        <td>{gr.items.map((i) => `${i.quantity_received}x #${i.product_id}`).join(', ')}</td>
                        <td>{gr.notes || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
