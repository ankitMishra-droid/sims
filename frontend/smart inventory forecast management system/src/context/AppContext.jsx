import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api'

const AppContext = createContext(null)

export function AppProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const [apiOnline, setApiOnline] = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)

  // Global cached lists to power smooth dropdowns across screens
  const [productsCache, setProductsCache] = useState([])
  const [suppliersCache, setSuppliersCache] = useState([])
  const [loadingInitial, setLoadingInitial] = useState(true)

  const showToast = useCallback((title, message, type = 'info', duration = 4000) => {
    const id = Date.now() + Math.random().toString(36).substr(2, 4)
    setToasts((prev) => [...prev, { id, title, message, type }])

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, duration)
  }, [])

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const triggerRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  // Check health and load cache
  const loadGlobalData = useCallback(async () => {
    try {
      await api.checkHealth()
      setApiOnline(true)

      const [prods, supps] = await Promise.allSettled([
        api.getProducts(),
        api.getSuppliers(),
      ])

      if (prods.status === 'fulfilled') {
        setProductsCache(prods.value || [])
      }
      if (supps.status === 'fulfilled') {
        setSuppliersCache(supps.value || [])
      }
    } catch {
      setApiOnline(false)
    } finally {
      setLoadingInitial(false)
    }
  }, [])

  useEffect(() => {
    loadGlobalData()
    const interval = setInterval(loadGlobalData, 30000)
    return () => clearInterval(interval)
  }, [loadGlobalData, refreshKey])

  return (
    <AppContext.Provider
      value={{
        toasts,
        showToast,
        removeToast,
        apiOnline,
        refreshKey,
        triggerRefresh,
        productsCache,
        suppliersCache,
        reloadGlobalData: loadGlobalData,
        loadingInitial,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) {
    throw new Error('useApp must be used within an AppProvider')
  }
  return ctx
}
