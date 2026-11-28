import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { AlertTriangle, CheckCircle2, ShoppingCart } from 'lucide-react'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { recordSale } from '../store/salesSlice'
import PageHeader from '../components/common/PageHeader'
import SearchableSelect from '../components/common/SearchableSelect'
import FormField from '../components/common/FormField'
import { useTranslation } from '../hooks/useTranslation'
import { validateAndBuildSalePayload } from '../utils/formHelpers'

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return `sale-${crypto.randomUUID()}`
  }
  return `sale-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export default function RecordSalePage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t } = useTranslation()
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

  const rawSellPrice = sellingPrice.trim()
  const parsedSellPrice = rawSellPrice !== '' ? Number(rawSellPrice) : Number(selectedProduct?.selling_price || 0)
  const unitPrice = Number.isFinite(parsedSellPrice) ? parsedSellPrice : 0
  const qtyNum = /^\d+$/.test(String(quantity).trim()) ? parseInt(quantity, 10) : 0
  const previewTotal = (unitPrice * qtyNum).toFixed(2)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError('')
    setConfirmedSale(null)

    const { error: validationError, payload } = validateAndBuildSalePayload(
      {
        productId: activeProductId,
        quantity,
        sellingPrice,
        notes,
      },
      { availableStock: selectedProduct?.current_stock ?? null }
    )
    if (validationError) {
      setError(validationError)
      return
    }

    setSubmitting(true)
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
          <FormField label="Quantity" htmlFor="sale-qty" required>
            <input
              id="sale-qty"
              type="number"
              min="1"
              required
              className="form-control"
              placeholder={t('placeholders.saleQuantity', 'e.g. 5')}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </FormField>

          <FormField
            label="Unit Selling Price (₹)"
            htmlFor="sale-price"
            hint="Leave blank to use default product price"
          >
            <input
              id="sale-price"
              type="number"
              step="0.01"
              min="0"
              className="form-control"
              placeholder={
                selectedProduct
                  ? `e.g. ${Number(selectedProduct.selling_price || 0).toFixed(2)}`
                  : t('placeholders.sellingPrice', 'e.g. 60.00')
              }
              value={sellingPrice}
              onChange={(e) => setSellingPrice(e.target.value)}
            />
          </FormField>
        </div>

        <FormField label="Notes (Optional)" htmlFor="sale-notes">
          <input
            id="sale-notes"
            type="text"
            className="form-control"
            placeholder={t('placeholders.saleNotes', 'e.g. Counter bill #INV-1042 or customer reference')}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </FormField>

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
