import { Suspense, lazy, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Provider, useDispatch, useSelector } from 'react-redux'
import { store } from './store'
import { api } from './api'
import { updateUserProfile, setWorkspaces, logout } from './store/authSlice'
import { setLanguage } from './store/uiSlice'
import { getLanguageDirection } from './i18n/translations'

import ToastContainer from './components/ToastContainer'
import CommandPalette from './components/common/CommandPalette'
import ProtectedRoute from './components/layout/ProtectedRoute'
import AppLayout from './components/layout/AppLayout'
import { LoadingState } from './components/common/StateBlocks'

// Public Pages
const LandingPage = lazy(() => import('./pages/LandingPage'))
const LoginPage = lazy(() => import('./pages/auth/LoginPage'))
const RegisterPage = lazy(() => import('./pages/auth/RegisterPage'))
const PasswordResetPage = lazy(() => import('./pages/auth/PasswordResetPage'))

// Overview
const DashboardPage = lazy(() => import('./pages/DashboardPage'))

// Workspaces, Onboarding & Supplier Portal
const WorkspaceSetupPage = lazy(() => import('./pages/workspaces/WorkspaceSetupPage'))
const OnboardingWizardPage = lazy(() => import('./pages/onboarding/OnboardingWizardPage'))
const SupplierPortalPage = lazy(() => import('./pages/supplier/SupplierPortalPage'))

// Inventory
const ProductsPage = lazy(() => import('./pages/ProductsPage'))
const StockManagementPage = lazy(() => import('./pages/StockManagementPage'))
const StockHistoryPage = lazy(() => import('./pages/StockHistoryPage'))
const StockAdjustmentsPage = lazy(() => import('./pages/StockAdjustmentsPage'))

// Sales
const RecordSalePage = lazy(() => import('./pages/RecordSalePage'))
const SalesHistoryPage = lazy(() => import('./pages/SalesHistoryPage'))

// Procurement
const SuppliersPage = lazy(() => import('./pages/SuppliersPage'))
const PurchaseOrdersPage = lazy(() => import('./pages/PurchaseOrdersPage'))
const ReceiveOrderPage = lazy(() => import('./pages/ReceiveOrderPage'))

// Intelligence
const ReorderPlannerPage = lazy(() => import('./pages/ReorderPlannerPage'))
const ForecastingPage = lazy(() => import('./pages/ForecastingPage'))
const WhatIfSimulatorPage = lazy(() => import('./pages/WhatIfSimulatorPage'))
const StockAlertsPage = lazy(() => import('./pages/StockAlertsPage'))

// Reports
const InventoryReportsPage = lazy(() => import('./pages/InventoryReportsPage'))
const SalesReportsPage = lazy(() => import('./pages/SalesReportsPage'))
const ProcurementReportsPage = lazy(() => import('./pages/ProcurementReportsPage'))

// Settings
const BusinessSettingsPage = lazy(() => import('./pages/settings/BusinessSettingsPage'))
const TeamMembersPage = lazy(() => import('./pages/settings/TeamMembersPage'))
const SecuritySettingsPage = lazy(() => import('./pages/auth/SecuritySettingsPage'))
const LanguageSettingsPage = lazy(() => import('./pages/LanguageSettingsPage'))

function AppContent() {
  const dispatch = useDispatch()
  const theme = useSelector((state) => state.ui.theme)
  const language = useSelector((state) => state.ui.language)
  const isAuthenticated = useSelector((state) => state.auth.isAuthenticated)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.setAttribute('lang', language || 'en')
    document.documentElement.setAttribute('dir', getLanguageDirection(language))
  }, [language])

  useEffect(() => {
    const handleExpired = () => {
      dispatch(logout())
    }
    window.addEventListener('stocksangati:auth-expired', handleExpired)
    return () => window.removeEventListener('stocksangati:auth-expired', handleExpired)
  }, [dispatch])

  useEffect(() => {
    if (!isAuthenticated) return
    let active = true
    const hydrate = async () => {
      try {
        const [me, wsList] = await Promise.all([api.getMe(), api.getWorkspaces()])
        if (!active) return
        dispatch(updateUserProfile(me))
        dispatch(setWorkspaces(wsList))
        if (me?.preferred_language) {
          dispatch(setLanguage(me.preferred_language))
        }
      } catch (err) {
        if (!active) return
        if (err.status === 401) {
          dispatch(logout())
        } else {
          dispatch(setWorkspaces([]))
        }
      }
    }
    hydrate()
    return () => {
      active = false
    }
  }, [isAuthenticated, dispatch])

  return (
    <BrowserRouter>
      <Suspense
        fallback={
          <div style={{ padding: '2rem', maxWidth: '720px', margin: '2rem auto' }}>
            <LoadingState message="Loading module..." />
          </div>
        }
      >
        <Routes>
          {/* Public Routes */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/reset-password" element={<PasswordResetPage />} />

          {/* Authenticated App Shell */}
          <Route
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            {/* Overview & Onboarding */}
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/workspaces" element={<WorkspaceSetupPage />} />
            <Route path="/onboarding" element={<OnboardingWizardPage />} />
            <Route path="/supplier-portal" element={<SupplierPortalPage />} />

            {/* Inventory */}
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/inventory" element={<StockManagementPage />} />
            <Route path="/inventory/history" element={<StockHistoryPage />} />
            <Route path="/inventory/adjustments" element={<StockAdjustmentsPage />} />

            {/* Sales */}
            <Route path="/sales/new" element={<RecordSalePage />} />
            <Route path="/sales" element={<SalesHistoryPage />} />

            {/* Procurement */}
            <Route path="/suppliers" element={<SuppliersPage />} />
            <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
            <Route path="/receive-order" element={<ReceiveOrderPage />} />

            {/* Intelligence */}
            <Route path="/reorder-planner" element={<ReorderPlannerPage />} />
            <Route path="/forecasting" element={<ForecastingPage />} />
            <Route path="/simulator" element={<WhatIfSimulatorPage />} />
            <Route path="/stock-alerts" element={<StockAlertsPage />} />

            {/* Reports */}
            <Route path="/reports/inventory" element={<InventoryReportsPage />} />
            <Route path="/reports/sales" element={<SalesReportsPage />} />
            <Route path="/reports/procurement" element={<ProcurementReportsPage />} />

            {/* Settings */}
            <Route path="/settings/business" element={<BusinessSettingsPage />} />
            <Route path="/settings/team" element={<TeamMembersPage />} />
            <Route path="/settings/security" element={<SecuritySettingsPage />} />
            <Route path="/settings/language" element={<LanguageSettingsPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>

      <ToastContainer />
      <CommandPalette />
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
