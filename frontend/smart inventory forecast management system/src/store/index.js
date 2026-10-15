import { configureStore } from '@reduxjs/toolkit'
import uiReducer from './uiSlice'
import productsReducer from './productsSlice'
import salesReducer from './salesSlice'
import suppliersReducer from './suppliersSlice'
import purchaseOrdersReducer from './purchaseOrdersSlice'
import inventoryReducer from './inventorySlice'
import dashboardReducer from './dashboardSlice'

export const store = configureStore({
  reducer: {
    ui: uiReducer,
    products: productsReducer,
    sales: salesReducer,
    suppliers: suppliersReducer,
    purchaseOrders: purchaseOrdersReducer,
    inventory: inventoryReducer,
    dashboard: dashboardReducer,
  },
})
