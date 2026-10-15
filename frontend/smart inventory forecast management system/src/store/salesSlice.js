import { createSlice, createAsyncThunk, createSelector } from '@reduxjs/toolkit'
import { api } from '../api'
import { fetchProducts } from './productsSlice'
import { showToast } from './uiSlice'

export const fetchSales = createAsyncThunk(
  'sales/fetchSales',
  async (_, { rejectWithValue }) => {
    try {
      const data = await api.getSales()
      return data || []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const recordSale = createAsyncThunk(
  'sales/recordSale',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.createSale(payload)
      dispatch(showToast('Sale Recorded', `Successfully recorded sale. Revenue: ₹${Number(res.data.revenue).toFixed(2)}`, 'success'))
      dispatch(fetchSales())
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
