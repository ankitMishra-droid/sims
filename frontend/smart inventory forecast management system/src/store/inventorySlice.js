import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { api } from '../api.js'
import { fetchProducts } from './productsSlice.js'
import { showToast } from './uiSlice.js'

export const fetchInventoryLogs = createAsyncThunk(
  'inventory/fetchInventoryLogs',
  async (productId, { rejectWithValue }) => {
    try {
      const data = await api.getInventoryLogs(productId)
      return { productId, logs: data || [] }
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const fetchInventoryPositions = createAsyncThunk(
  'inventory/fetchInventoryPositions',
  async (_, { rejectWithValue }) => {
    try {
      const data = await api.getInventoryPositions()
      return data || []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const adjustProductStock = createAsyncThunk(
  'inventory/adjustProductStock',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.adjustStock(payload)
      dispatch(
        showToast(
          'Stock Adjusted',
          `Updated stock from ${res.previous_stock} to ${res.current_stock}.`,
          'success'
        )
      )
      dispatch(fetchInventoryPositions())
      dispatch(fetchProducts())
      dispatch(fetchInventoryLogs(payload.product_id))
      return res
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const inventorySlice = createSlice({
  name: 'inventory',
  initialState: {
    logsByProduct: {},
    positions: [],
    loading: false,
    positionsLoading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchInventoryLogs.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchInventoryLogs.fulfilled, (state, action) => {
        state.loading = false
        state.logsByProduct[action.payload.productId] = action.payload.logs
      })
      .addCase(fetchInventoryLogs.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
      .addCase(fetchInventoryPositions.pending, (state) => {
        state.positionsLoading = true
        state.error = null
      })
      .addCase(fetchInventoryPositions.fulfilled, (state, action) => {
        state.positionsLoading = false
        state.positions = action.payload
      })
      .addCase(fetchInventoryPositions.rejected, (state, action) => {
        state.positionsLoading = false
        state.error = action.payload
      })
  },
})

export const selectLogsForProduct = (productId) => (state) =>
  state.inventory.logsByProduct[productId] || []
export const selectInventoryPositions = (state) => state.inventory.positions
export const selectInventoryPositionsLoading = (state) => state.inventory.positionsLoading

export default inventorySlice.reducer
