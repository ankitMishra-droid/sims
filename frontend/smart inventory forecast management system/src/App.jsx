import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Provider, useSelector, useDispatch } from 'react-redux'
import { store } from './store'
import { api } from './api'

import Navbar from './components/Navbar'
import ToastContainer from './components/ToastContainer'
import CommandPalette from './components/common/CommandPalette'

// Pages
import LandingPage from './pages/LandingPage'
import ProductsPage from './pages/ProductsPage'
import SalesPage from './pages/SalesPage'
import InventoryPage from './pages/InventoryPage'
import SuppliersPage from './pages/SuppliersPage'
import PurchaseOrdersPage from './pages/PurchaseOrdersPage'
import ReceiveOrderPage from './pages/ReceiveOrderPage'
import DashboardPage from './pages/DashboardPage'

function AppContent() {
  const dispatch = useDispatch()
  const theme = useSelector((state) => state.ui.theme)

  // Sync theme with DOM
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  return (
    <BrowserRouter>
      <div className="app-wrapper">
        {/* Top Navigation */}
        <Navbar />

        {/* Active Screen Content */}
        <main className="main-content">
          <Routes>
            {/* Landing launchpad page when home page opened */}
            <Route path="/" element={<LandingPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/sales" element={<SalesPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/suppliers" element={<SuppliersPage />} />
            <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
            <Route path="/receive-order" element={<ReceiveOrderPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        {/* Global Layer Components */}
        <ToastContainer />
        <CommandPalette />
      </div>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <Provider store={store}>
      <AppContent />
    </Provider>
  )
}
