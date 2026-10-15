import { createSlice, createAsyncThunk, createSelector } from '@reduxjs/toolkit'
import { api } from '../api'
import { showToast } from './uiSlice'

export const fetchSuppliers = createAsyncThunk(
  'suppliers/fetchSuppliers',
  async (_, { rejectWithValue }) => {
    try {
      const data = await api.getSuppliers()
      return data || []
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const createSupplier = createAsyncThunk(
  'suppliers/createSupplier',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.createSupplier(payload)
      dispatch(showToast('Supplier Added', `${payload.name} created successfully.`, 'success'))
      dispatch(fetchSuppliers())
      return res.data
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const updateSupplier = createAsyncThunk(
  'suppliers/updateSupplier',
  async ({ id, payload }, { dispatch, rejectWithValue }) => {
    try {
      const res = await api.updateSupplier(id, payload)
      dispatch(showToast('Supplier Updated', `${payload.name} updated.`, 'success'))
      dispatch(fetchSuppliers())
      return res.data
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

export const deactivateSupplier = createAsyncThunk(
  'suppliers/deactivateSupplier',
  async (supplier, { dispatch, rejectWithValue }) => {
    try {
      await api.deactivateSupplier(supplier.id)
      dispatch(showToast('Supplier Deactivated', `${supplier.name} deactivated.`, 'info'))
      dispatch(fetchSuppliers())
      return supplier.id
    } catch (err) {
      return rejectWithValue(err.message)
    }
  }
)

const suppliersSlice = createSlice({
  name: 'suppliers',
  initialState: {
    items: [],
    loading: false,
    error: null,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchSuppliers.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchSuppliers.fulfilled, (state, action) => {
        state.loading = false
        state.items = action.payload
      })
      .addCase(fetchSuppliers.rejected, (state, action) => {
        state.loading = false
        state.error = action.payload
      })
  },
})

export const selectAllSuppliers = (state) => state.suppliers.items
export const selectSuppliersLoading = (state) => state.suppliers.loading
export const selectSuppliersError = (state) => state.suppliers.error

export default suppliersSlice.reducer
