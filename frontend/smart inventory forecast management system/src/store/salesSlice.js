import { createSlice, createAsyncThunk, createSelector } from '@reduxjs/toolkit'
import { api } from '../api.js'
import { fetchProducts } from './productsSlice.js'
import { showToast } from './uiSlice.js'

export const fetchSales = createAsyncThunk(
  'sales/fetchSales',
  async (params = { limit: 100 }, { rejectWithValue }) => {
    try {
      const data = await api.getSales(params)
      return data || []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const recordSale = createAsyncThunk(
  'sales/recordSale',
  async (arg, { dispatch, rejectWithValue }) => {
    try {
      const actualPayload = arg?.payload || arg
      const idempotencyKey = arg?.idempotencyKey || null
      const res = await api.createSale(actualPayload, idempotencyKey)
      dispatch(showToast('Sale Recorded', `Successfully recorded sale. Revenue: ₹${Number(res.data.revenue).toFixed(2)}`, 'success'))
      dispatch(fetchSales({ limit: 100 }))
      dispatch(fetchProducts())
      return res.data
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const salesSlice = createSlice({
  name: 'sales',
  initialState: {
    items: [],
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchSales.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchSales.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload
      })
      .addCase(fetchSales.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

// Memoized Selectors
export const selectAllSales = (state) => state.sales.items
export const selectSalesLoading = (state) => state.sales.loading
export const selectSalesError = (state) => state.sales.error

export const selectSalesSummary = createSelector(
  [selectAllSales],
  (sales) => {
    const totalRevenue = sales.reduce((acc, s) => acc + (Number(s.revenue) || 0), 0)
    const totalUnits = sales.reduce((acc, s) => acc + (Number(s.quantity_sold) || 0), 0)
    return {
      count: sales.length,
      totalRevenue,
      totalUnits,
    }
  }
)

export default salesSlice.reducer
