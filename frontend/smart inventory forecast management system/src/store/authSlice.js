import { createSlice } from '@reduxjs/toolkit'

const getStoredItem = (key) => {
  try {
    return localStorage.getItem(key) || null
  } catch {
    return null
  }
}

const getStoredJson = (key) => {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const initialToken = getStoredItem('stocksangati_token')
const initialRefreshToken = getStoredItem('stocksangati_refresh_token')
const initialUser = getStoredJson('stocksangati_user')

const initialState = {
  token: initialToken,
  refreshToken: initialRefreshToken,
  user: initialUser,
  workspaces: [],
  workspacesLoaded: false,
  currentWorkspace: null, // { business, role, permissions, is_active_workspace }
  onboardingProgress: null,
  isAuthenticated: !!initialToken,
  loading: false,
  error: null,
}

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setLoading: (state, action) => {
      state.loading = action.payload
      state.error = null
    },
    setError: (state, action) => {
      state.error = action.payload
      state.loading = false
    },
    setCredentials: (state, action) => {
      const { token, refreshToken, user } = action.payload
      state.token = token
      if (refreshToken !== undefined) state.refreshToken = refreshToken
      if (user !== undefined) state.user = user
      state.isAuthenticated = !!token
      state.loading = false
      state.error = null
      try {
        if (token) localStorage.setItem('stocksangati_token', token)
        if (refreshToken) localStorage.setItem('stocksangati_refresh_token', refreshToken)
        if (user) localStorage.setItem('stocksangati_user', JSON.stringify(user))
      } catch (e) {
        console.error('Failed to store auth session', e)
      }
    },
    updateUserProfile: (state, action) => {
      state.user = action.payload
      try {
        localStorage.setItem('stocksangati_user', JSON.stringify(action.payload))
      } catch {
        // ignore storage failures
      }
    },
    setWorkspaces: (state, action) => {
      state.workspaces = Array.isArray(action.payload) ? action.payload : []
      state.workspacesLoaded = true
      const active =
        state.workspaces.find((w) => w.is_active_workspace) ||
        (state.user?.active_business_id
          ? state.workspaces.find((w) => w.business?.id === state.user.active_business_id)
          : null) ||
        null
      state.currentWorkspace = active
    },
    setCurrentWorkspace: (state, action) => {
      state.currentWorkspace = action.payload
      if (action.payload?.business?.id) {
        const bid = action.payload.business.id
        const idx = state.workspaces.findIndex((w) => w.business?.id === bid)
        if (idx >= 0) {
          state.workspaces = state.workspaces.map((w, i) =>
            i === idx ? { ...action.payload, is_active_workspace: true } : { ...w, is_active_workspace: false }
          )
        } else {
          state.workspaces = [
            ...state.workspaces.map((w) => ({ ...w, is_active_workspace: false })),
            { ...action.payload, is_active_workspace: true },
          ]
        }
      }
      state.workspacesLoaded = true
    },
    setOnboardingProgress: (state, action) => {
      state.onboardingProgress = action.payload
      if (action.payload?.is_completed && state.currentWorkspace?.business) {
        state.currentWorkspace = {
          ...state.currentWorkspace,
          business: { ...state.currentWorkspace.business, onboarding_completed: true },
        }
        const bid = state.currentWorkspace.business.id
        state.workspaces = state.workspaces.map((w) =>
          w.business?.id === bid
            ? { ...w, business: { ...w.business, onboarding_completed: true } }
            : w
        )
      }
    },
    switchWorkspaceReset: (state, action) => {
      const { token, refreshToken, user, workspace } = action.payload
      if (token) state.token = token
      if (refreshToken) state.refreshToken = refreshToken
      if (user) state.user = user
      if (workspace) {
        state.currentWorkspace = workspace
        const bid = workspace.business?.id
        if (bid) {
          const exists = state.workspaces.some((w) => w.business?.id === bid)
          if (exists) {
            state.workspaces = state.workspaces.map((w) =>
              w.business?.id === bid ? { ...workspace, is_active_workspace: true } : { ...w, is_active_workspace: false }
            )
          } else {
            state.workspaces = [
              ...state.workspaces.map((w) => ({ ...w, is_active_workspace: false })),
              { ...workspace, is_active_workspace: true },
            ]
          }
        }
      }
      state.workspacesLoaded = true
      state.onboardingProgress = null
      try {
        if (token) localStorage.setItem('stocksangati_token', token)
        if (refreshToken) localStorage.setItem('stocksangati_refresh_token', refreshToken)
        if (user) localStorage.setItem('stocksangati_user', JSON.stringify(user))
      } catch {
        // ignore storage failures
      }
    },
    logout: (state) => {
      state.token = null
      state.refreshToken = null
      state.user = null
      state.workspaces = []
      state.workspacesLoaded = false
      state.currentWorkspace = null
      state.onboardingProgress = null
      state.isAuthenticated = false
      state.loading = false
      state.error = null
      try {
        localStorage.removeItem('stocksangati_token')
        localStorage.removeItem('stocksangati_refresh_token')
        localStorage.removeItem('stocksangati_user')
      } catch (e) {
        console.error('Failed to clear auth session', e)
      }
    },
  },
})

export const {
  setLoading,
  setError,
  setCredentials,
  updateUserProfile,
  setWorkspaces,
  setCurrentWorkspace,
  setOnboardingProgress,
  switchWorkspaceReset,
  logout,
} = authSlice.actions

export default authSlice.reducer
