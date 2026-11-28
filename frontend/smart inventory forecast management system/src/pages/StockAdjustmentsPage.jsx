import { useState, useEffect, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { adjustProductStock } from '../store/inventorySlice'
import PageHeader from '../components/common/PageHeader'
import SearchableSelect from '../components/common/SearchableSelect'
import FormField from '../components/common/FormField'
import { useTranslation } from '../hooks/useTranslation'
import { parseStrictPositiveInt } from '../utils/formHelpers'

export default function StockAdjustmentsPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const products = useSelector(selectAllProducts)

  const [productId, setProductId] = useState(searchParams.get('product_id') || '')
  const [direction, setDirection] = useState('add') // 'add' | 'remove'
  const [quantity, setQuantity] = useState('1')
  const [movementType, setMovementType] = useState('STOCK_ADJUSTMENT')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

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
        subLabel: `Current: ${p.current_stock} ${p.unit}`,
        badge: p.sku,
      })),
    [products]
  )

  const qtyNum = parseStrictPositiveInt(quantity) ?? 0
  const delta = direction === 'remove' ? -Math.abs(qtyNum) : Math.abs(qtyNum)
  const projectedStock = selectedProduct ? selectedProduct.current_stock + delta : null

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError('')
    setResult(null)

    const parsedProductId = parseStrictPositiveInt(activeProductId)
    if (!parsedProductId) {
      setError('Please select a product.')
      return
    }
    const parsedQty = parseStrictPositiveInt(quantity)
    if (parsedQty === null) {
      setError('Adjustment quantity must be a whole number greater than 0.')
      return
    }
    if (reason.trim().length < 2) {
      setError('Please provide a clear reason (at least 2 characters).')
      return
    }

    const signedDelta = direction === 'remove' ? -parsedQty : parsedQty
    setSubmitting(true)
    const res = await dispatch(
      adjustProductStock({
        product_id: parsedProductId,
        quantity_delta: signedDelta,
        reason: reason.trim(),
        movement_type: movementType,
      })
    )
    if (adjustProductStock.rejected.match(res)) {
      setError(res.payload || 'Stock adjustment failed.')
    } else {
      setResult(res.payload)
      setReason('')
      setQuantity('1')
    }
    setSubmitting(false)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: '720px' }}>
      <PageHeader
        title="Stock Adjustments"
        subtitle="Record audited positive or negative inventory corrections with a required reason."
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => navigate(`/inventory/history?product_id=${activeProductId}`)}
          >
            View Stock History
          </button>
        }
      />

      {result && (
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
            Stock updated from <strong>{result.previous_stock}</strong> to{' '}
            <strong>{result.current_stock}</strong> (Ledger #{result.log_id}).
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
            onChange={(val) => setProductId(String(val))}
            placeholder="Select product..."
          />
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label className="form-label" htmlFor="adj-dir">Adjustment Direction</label>
            <select
              id="adj-dir"
              className="form-control"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option value="add">Increase Stock (+)</option>
              <option value="remove">Decrease Stock (-)</option>
            </select>
          </div>

          <FormField label="Quantity" htmlFor="adj-qty" required>
            <input
              id="adj-qty"
              type="number"
              min="1"
              required
              className="form-control"
              placeholder={t('placeholders.adjustQuantity', 'e.g. 10')}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </FormField>

          <div className="form-group">
            <label className="form-label" htmlFor="adj-type">Movement Type</label>
            <select
              id="adj-type"
              className="form-control"
              value={movementType}
              onChange={(e) => setMovementType(e.target.value)}
            >
              <option value="STOCK_ADJUSTMENT">STOCK_ADJUSTMENT</option>
              <option value="RETURN">RETURN</option>
              <option value="OPENING_STOCK">OPENING_STOCK</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Projected Resulting Stock</label>
            <input
              type="text"
              disabled
              className="form-control"
              value={
                selectedProduct
                  ? `${selectedProduct.current_stock} -> ${projectedStock} ${selectedProduct.unit}`
                  : 'Select a product'
              }
            />
          </div>
        </div>

        <FormField label="Reason" htmlFor="adj-reason" required hint="Required for stock audit trail">
          <input
            id="adj-reason"
            type="text"
            required
            className="form-control"
            placeholder={t('placeholders.adjustReason', 'e.g. Physical cycle count variance or damaged box')}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Applying...' : 'Apply Adjustment'}
          </button>
        </div>
      </form>
    </div>
  )
}
