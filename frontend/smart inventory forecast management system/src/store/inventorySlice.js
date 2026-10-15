import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { api } from '../api'

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

const inventorySlice = createSlice({
  name: 'inventory',
  initialState: {
    logsByProduct: {},
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchInventoryLogs.pending, (state) => {
        state.loading = true
      })
      .addCase(fetchInventoryLogs.fulfilled, (state, action) => {
        state.loading = false
        state.logsByProduct[action.payload.productId] = action.payload.logs
      })
      .addCase(fetchInventoryLogs.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

export const selectLogsForProduct = (productId) => (state) =>
  state.inventory.logsByProduct[productId] || []

export default inventorySlice.reducer
