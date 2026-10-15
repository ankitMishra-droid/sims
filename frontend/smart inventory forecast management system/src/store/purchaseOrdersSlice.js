import { createSlice, createAsyncThunk, createSelector } from '@reduxjs/toolkit'
import { api } from '../api'
import { fetchProducts } from './productsSlice'
import { showToast } from './uiSlice'

export const fetchPurchaseOrders = createAsyncThunk(
  'purchaseOrders/fetchPurchaseOrders',
  async (_, { rejectWithValue }) => {
    try {
      const data = await api.getPurchaseOrders()
      return Array.isArray(data) ? data : []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const createPurchaseOrder = createAsyncThunk(
  'purchaseOrders/createPurchaseOrder',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.createPurchaseOrder(payload)
      dispatch(showToast('PO Created', `PO #${res.id} created in DRAFT status.`, 'success'))
      dispatch(fetchPurchaseOrders())
      return res
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const cancelPurchaseOrder = createAsyncThunk(
  'purchaseOrders/cancelPurchaseOrder',
  async (orderId, { dispatch, rejectWithValue }) => {
    try {
      await api.cancelPurchaseOrder(orderId)
      dispatch(showToast('Order Cancelled', `PO #${orderId} marked as CANCELLED.`, 'info'))
      dispatch(fetchPurchaseOrders())
      return orderId
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const receivePurchaseOrder = createAsyncThunk(
  'purchaseOrders/receivePurchaseOrder',
  async (orderId, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.receivePurchaseOrder(orderId)
      dispatch(showToast('Order Received', `All items in PO #${orderId} received & stock updated.`, 'success'))
      dispatch(fetchPurchaseOrders())
      dispatch(fetchProducts())
      return res
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const partiallyReceivePOItem = createAsyncThunk(
  'purchaseOrders/partiallyReceivePOItem',
  async ({ orderId, payload }, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.partiallyReceivePurchaseOrder(orderId, payload)
      dispatch(showToast('Item Received', `Checked in ${payload.received_quantity} units. Stock increased.`, 'success'))
      dispatch(fetchPurchaseOrders())
      dispatch(fetchProducts())
      return res
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const purchaseOrdersSlice = createSlice({
  name: 'purchaseOrders',
  initialState: {
    items: [],
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchPurchaseOrders.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchPurchaseOrders.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload
      })
      .addCase(fetchPurchaseOrders.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

export const selectAllPurchaseOrders = (state) => state.purchaseOrders.items
export const selectPurchaseOrdersLoading = (state) => state.purchaseOrders.loading
export const selectPurchaseOrdersError = (state) => state.purchaseOrders.error

export const selectPendingPurchaseOrders = createSelector(
  [selectAllPurchaseOrders],
  (orders) => orders.filter((o) => ['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(o.status))
)

export default purchaseOrdersSlice.reducer
