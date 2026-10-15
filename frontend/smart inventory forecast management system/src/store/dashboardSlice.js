import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { api } from '../api'

export const fetchDashboardMetrics = createAsyncThunk(
  'dashboard/fetchDashboardMetrics',
  async (_, { rejectWithValue }) => {
    try {
      const [summary, poMetrics, movementMetrics, salesMetrics, supplierMetrics] =
        await Promise.all([
          api.getDashboardSummary(),
          api.getPurchaseOrderMetrics(),
          api.getInventoryMovementMetrics(),
          api.getSalesMetrics(),
          api.getSupplierMetrics(),
        ])

      return {
        summary,
        poMetrics,
        movementMetrics,
        salesMetrics,
        supplierMetrics,
      }
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const dashboardSlice = createSlice({
  name: 'dashboard',
  initialState: {
    metrics: null,
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchDashboardMetrics.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchDashboardMetrics.fulfilled, (state, action) => {
        state.loading = false
        state.metrics = action.payload
      })
      .addCase(fetchDashboardMetrics.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

export const selectDashboardMetrics = (state) => state.dashboard.metrics
export const selectDashboardLoading = (state) => state.dashboard.loading

export default dashboardSlice.reducer
