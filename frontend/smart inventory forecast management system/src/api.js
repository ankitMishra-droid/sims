export const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : 'http://127.0.0.1:8000')

async function request(endpoint, options = {}) {
  const defaultHeaders = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  }

  const targetUrl = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`

  try {
    const res = await fetch(targetUrl, config)
    const isJson = res.headers.get('content-type')?.includes('application/json')
    const data = isJson ? await res.json() : await res.text()


    if (!res.ok) {
      let errorMessage = 'An error occurred while communicating with the server'
      if (data && typeof data === 'object') {
        if (typeof data.detail === 'string') {
          errorMessage = data.detail
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail
            .map((err) => {
              const field = err.loc ? err.loc[err.loc.length - 1] : ''
              return field ? `${field}: ${err.msg}` : err.msg
            })
            .join(', ')
        } else if (data.message) {
          errorMessage = data.message
        }
      }
      const error = new Error(errorMessage)
      error.status = res.status
      error.payload = data
      throw error
    }

    return data
  } catch (err) {
    // If direct connection threw TypeError (e.g. host unreachable), attempt relative fallback
    if (!endpoint.startsWith('http')) {
      try {
        const fallbackRes = await fetch(endpoint, config)
        if (fallbackRes.ok) {
          const isJson = fallbackRes.headers.get('content-type')?.includes('application/json')
          return isJson ? await fallbackRes.json() : await fallbackRes.text()
        }
      } catch {
        // Fallback also failed
      }
    }

    if (!err.status && err.name === 'TypeError') {
      const connErr = new Error('Cannot connect to backend server. Ensure backend is running.')
      connErr.status = 0
      throw connErr
    }
    throw err
  }
}

export const api = {
  // System Health
  checkHealth: () => request('/'),

  // Products
  getProducts: async () => {
    const res = await request('/api/products/')
    return res.data || []
  },
  getProduct: async (id) => {
    const res = await request(`/api/products/${id}`)
    return res.data
  },
  createProduct: async (productData) => {
    const res = await request('/api/products/', {
      method: 'POST',
      body: JSON.stringify(productData),
    })
    return res
  },
  updateProduct: async (id, productData) => {
    const res = await request(`/api/products/${id}`, {
      method: 'PUT',
      body: JSON.stringify(productData),
    })
    return res
  },
  deactivateProduct: async (id) => {
    const res = await request(`/api/products/deactivate/${id}`, {
      method: 'PATCH',
    })
    return res
  },
  activateProduct: async (id) => {
    const res = await request(`/api/products/activate/${id}`, {
      method: 'PATCH',
    })
    return res
  },

  // Sales
  getSales: async () => {
    try {
      const res = await request('/api/sales/')
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },
  createSale: async (saleData) => {
    const res = await request('/api/sales/', {
      method: 'POST',
      body: JSON.stringify(saleData),
    })
    return res
  },
  getSaleByProduct: async (productId) => {
    try {
      const res = await request(`/api/sales/product/${productId}`)
      return res.data
    } catch (err) {
      if (err.status === 404) return null
      throw err
    }
  },
  getSalesByDateRange: async (startDate, endDate) => {
    try {
      const res = await request(`/api/sales/date-range/?start_date=${startDate}&end_date=${endDate}`)
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },

  // Inventory
  getLowStockProducts: async () => {
    try {
      const res = await request('/api/inventory/low-stock')
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },
  getInventoryLogs: async (productId) => {
    try {
      const res = await request(`/api/inventory/logs/${productId}`)
      return Array.isArray(res) ? res : res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },
  stockIn: async (stockData) => {
    const res = await request('/api/inventory/stock-in', {
      method: 'POST',
      body: JSON.stringify(stockData),
    })
    return res
  },

  // Suppliers
  getSuppliers: async () => {
    try {
      const res = await request('/api/suppliers/')
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },
  getSupplier: async (id) => {
    const res = await request(`/api/suppliers/${id}`)
    return res.data
  },
  createSupplier: async (supplierData) => {
    const res = await request('/api/suppliers/', {
      method: 'POST',
      body: JSON.stringify(supplierData),
    })
    return res
  },
  updateSupplier: async (id, supplierData) => {
    const res = await request(`/api/suppliers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(supplierData),
    })
    return res
  },
  deactivateSupplier: async (id) => {
    const res = await request(`/api/suppliers/${id}`, {
      method: 'PATCH',
    })
    return res
  },
  activateSupplier: async (id) => {
    const res = await request(`/api/suppliers/${id}/activate`, {
      method: 'PATCH',
    })
    return res
  },

  // Purchase Orders
  getPurchaseOrders: async () => {
    const res = await request('/api/purchase-orders/')
    return Array.isArray(res) ? res : []
  },
  getPurchaseOrder: async (id) => {
    const res = await request(`/api/purchase-orders/${id}`)
    return res
  },
  createPurchaseOrder: async (orderData) => {
    const res = await request('/api/purchase-orders/', {
      method: 'POST',
      body: JSON.stringify(orderData),
    })
    return res
  },
  updatePurchaseOrder: async (id, orderData) => {
    const res = await request(`/api/purchase-orders/${id}`, {
      method: 'PUT',
      body: JSON.stringify(orderData),
    })
    return res
  },
  cancelPurchaseOrder: async (id) => {
    const res = await request(`/api/purchase-orders/${id}/cancel`, {
      method: 'POST',
    })
    return res
  },
  receivePurchaseOrder: async (id) => {
    const res = await request(`/api/purchase-orders/${id}/receive`, {
      method: 'POST',
    })
    return res
  },
  partiallyReceivePurchaseOrder: async (id, receiveData) => {
    const res = await request(`/api/purchase-orders/${id}/partially_receive`, {
      method: 'POST',
      body: JSON.stringify(receiveData),
    })
    return res
  },

  // Dashboard Metrics
  getDashboardSummary: async () => {
    return request('/dashboard/summary')
  },
  getPurchaseOrderMetrics: async () => {
    return request('/dashboard/purchase-order-metrics')
  },
  getInventoryMovementMetrics: async () => {
    return request('/dashboard/inventory-movement-metrics')
  },
  getSalesMetrics: async () => {
    return request('/dashboard/sales-metrics')
  },
  getSupplierMetrics: async () => {
    return request('/dashboard/supplier-metrics')
  },
}
