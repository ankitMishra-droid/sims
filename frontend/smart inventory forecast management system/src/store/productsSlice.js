import { createSlice, createAsyncThunk, createSelector } from '@reduxjs/toolkit'
import { api } from '../api'
import { showToast } from './uiSlice'

export const fetchProducts = createAsyncThunk(
  'products/fetchProducts',
  async (_, { rejectWithValue }) => {
    try {
      const data = await api.getProducts()
      return data || []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const createProduct = createAsyncThunk(
  'products/createProduct',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.createProduct(payload)
      dispatch(showToast('Product Created', `${payload.name} added to catalog.`, 'success'))
      dispatch(fetchProducts())
      return res.data
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const updateProduct = createAsyncThunk(
  'products/updateProduct',
  async ({ id, payload }, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.updateProduct(id, payload)
      dispatch(showToast('Product Updated', `${payload.name} updated successfully.`, 'success'))
      dispatch(fetchProducts())
      return res.data
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const toggleProductActive = createAsyncThunk(
  'products/toggleProductActive',
  async (product, { dispatch, rejectWithValue }) => {
    try {
      if (product.is_active) {
        await api.deactivateProduct(product.id)
        dispatch(showToast('Product Deactivated', `${product.sku} deactivated.`, 'info'))
      } else {
        await api.activateProduct(product.id)
        dispatch(showToast('Product Activated', `${product.sku} activated.`, 'success'))
      }
      dispatch(fetchProducts())
      return product.id
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const stockInProduct = createAsyncThunk(
  'products/stockInProduct',
  async ({ product_id, quantity, reason }, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.stockIn({ product_id, quantity, reason })
      dispatch(showToast('Stock Adjusted', `Added ${quantity} units to inventory.`, 'success'))
      dispatch(fetchProducts())
      return res
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const productsSlice = createSlice({
  name: 'products',
  initialState: {
    items: [],
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchProducts.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchProducts.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload
      })
      .addCase(fetchProducts.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

// Memoized Selectors
export const selectAllProducts = (state) => state.products.items
export const selectProductsLoading = (state) => state.products.loading
export const selectProductsError = (state) => state.products.error

export const selectLowStockProducts = createSelector(
  [selectAllProducts],
  (products) => products.filter((p) => p.current_stock <= p.reorder_level)
)

export const selectProductCategories = createSelector(
  [selectAllProducts],
  (products) => {
    const set = new Set()
    products.forEach((p) => {
      if (p.category) set.add(p.category)
    })
    return Array.from(set)
  }
)

export default productsSlice.reducer
