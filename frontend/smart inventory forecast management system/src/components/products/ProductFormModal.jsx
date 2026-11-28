import { useState, useEffect, useMemo, useRef } from 'react'
import { AlertTriangle } from 'lucide-react'
import Modal from '../Modal'
import SearchableSelect from '../common/SearchableSelect'
import FormField from '../common/FormField'
import { useTranslation } from '../../hooks/useTranslation'
import { validateAndBuildProductPayload } from '../../utils/formHelpers'

export default function ProductFormModal({
  isOpen,
  onClose,
  mode = 'add', // 'add' | 'edit'
  initialProduct = null,
  suppliers = [],
  defaultSku = '',
  defaultCategory = 'General',
  onSubmit,
  submitting = false,
  error = '',
}) {
  const { t } = useTranslation()
  const [formData, setFormData] = useState({
    sku: '',
    name: '',
    category: 'General',
    unit: 'piece',
    cost_price: '0',
    selling_price: '0',
    current_stock: '0',
    reorder_level: '10',
    supplier_id: '',
    min_order_quantity: '1',
    order_pack_size: '1',
    max_stock_level: '',
    review_period_days: '7',
    initial_daily_demand: '',
  })
  const [localError, setLocalError] = useState('')
  const lastOpenSigRef = useRef('closed')

  useEffect(() => {
    const openSignature = isOpen ? `${mode}:${initialProduct?.id ?? 'new'}` : 'closed'
    if (openSignature === lastOpenSigRef.current) return undefined
    lastOpenSigRef.current = openSignature
    if (!isOpen) return undefined

    const timer = setTimeout(() => {
      setLocalError('')
      if (mode === 'edit' && initialProduct) {
        setFormData({
          sku: initialProduct.sku || '',
          name: initialProduct.name || '',
          category: initialProduct.category || 'General',
          unit: initialProduct.unit || 'piece',
          cost_price: String(initialProduct.cost_price ?? 0),
          selling_price: String(initialProduct.selling_price ?? 0),
          current_stock: String(initialProduct.current_stock ?? 0),
          reorder_level: String(initialProduct.reorder_level ?? 10),
          supplier_id: initialProduct.supplier_id || '',
          min_order_quantity: String(initialProduct.min_order_quantity ?? 1),
          order_pack_size: String(initialProduct.order_pack_size ?? 1),
          max_stock_level: initialProduct.max_stock_level != null ? String(initialProduct.max_stock_level) : '',
          review_period_days: String(initialProduct.review_period_days ?? 7),
          initial_daily_demand:
            initialProduct.initial_daily_demand != null ? String(initialProduct.initial_daily_demand) : '',
        })
      } else {
        setFormData({
          sku: defaultSku,
          name: '',
          category: defaultCategory || 'General',
          unit: 'piece',
          cost_price: '10',
          selling_price: '15',
          current_stock: '0',
          reorder_level: '10',
          supplier_id: suppliers[0]?.id || '',
          min_order_quantity: '1',
          order_pack_size: '1',
          max_stock_level: '',
          review_period_days: '7',
          initial_daily_demand: '',
        })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [isOpen, mode, initialProduct, defaultSku, defaultCategory, suppliers])

  const supplierOptions = useMemo(
    () => [
      { value: '', label: '-- No Supplier Assigned --' },
      ...suppliers.map((s) => ({
        value: s.id,
        label: s.name,
        subLabel: s.email || s.contact_person || 'Supplier',
        badge: `#${s.id}`,
      })),
    ],
    [suppliers]
  )

  const handleSubmit = (e) => {
    e.preventDefault()
    if (submitting) return
    setLocalError('')

    const { error: validationError, payload } = validateAndBuildProductPayload(formData, mode)
    if (validationError || !payload) {
      setLocalError(validationError || 'Please review the product fields.')
      return
    }
    onSubmit(payload)
  }

  const displayError = localError || error

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={mode === 'edit' ? `Edit Product: ${initialProduct?.name}` : 'Add New Product'}
      subtitle={mode === 'edit' ? `SKU: ${initialProduct?.sku}` : 'Create an inventory SKU in your active workspace'}
      size="lg"
    >
      <form onSubmit={handleSubmit}>
        <div className="modal-body">
          {displayError && (
            <div className="form-error-banner">
              <AlertTriangle size={18} style={{ flexShrink: 0 }} />
              <div>{displayError}</div>
            </div>
          )}

          <div className="form-grid">
            <FormField label="SKU" htmlFor="prod-sku" required hint={t('common.skuHelp')}>
              <input
                id="prod-sku"
                type="text"
                required
                className="form-control"
                placeholder={t('placeholders.productSku', 'e.g. RICE-001')}
                value={formData.sku}
                onChange={(e) => setFormData((prev) => ({ ...prev, sku: e.target.value }))}
              />
            </FormField>

            <FormField label="Product Name" htmlFor="prod-name" required>
              <input
                id="prod-name"
                type="text"
                required
                className="form-control"
                placeholder={t('placeholders.productName', 'e.g. Premium Basmati Rice 5kg')}
                value={formData.name}
                onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
              />
            </FormField>

            <FormField label="Category" htmlFor="prod-category">
              <input
                id="prod-category"
                type="text"
                className="form-control"
                placeholder={t('placeholders.productCategory', 'e.g. Grains & Staples')}
                value={formData.category}
                onChange={(e) => setFormData((prev) => ({ ...prev, category: e.target.value }))}
              />
            </FormField>

            <FormField label="Unit of Measure" htmlFor="prod-unit">
              <select
                id="prod-unit"
                className="form-control"
                value={formData.unit}
                onChange={(e) => setFormData((prev) => ({ ...prev, unit: e.target.value }))}
              >
                <option value="piece">piece</option>
                <option value="kg">kg</option>
                <option value="box">box</option>
                <option value="pack">pack</option>
                <option value="meter">meter</option>
                <option value="liter">liter</option>
              </select>
            </FormField>

            <FormField label="Cost Price (₹)" htmlFor="prod-cost" hint="Unit purchase cost (0 or more).">
              <input
                id="prod-cost"
                type="number"
                step="0.01"
                min="0"
                className="form-control"
                placeholder={t('placeholders.costPrice', 'e.g. 45.00')}
                value={formData.cost_price}
                onChange={(e) => setFormData((prev) => ({ ...prev, cost_price: e.target.value }))}
              />
            </FormField>

            <FormField label="Selling Price (₹)" htmlFor="prod-sell" hint="Unit retail/wholesale selling price (0 or more).">
              <input
                id="prod-sell"
                type="number"
                step="0.01"
                min="0"
                className="form-control"
                placeholder={t('placeholders.sellingPrice', 'e.g. 60.00')}
                value={formData.selling_price}
                onChange={(e) => setFormData((prev) => ({ ...prev, selling_price: e.target.value }))}
              />
            </FormField>

            {mode === 'add' ? (
              <FormField label="Opening Stock" htmlFor="prod-opening" hint="Initial stock recorded directly into ledger.">
                <input
                  id="prod-opening"
                  type="number"
                  min="0"
                  step="1"
                  className="form-control"
                  placeholder={t('placeholders.openingStock', 'e.g. 25')}
                  value={formData.current_stock}
                  onChange={(e) => setFormData((prev) => ({ ...prev, current_stock: e.target.value }))}
                />
              </FormField>
            ) : (
              <FormField label="Current Stock (Read-Only)">
                <input
                  type="text"
                  disabled
                  className="form-control"
                  value={`${formData.current_stock} ${formData.unit} (adjust via Stock Adjustments)`}
                />
              </FormField>
            )}

            <FormField label="Reorder Level" htmlFor="prod-reorder" hint="Alert threshold when on-hand stock falls at or below this count.">
              <input
                id="prod-reorder"
                type="number"
                min="0"
                step="1"
                className="form-control"
                placeholder={t('placeholders.reorderLevel', 'e.g. 20')}
                value={formData.reorder_level}
                onChange={(e) => setFormData((prev) => ({ ...prev, reorder_level: e.target.value }))}
              />
            </FormField>

            <FormField label="Supplier" htmlFor="prod-supplier" className="col-span-2">
              <SearchableSelect
                id="prod-supplier"
                options={supplierOptions}
                value={formData.supplier_id}
                onChange={(val) => setFormData((prev) => ({ ...prev, supplier_id: val }))}
                placeholder="Search and select supplier..."
              />
            </FormField>

            <FormField label="Min Order Qty (MOQ)" htmlFor="prod-moq" hint="Minimum units per purchase order (≥ 1).">
              <input
                id="prod-moq"
                type="number"
                min="1"
                step="1"
                className="form-control"
                placeholder={t('placeholders.moq', 'e.g. 10')}
                value={formData.min_order_quantity}
                onChange={(e) => setFormData((prev) => ({ ...prev, min_order_quantity: e.target.value }))}
              />
            </FormField>

            <FormField label="Pack Size Multiple" htmlFor="prod-pack" hint="Suggested orders round up to multiples of this pack size.">
              <input
                id="prod-pack"
                type="number"
                min="1"
                step="1"
                className="form-control"
                placeholder={t('placeholders.packSize', 'e.g. 5')}
                value={formData.order_pack_size}
                onChange={(e) => setFormData((prev) => ({ ...prev, order_pack_size: e.target.value }))}
              />
            </FormField>

            <FormField label="Review Cycle (Days)" htmlFor="prod-review" hint="Days between reorder checks (0–90 days).">
              <input
                id="prod-review"
                type="number"
                min="0"
                max="90"
                step="1"
                className="form-control"
                placeholder={t('placeholders.reviewDays', 'e.g. 7')}
                value={formData.review_period_days}
                onChange={(e) => setFormData((prev) => ({ ...prev, review_period_days: e.target.value }))}
              />
            </FormField>

            <FormField label="Max Stock Cap (Optional)" htmlFor="prod-max-stock">
              <input
                id="prod-max-stock"
                type="number"
                min="1"
                step="1"
                placeholder={t('placeholders.maxStock', 'e.g. 500 (leave blank for no cap)')}
                className="form-control"
                value={formData.max_stock_level}
                onChange={(e) => setFormData((prev) => ({ ...prev, max_stock_level: e.target.value }))}
              />
            </FormField>

            <FormField
              label="Cold-Start Daily Demand Estimate (Optional units/day for new SKUs)"
              htmlFor="prod-init-demand"
              className="col-span-2"
              hint="Used only before sufficient sales history accumulates."
            >
              <input
                id="prod-init-demand"
                type="number"
                step="0.1"
                min="0"
                placeholder={t('placeholders.coldStartDemand', 'e.g. 4.5 (or leave blank to learn from sales)')}
                className="form-control"
                value={formData.initial_daily_demand}
                onChange={(e) => setFormData((prev) => ({ ...prev, initial_daily_demand: e.target.value }))}
              />
            </FormField>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Saving...' : mode === 'edit' ? 'Update Product' : 'Save Product'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
