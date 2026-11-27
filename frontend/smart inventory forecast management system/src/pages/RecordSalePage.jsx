import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { AlertTriangle, CheckCircle2, ShoppingCart } from 'lucide-react'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { recordSale } from '../store/salesSlice'
import PageHeader from '../components/common/PageHeader'
import SearchableSelect from '../components/common/SearchableSelect'

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `sale-${crypto.randomUUID()}`
  }
  return `sale-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export default function RecordSalePage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const products = useSelector(selectAllProducts)

  const [productId, setProductId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [sellingPrice, setSellingPrice] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [confirmedSale, setConfirmedSale] = useState(null)
  const [idemKey, setIdemKey] = useState(() => newIdempotencyKey())

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  const activeProductId = productId || (products[0] ? String(products[0].id) : '')
  const selectedProduct = useMemo(
    () => products.find((p) => String(p.id) === String(activeProductId)) || null,
    [products, activeProductId]
  )

  const productOptions = useMemo(
    () =>
      products.map((p) => ({
        value: p.id,
        label: p.name,
        subLabel: `Available: ${p.current_stock} ${p.unit}`,
        badge: p.sku,
        meta: `₹${Number(p.selling_price || 0).toFixed(2)}`,
      })),
    [products]
  )

  const unitPrice = sellingPrice !== '' ? parseFloat(sellingPrice) || 0 : Number(selectedProduct?.selling_price || 0)
  const qtyNum = parseInt(quantity, 10) || 0
  const previewTotal = (unitPrice * qtyNum).toFixed(2)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setConfirmedSale(null)

    if (!activeProductId) {
      setError('Please select a product.')
      return
    }
    if (qtyNum <= 0) {
      setError('Quantity must be greater than 0.')
      return
    }
    if (selectedProduct && qtyNum > selectedProduct.current_stock) {
      setError(`Only ${selectedProduct.current_stock} ${selectedProduct.unit} available in stock.`)
      return
    }

    setSubmitting(true)
    const payload = {
      product_id: parseInt(activeProductId, 10),
      quantity_sold: qtyNum,
      selling_price: sellingPrice !== '' ? parseFloat(sellingPrice) : null,
      notes: notes.trim() || null,
    }
    const res = await dispatch(recordSale({ payload, idempotencyKey: idemKey }))
    if (recordSale.rejected.match(res)) {
      setError(res.payload || 'Sale failed.')
    } else {
      setConfirmedSale(res.payload)
      setQuantity('1')
      setSellingPrice('')
      setNotes('')
      setIdemKey(newIdempotencyKey())
    }
    setSubmitting(false)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: '720px' }}>
      <PageHeader
        title="Record Sale"
        subtitle="Deducts stock through the authoritative ledger. Final totals are calculated on the backend."
        actions={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigate('/sales')}>
            View Sales History
          </button>
        }
      />

      {confirmedSale && (
        <div
          className="section-card"
          style={{
            borderColor: 'var(--status-success-border)',
            backgroundColor: 'var(--status-success-bg)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.625rem',
            color: 'var(--status-success-text)',
          }}
        >
          <CheckCircle2 size={18} />
          <span>
            Sale <strong>#SO-{String(confirmedSale.id).padStart(4, '0')}</strong> recorded —{' '}
            {confirmedSale.quantity_sold} units, verified revenue{' '}
            <strong>₹{Number(confirmedSale.revenue).toFixed(2)}</strong>.
          </span>
        </div>
      )}

      <form className="section-card" onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {error && (
          <div className="form-error-banner">
            <AlertTriangle size={18} />
            <div>{error}</div>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Product</label>
          <SearchableSelect
            options={productOptions}
            value={activeProductId}
            onChange={(val) => {
              setProductId(String(val))
              const prod = products.find((p) => String(p.id) === String(val))
              setSellingPrice(prod ? String(prod.selling_price) : '')
            }}
            placeholder="Select product to sell..."
          />
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label className="form-label" htmlFor="sale-qty">
              Quantity <span className="required">*</span>
            </label>
            <input
              id="sale-qty"
              type="number"
              min="1"
              required
              className="form-control"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="sale-price">Unit Selling Price (₹)</label>
            <input
              id="sale-price"
              type="number"
              step="0.01"
              min="0"
              className="form-control"
              placeholder={selectedProduct ? String(selectedProduct.selling_price) : '0.00'}
              value={sellingPrice}
              onChange={(e) => setSellingPrice(e.target.value)}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="sale-notes">Notes (Optional)</label>
          <input
            id="sale-notes"
            type="text"
            className="form-control"
            placeholder="Invoice reference or customer note..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <div
          style={{
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--erp-surface-subtle)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <span style={{ fontSize: '0.84rem', color: 'var(--erp-text-muted)' }}>
            Estimated Total Preview (backend authoritative):
          </span>
          <strong style={{ fontSize: '1.15rem', color: '#059669' }}>₹{previewTotal}</strong>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            <ShoppingCart size={15} />
            <span>{submitting ? 'Submitting...' : 'Confirm & Record Sale'}</span>
          </button>
        </div>
      </form>
    </div>
  )
}
