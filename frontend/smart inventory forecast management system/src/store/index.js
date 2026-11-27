import { combineReducers, configureStore } from '@reduxjs/toolkit'
import uiReducer from './uiSlice.js'
import authReducer from './authSlice.js'
import productsReducer from './productsSlice.js'
import salesReducer from './salesSlice.js'
import suppliersReducer from './suppliersSlice.js'
import purchaseOrdersReducer from './purchaseOrdersSlice.js'
import inventoryReducer from './inventorySlice.js'
import dashboardReducer from './dashboardSlice.js'

const appReducer = combineReducers({
  ui: uiReducer,
  auth: authReducer,
  products: productsReducer,
  sales: salesReducer,
  suppliers: suppliersReducer,
  purchaseOrders: purchaseOrdersReducer,
  inventory: inventoryReducer,
  dashboard: dashboardReducer,
})

const rootReducer = (state, action) => {
  // Clear tenant-scoped data caches on logout or workspace switch
  if (action.type === 'auth/logout') {
    state = { ui: state?.ui }
  } else if (action.type === 'auth/switchWorkspaceReset') {
    state = { ui: state?.ui, auth: state?.auth }
  }
  return appReducer(state, action)
}

export const store = configureStore({
  reducer: rootReducer,
})
