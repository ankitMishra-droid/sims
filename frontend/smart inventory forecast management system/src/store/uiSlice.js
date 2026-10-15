import { createSlice } from '@reduxjs/toolkit'

const getInitialTheme = () => {
  if (typeof window !== 'undefined') {
    const saved =
      localStorage.getItem('stocksangati_theme') ||
      localStorage.getItem('sims_theme')
    if (saved) return saved
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark'
    }
  }
  return 'light'
}

const initialState = {
  toasts: [],
  commandPaletteOpen: false,
  theme: getInitialTheme(),
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    addToast: (state, action) => {
      const { title, message, type = 'info', id = Date.now().toString() } = action.payload
      state.toasts.push({ id, title, message, type })
    },
    removeToast: (state, action) => {
      state.toasts = state.toasts.filter((t) => t.id !== action.payload)
    },
    setCommandPaletteOpen: (state, action) => {
      state.commandPaletteOpen = action.payload
    },
    toggleCommandPalette: (state) => {
      state.commandPaletteOpen = !state.commandPaletteOpen
    },
    toggleTheme: (state) => {
      state.theme = state.theme === 'dark' ? 'light' : 'dark'
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_theme', state.theme)
        document.documentElement.setAttribute('data-theme', state.theme)
      }
    },
    setTheme: (state, action) => {
      state.theme = action.payload
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_theme', state.theme)
        document.documentElement.setAttribute('data-theme', state.theme)
      }
    },
  },
})

export const {
  addToast,
  removeToast,
  setCommandPaletteOpen,
  toggleCommandPalette,
  toggleTheme,
  setTheme,
} = uiSlice.actions

export const showToast = (title, message, type = 'info') => (dispatch) => {
  const id = Date.now().toString() + Math.random().toString(36).substr(2, 4)
  dispatch(addToast({ id, title, message, type }))
  setTimeout(() => {
    dispatch(removeToast(id))
  }, 4000)
}

export default uiSlice.reducer
