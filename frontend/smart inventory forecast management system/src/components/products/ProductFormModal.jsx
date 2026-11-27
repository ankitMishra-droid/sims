import { useState, useEffect, useMemo } from 'react'
import { AlertTriangle } from 'lucide-react'
import Modal from '../Modal'
import SearchableSelect from '../common/SearchableSelect'

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
  const [formData, setFormData] = useState({
    sku: '',
    name: '',
    category: 'General',
    unit: 'piece',
    cost_price: 0,
    selling_price: 0,
    current_stock: 0,
    reorder_level: 10,
    supplier_id: '',
  })
  const [localError, setLocalError] = useState('')

  useEffect(() => {
    if (!isOpen) return
    const timer = setTimeout(() => {
      setLocalError('')
      if (mode === 'edit' && initialProduct) {
        setFormData({
          sku: initialProduct.sku || '',
          name: initialProduct.name || '',
          category: initialProduct.category || 'General',
          unit: initialProduct.unit || 'piece',
          cost_price: initialProduct.cost_price ?? 0,
          selling_price: initialProduct.selling_price ?? 0,
          current_stock: initialProduct.current_stock ?? 0,
          reorder_level: initialProduct.reorder_level ?? 10,
          supplier_id: initialProduct.supplier_id || '',
        })
      } else {
        setFormData({
          sku: defaultSku,
          name: '',
          category: defaultCategory || 'General',
          unit: 'piece',
          cost_price: 10,
          selling_price: 15,
          current_stock: 0,
          reorder_level: 10,
          supplier_id: suppliers[0]?.id || '',
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
    setLocalError('')

    const sku = formData.sku.trim()
    const name = formData.name.trim()
    const cost = parseFloat(formData.cost_price)
    const sell = parseFloat(formData.selling_price)
    const reorder = parseInt(formData.reorder_level, 10)
    const opening = parseInt(formData.current_stock, 10)

    if (!sku || !name) {
      setLocalError('SKU and Product Name are required.')
      return
    }
    if (isNaN(cost) || cost < 0 || isNaN(sell) || sell < 0) {
      setLocalError('Cost price and selling price must be 0 or greater.')
      return
    }
    if (isNaN(reorder) || reorder < 0) {
      setLocalError('Reorder level must be 0 or greater.')
      return
    }
    if (mode === 'add' && (isNaN(opening) || opening < 0)) {
      setLocalError('Opening stock must be 0 or greater.')
      return
    }

    const payload = {
      sku,
      name,
      category: formData.category.trim() || 'General',
      unit: formData.unit.trim() || 'piece',
      cost_price: cost,
      selling_price: sell,
      reorder_level: reorder,
      supplier_id: formData.supplier_id ? parseInt(formData.supplier_id, 10) : null,
      ...(mode === 'add' ? { current_stock: opening } : {}),
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
            <div className="form-group">
              <label className="form-label" htmlFor="prod-sku">
                SKU <span className="required">*</span>
              </label>
              <input
                id="prod-sku"
                type="text"
                required
                className="form-control"
                value={formData.sku}
                onChange={(e) => setFormData({ ...formData, sku: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="prod-name">
                Product Name <span className="required">*</span>
              </label>
              <input
                id="prod-name"
                type="text"
                required
                className="form-control"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="prod-category">
                Category
              </label>
              <input
                id="prod-category"
                type="text"
                className="form-control"
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="prod-unit">
                Unit of Measure
              </label>
              <select
                id="prod-unit"
                className="form-control"
                value={formData.unit}
                onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
              >
                <option value="piece">piece</option>
                <option value="kg">kg</option>
                <option value="box">box</option>
                <option value="pack">pack</option>
                <option value="meter">meter</option>
                <option value="liter">liter</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="prod-cost">
                Cost Price (₹)
              </label>
              <input
                id="prod-cost"
                type="number"
                step="0.01"
                min="0"
                className="form-control"
                value={formData.cost_price}
                onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="prod-sell">
                Selling Price (₹)
              </label>
              <input
                id="prod-sell"
                type="number"
                step="0.01"
                min="0"
                className="form-control"
                value={formData.selling_price}
                onChange={(e) => setFormData({ ...formData, selling_price: e.target.value })}
              />
            </div>

            {mode === 'add' ? (
              <div className="form-group">
                <label className="form-label" htmlFor="prod-opening">
                  Opening Stock
                </label>
                <input
                  id="prod-opening"
                  type="number"
                  min="0"
                  className="form-control"
                  value={formData.current_stock}
                  onChange={(e) => setFormData({ ...formData, current_stock: e.target.value })}
                />
              </div>
            ) : (
              <div className="form-group">
                <label className="form-label">Current Stock (Read-Only)</label>
                <input
                  type="text"
                  disabled
                  className="form-control"
                  value={`${formData.current_stock} ${formData.unit} (adjust via Stock Adjustments)`}
                />
              </div>
            )}

            <div className="form-group">
              <label className="form-label" htmlFor="prod-reorder">
                Reorder Level
              </label>
              <input
                id="prod-reorder"
                type="number"
                min="0"
                className="form-control"
                value={formData.reorder_level}
                onChange={(e) => setFormData({ ...formData, reorder_level: e.target.value })}
              />
            </div>

            <div className="form-group col-span-2">
              <label className="form-label">Supplier</label>
              <SearchableSelect
                options={supplierOptions}
                value={formData.supplier_id}
                onChange={(val) => setFormData({ ...formData, supplier_id: val })}
                placeholder="Search and select supplier..."
              />
            </div>
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
