let _rowKeyCounter = 0

/**
 * Generates a unique, monotonic key for editable list items so adding/removing rows never resets sibling inputs.
 */
export function createStableRowKey(prefix = 'row') {
  return `${prefix}-${++_rowKeyCounter}`
}

export function parseStrictPositiveInt(rawValue) {
  const str = String(rawValue ?? '').trim()
  if (!/^\d+$/.test(str)) return null
  const num = Number(str)
  if (!Number.isSafeInteger(num) || num < 1) return null
  return num
}

export function parseStrictNonNegativeInt(rawValue) {
  const str = String(rawValue ?? '').trim()
  if (!/^\d+$/.test(str)) return null
  const num = Number(str)
  if (!Number.isSafeInteger(num) || num < 0) return null
  return num
}

export function parseNonNegativeDecimal(rawValue) {
  const str = String(rawValue ?? '').trim()
  if (!str) return null
  const num = Number(str)
  if (!Number.isFinite(num) || num < 0) return null
  return num
}

export function validateAndBuildPurchaseOrderPayload(poForm) {
  if (!poForm?.supplier_id) {
    return { error: 'Please select a supplier.', payload: null }
  }
  const supplierId = parseStrictPositiveInt(poForm.supplier_id)
  if (supplierId === null) {
    return { error: 'Please select a valid supplier.', payload: null }
  }
  const items = Array.isArray(poForm.items) ? poForm.items : []
  if (items.length === 0) {
    return { error: 'Add at least one product line.', payload: null }
  }

  const normalizedItems = []
  for (let i = 0; i < items.length; i += 1) {
    const row = items[i]
    const productId = parseStrictPositiveInt(row.product_id)
    if (productId === null) {
      return { error: `Line #${i + 1}: Please select a product.`, payload: null }
    }
    const orderedQuantity = parseStrictPositiveInt(row.ordered_quantity)
    if (orderedQuantity === null) {
      return { error: `Line #${i + 1}: Ordered quantity must be a whole number of 1 or more.`, payload: null }
    }
    const unitCost = parseNonNegativeDecimal(row.unit_cost)
    if (unitCost === null) {
      return { error: `Line #${i + 1}: Unit cost must be a valid non-negative number.`, payload: null }
    }
    normalizedItems.push({
      product_id: productId,
      ordered_quantity: orderedQuantity,
      unit_cost: unitCost,
    })
  }

  return {
    error: '',
    payload: {
      supplier_id: supplierId,
      expected_delivery_date: poForm.expected_delivery_date || null,
      notes: String(poForm.notes || '').trim() || null,
      items: normalizedItems,
    },
  }
}

export function validateAndBuildProductPayload(formData, mode = 'add') {
  const sku = String(formData?.sku ?? '').trim()
  const name = String(formData?.name ?? '').trim()
  if (!sku || !name) {
    return { error: 'SKU and Product Name are required.', payload: null }
  }

  const cost = parseNonNegativeDecimal(formData.cost_price)
  const sell = parseNonNegativeDecimal(formData.selling_price)
  if (cost === null || sell === null) {
    return { error: 'Cost price and selling price must be 0 or greater.', payload: null }
  }

  const reorder = parseStrictNonNegativeInt(formData.reorder_level)
  if (reorder === null) {
    return { error: 'Reorder level must be a whole number of 0 or greater.', payload: null }
  }

  const moq = parseStrictPositiveInt(formData.min_order_quantity)
  if (moq === null) {
    return { error: 'Minimum order quantity (MOQ) must be 1 or greater.', payload: null }
  }

  const packSize = parseStrictPositiveInt(formData.order_pack_size)
  if (packSize === null) {
    return { error: 'Pack size multiple must be 1 or greater.', payload: null }
  }

  const reviewDays = parseStrictNonNegativeInt(formData.review_period_days)
  if (reviewDays === null || reviewDays > 90) {
    return { error: 'Review cycle days must be a whole number between 0 and 90.', payload: null }
  }

  const rawMax = String(formData.max_stock_level ?? '').trim()
  let maxStock = null
  if (rawMax !== '') {
    maxStock = parseStrictPositiveInt(rawMax)
    if (maxStock === null) {
      return { error: 'Max stock level must be a whole number greater than 0 when set.', payload: null }
    }
  }

  const rawInit = String(formData.initial_daily_demand ?? '').trim()
  let initDemand = null
  if (rawInit !== '') {
    initDemand = parseNonNegativeDecimal(rawInit)
    if (initDemand === null) {
      return { error: 'Initial daily demand estimate must be 0 or greater.', payload: null }
    }
  }

  let opening = null
  if (mode === 'add') {
    opening = parseStrictNonNegativeInt(formData.current_stock)
    if (opening === null) {
      return { error: 'Opening stock must be a whole number of 0 or greater.', payload: null }
    }
  }

  const supplierId =
    formData.supplier_id !== '' && formData.supplier_id !== null && formData.supplier_id !== undefined
      ? parseStrictPositiveInt(formData.supplier_id)
      : null

  return {
    error: '',
    payload: {
      sku,
      name,
      category: String(formData.category ?? '').trim() || 'General',
      unit: String(formData.unit ?? '').trim() || 'piece',
      cost_price: cost,
      selling_price: sell,
      reorder_level: reorder,
      min_order_quantity: moq,
      order_pack_size: packSize,
      max_stock_level: maxStock,
      review_period_days: reviewDays,
      initial_daily_demand: initDemand,
      supplier_id: supplierId,
      ...(mode === 'add' ? { current_stock: opening } : {}),
    },
  }
}

export function validateAndBuildSupplierPayload(formData) {
  const name = String(formData?.name ?? '').trim()
  if (!name) {
    return { error: 'Supplier name is required.', payload: null }
  }

  const leadDays = parseStrictNonNegativeInt(formData.lead_time_days)
  if (leadDays === null || leadDays > 365) {
    return { error: 'Lead time days must be a whole number between 0 and 365.', payload: null }
  }

  const email = String(formData.email ?? '').trim()
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return { error: 'Please enter a valid supplier email address.', payload: null }
  }

  return {
    error: '',
    payload: {
      name,
      contact_person: String(formData.contact_person ?? '').trim() || null,
      email: email || null,
      phone: String(formData.phone ?? '').trim() || null,
      address: String(formData.address ?? '').trim() || null,
      lead_time_days: leadDays,
    },
  }
}

export function validateAndBuildSalePayload(
  { productId, quantity, sellingPrice, notes },
  { availableStock = null, allowNegativeStock = false } = {}
) {
  const parsedProdId = parseStrictPositiveInt(productId)
  if (parsedProdId === null) {
    return { error: 'Please select a product.', payload: null }
  }
  const qty = parseStrictPositiveInt(quantity)
  if (qty === null) {
    return { error: 'Quantity must be a whole number greater than 0.', payload: null }
  }
  if (!allowNegativeStock && availableStock !== null && qty > availableStock) {
    return { error: `Only ${availableStock} units available in stock.`, payload: null }
  }

  const rawPrice = String(sellingPrice ?? '').trim()
  let parsedPrice = null
  if (rawPrice !== '') {
    parsedPrice = parseNonNegativeDecimal(rawPrice)
    if (parsedPrice === null) {
      return { error: 'Unit selling price must be 0 or greater.', payload: null }
    }
  }

  return {
    error: '',
    payload: {
      product_id: parsedProdId,
      quantity_sold: qty,
      selling_price: parsedPrice,
      notes: String(notes ?? '').trim() || null,
    },
  }
}
