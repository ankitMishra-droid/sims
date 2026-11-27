export const API_BASE_URL =
  import.meta?.env?.VITE_API_URL ||
  (typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : 'http://127.0.0.1:8000')

let _refreshPromise = null

function getStoredUserBusinessId() {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem('stocksangati_user')
    const parsed = raw ? JSON.parse(raw) : null
    return parsed?.active_business_id || null
  } catch {
    return null
  }
}

function clearAuthStorage(notify = false) {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem('stocksangati_token')
    localStorage.removeItem('stocksangati_refresh_token')
    localStorage.removeItem('stocksangati_user')
  } catch {
    // ignore storage access issues
  }
  if (notify) {
    window.dispatchEvent(new CustomEvent('stocksangati:auth-expired'))
  }
}

async function tryRefreshSession() {
  if (typeof window === 'undefined') return null
  const refreshToken = localStorage.getItem('stocksangati_refresh_token')
  if (!refreshToken) return null

  if (!_refreshPromise) {
    _refreshPromise = fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        if (!res.ok) return null
        const data = await res.json()
        if (data?.access_token) {
          localStorage.setItem('stocksangati_token', data.access_token)
          if (data.refresh_token) localStorage.setItem('stocksangati_refresh_token', data.refresh_token)
          if (data.user) localStorage.setItem('stocksangati_user', JSON.stringify(data.user))
          return data.access_token
        }
        return null
      })
      .catch(() => null)
      .finally(() => {
        _refreshPromise = null
      })
  }
  return _refreshPromise
}

async function request(endpoint, options = {}, _retried = false) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('stocksangati_token') : null
  const activeBizId = getStoredUserBusinessId()

  const defaultHeaders = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(token && activeBizId ? { 'X-Business-Id': String(activeBizId) } : {}),
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
      const isAuthEndpoint =
        endpoint.startsWith('/api/auth/login') || endpoint.startsWith('/api/auth/refresh')
      if (res.status === 401 && token && !isAuthEndpoint) {
        if (!_retried) {
          const freshToken = await tryRefreshSession()
          if (freshToken) {
            return request(
              endpoint,
              {
                ...options,
                headers: { ...options.headers, Authorization: `Bearer ${freshToken}` },
              },
              true
            )
          }
        }
        clearAuthStorage(true)
      }
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
  // Authentication & Session
  register: (userData) =>
    request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    }),
  login: (credentials) =>
    request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    }),
  refreshToken: (refreshToken) =>
    request('/api/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),
  logout: (payload = {}) =>
    request('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getMe: () => request('/api/auth/me'),
  updateMe: (payload) =>
    request('/api/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  changePassword: (payload) =>
    request('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  requestPasswordReset: (email) =>
    request('/api/auth/password-reset/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  confirmPasswordReset: (payload) =>
    request('/api/auth/password-reset/confirm', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Workspaces, Memberships & Onboarding
  getWorkspaces: () => request('/api/businesses/'),
  createWorkspace: (payload) =>
    request('/api/businesses/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getCurrentWorkspace: () => request('/api/businesses/current'),
  updateCurrentWorkspace: (payload) =>
    request('/api/businesses/current', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  switchWorkspace: (businessId) =>
    request('/api/businesses/switch', {
      method: 'POST',
      body: JSON.stringify({ business_id: businessId }),
    }),
  getMembers: () => request('/api/members/'),
  inviteMember: (payload) =>
    request('/api/members/invite', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getInvitations: () => request('/api/members/invitations'),
  getMyInvitations: () => request('/api/members/my-invitations'),
  acceptInvitation: (token) =>
    request('/api/members/accept-invitation', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  revokeInvitation: (invitationId) =>
    request(`/api/members/invitations/${invitationId}`, { method: 'DELETE' }),
  updateMemberRole: (memberId, role) =>
    request(`/api/members/${memberId}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    }),
  removeMember: (memberId) =>
    request(`/api/members/${memberId}`, { method: 'DELETE' }),
  getOnboardingProgress: () => request('/api/onboarding/progress'),
  saveOnboardingStep: (payload) =>
    request('/api/onboarding/step', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  linkSupplierWorkspace: (supplierId, supplierBusinessId) =>
    request(`/api/suppliers/${supplierId}/link-workspace`, {
      method: 'PATCH',
      body: JSON.stringify({ supplier_business_id: supplierBusinessId }),
    }),
  sharePurchaseOrder: (orderId) =>
    request(`/api/purchase-orders/${orderId}/share`, { method: 'POST' }),
  unsharePurchaseOrder: (orderId) =>
    request(`/api/purchase-orders/${orderId}/unshare`, { method: 'POST' }),
  getSupplierPortalOrders: () => request('/api/supplier-portal/purchase-orders'),
  getSupplierPortalOrder: (orderId) => request(`/api/supplier-portal/purchase-orders/${orderId}`),
  updateSupplierOrderStatus: (orderId, payload) =>
    request(`/api/supplier-portal/purchase-orders/${orderId}/status`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // System Health
  checkHealth: () => request('/'),

  // Products
  getProducts: async () => {
    try {
      const res = await request('/api/products/')
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
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
  getSales: async (params = {}) => {
    const query = new URLSearchParams()
    if (params.product_id) query.set('product_id', String(params.product_id))
    if (params.start_date) query.set('start_date', params.start_date)
    if (params.end_date) query.set('end_date', params.end_date)
    if (params.skip !== undefined) query.set('skip', String(params.skip))
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    const qs = query.toString() ? `?${query.toString()}` : ''
    try {
      const res = await request(`/api/sales/${qs}`)
      return res.data || []
    } catch (err) {
      if (err.status === 404) return []
      throw err
    }
  },
  getSalesPage: async (params = {}) => {
    const query = new URLSearchParams()
    if (params.product_id) query.set('product_id', String(params.product_id))
    if (params.start_date) query.set('start_date', params.start_date)
    if (params.end_date) query.set('end_date', params.end_date)
    if (params.skip !== undefined) query.set('skip', String(params.skip))
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    const qs = query.toString() ? `?${query.toString()}` : ''
    const res = await request(`/api/sales/${qs}`)
    return { data: res.data || [], total: res.total ?? (res.data || []).length }
  },
  createSale: async (saleData, idempotencyKey = null) => {
    const res = await request('/api/sales/', {
      method: 'POST',
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
      body: JSON.stringify(saleData),
    })
    return res
  },
  cancelSale: async (saleId, reason = 'sale_cancelled') => {
    const res = await request(`/api/sales/${saleId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
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
  adjustStock: async (adjustmentData) => {
    const res = await request('/api/inventory/adjust', {
      method: 'POST',
      body: JSON.stringify(adjustmentData),
    })
    return res
  },
  getInventoryPositions: async () => {
    const res = await request('/api/inventory/positions')
    return Array.isArray(res) ? res : []
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
  sendPurchaseOrder: async (id) => {
    const res = await request(`/api/purchase-orders/${id}/send`, {
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
  partiallyReceivePurchaseOrder: async (id, receiveData, idempotencyKey = null) => {
    const res = await request(`/api/purchase-orders/${id}/partially_receive`, {
      method: 'POST',
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
      body: JSON.stringify(receiveData),
    })
    return res
  },
  createGoodsReceipt: async (id, receiptData, idempotencyKey = null) => {
    const res = await request(`/api/purchase-orders/${id}/receipts`, {
      method: 'POST',
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
      body: JSON.stringify(receiptData),
    })
    return res
  },
  getGoodsReceipts: async (id) => {
    const res = await request(`/api/purchase-orders/${id}/receipts`)
    return Array.isArray(res) ? res : []
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

  // Machine Learning Demand Forecasting
  getForecast: async (productId, horizonDays = 30, model = 'auto') => {
    const res = await request(`/api/forecast/${productId}?horizon_days=${horizonDays}&model=${model}`)
    return res.data
  },
  compareModels: async (productId, testDays = 30) => {
    const res = await request(`/api/forecast/compare/${productId}?test_days=${testDays}`)
    return res.data
  },

  // Inventory Decision Engine & Smart Reorder Planner
  getReorderRecommendations: async (serviceLevel = 0.95) => {
    const res = await request(`/api/decision/recommendations?service_level=${serviceLevel}`)
    return res.data || []
  },
  getProductDecision: async (productId, serviceLevel = 0.95) => {
    const res = await request(`/api/decision/product/${productId}?service_level=${serviceLevel}`)
    return res.data
  },
  convertRecommendationToPo: async (poData) => {
    const res = await request('/api/decision/convert-to-po', {
      method: 'POST',
      body: JSON.stringify(poData),
    })
    return res
  },

  // What-If Scenario Simulator
  runWhatIfSimulation: async (scenarioData) => {
    const res = await request('/api/simulator/scenario', {
      method: 'POST',
      body: JSON.stringify(scenarioData),
    })
    return res.data
  },

  // Anomaly Detection
  getProductAnomalies: async (productId, lookbackDays = 90) => {
    const res = await request(`/api/analytics/anomalies/${productId}?lookback_days=${lookbackDays}`)
    return res.data
  },
}
