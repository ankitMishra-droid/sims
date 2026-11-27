import { createSlice } from '@reduxjs/toolkit'
import { SUPPORTED_LANGUAGE_CODES } from '../i18n/translations.js'

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

const getInitialLanguage = () => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('stocksangati_lang')
    if (saved && SUPPORTED_LANGUAGE_CODES.includes(saved)) return saved
  }
  return 'en'
}

const initialState = {
  toasts: [],
  commandPaletteOpen: false,
  theme: getInitialTheme(),
  language: getInitialLanguage(),
  mobileSidebarOpen: false,
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    addToast: (state, action) => {
      const {
        title,
        message,
        type = 'info',
        id = Date.now().toString() + Math.random().toString(36).slice(2, 6),
      } = action.payload
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
    setMobileSidebarOpen: (state, action) => {
      state.mobileSidebarOpen = action.payload
    },
    toggleMobileSidebar: (state) => {
      state.mobileSidebarOpen = !state.mobileSidebarOpen
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
    setLanguage: (state, action) => {
      const code = String(action.payload || 'en').toLowerCase()
      const lang = SUPPORTED_LANGUAGE_CODES.includes(code) ? code : 'en'
      state.language = lang
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_lang', lang)
      }
    },
  },
})

export const {
  addToast,
  removeToast,
  setCommandPaletteOpen,
  toggleCommandPalette,
  setMobileSidebarOpen,
  toggleMobileSidebar,
  toggleTheme,
  setTheme,
  setLanguage,
} = uiSlice.actions

export const showToast = (title, message, type = 'info') => (dispatch) => {
  const id = Date.now().toString() + Math.random().toString(36).slice(2, 6)
  dispatch(addToast({ id, title, message, type }))
  setTimeout(() => {
    dispatch(removeToast(id))
  }, 4000)
}

export default uiSlice.reducer
