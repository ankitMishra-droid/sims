import { createSlice } from '@reduxjs/toolkit'
import { SUPPORTED_LANGUAGE_CODES } from '../i18n/translations.js'

export const getInitialTheme = () => {
  if (typeof window !== 'undefined') {
    const saved =
      localStorage.getItem('stocksangati_theme') ||
      localStorage.getItem('sims_theme')
    if (saved === 'light' || saved === 'dark') return saved
  }
  return 'light'
}

export const getInitialSidebarCollapsed = () => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('stocksangati_sidebar_collapsed')
    if (saved === 'true') return true
    if (saved === 'false') return false
  }
  return false
}

const getInitialLanguage = () => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('stocksangati_lang')
    if (saved && SUPPORTED_LANGUAGE_CODES.includes(saved)) return saved
  }
  return 'en'
}

export function findActiveNavGroupId(groups = [], pathname = '') {
  const path = String(pathname || '').trim()
  if (!path) return null
  let bestGroupId = null
  let bestMatchLength = -1

  for (const group of groups) {
    for (const item of group.items || []) {
      const target = String(item.path || '')
      if (!target) continue
      const exactMatch = path === target
      const prefixMatch = !item.end && path.startsWith(`${target}/`)
      if (exactMatch || prefixMatch) {
        const score = exactMatch ? target.length + 1000 : target.length
        if (score > bestMatchLength) {
          bestMatchLength = score
          bestGroupId = group.id
        }
      }
    }
  }
  return bestGroupId
}

export const DEFAULT_TOAST_DURATION_MS = 5000
export const MAX_VISIBLE_TOASTS = 5
const VALID_TOAST_TYPES = new Set(['success', 'error', 'warning', 'info'])
let _toastSequence = 0

export const createToastId = () => `toast-${Date.now()}-${++_toastSequence}`

export function normalizeToastPayload(payload) {
  if (!payload || typeof payload !== 'object') return null
  const rawType = String(payload.type || 'info').trim().toLowerCase()
  const type = VALID_TOAST_TYPES.has(rawType) ? rawType : 'info'
  const title = payload.title != null ? String(payload.title).trim() : ''
  const message = payload.message != null ? String(payload.message).trim() : ''
  if (!title && !message) return null

  const persistent = Boolean(payload.persistent)
  const rawDuration = payload.duration
  const parsedDuration =
    rawDuration === null || rawDuration === undefined || rawDuration === ''
      ? DEFAULT_TOAST_DURATION_MS
      : Number(rawDuration)
  const duration = persistent
    ? null
    : Number.isFinite(parsedDuration) && parsedDuration > 0
    ? parsedDuration
    : DEFAULT_TOAST_DURATION_MS

  const rawId = payload.id != null ? String(payload.id).trim() : ''
  return {
    id: rawId || createToastId(),
    title,
    message,
    type,
    duration,
    persistent,
  }
}

export function createToastTimerController({
  onExpire,
  defaultDuration = DEFAULT_TOAST_DURATION_MS,
  setTimeoutFn = (...args) => globalThis.setTimeout(...args),
  clearTimeoutFn = (...args) => globalThis.clearTimeout(...args),
  nowFn = () => Date.now(),
} = {}) {
  const timers = new Map()

  const start = (id, remaining) => {
    const existing = timers.get(id)
    if (existing?.timeoutId !== null && existing?.timeoutId !== undefined) {
      clearTimeoutFn(existing.timeoutId)
    }
    const parsedRemaining = Number(remaining)
    const delay = Number.isFinite(parsedRemaining) && parsedRemaining >= 0 ? parsedRemaining : defaultDuration
    const entry = {
      timeoutId: null,
      startedAt: nowFn(),
      remaining: delay,
    }
    entry.timeoutId = setTimeoutFn(() => {
      timers.delete(id)
      onExpire?.(id)
    }, delay)
    timers.set(id, entry)
  }

  const clear = (id) => {
    const entry = timers.get(id)
    if (!entry) return
    if (entry.timeoutId !== null && entry.timeoutId !== undefined) {
      clearTimeoutFn(entry.timeoutId)
    }
    timers.delete(id)
  }

  const clearAll = () => {
    for (const id of [...timers.keys()]) {
      clear(id)
    }
  }

  const sync = (toasts = []) => {
    const activeIds = new Set(toasts.map((toast) => toast.id))
    for (const id of [...timers.keys()]) {
      if (!activeIds.has(id)) {
        clear(id)
      }
    }
    for (const toast of toasts) {
      if (toast.persistent) {
        clear(toast.id)
        continue
      }
      const duration = toast.duration ?? defaultDuration
      if (!Number.isFinite(duration) || duration <= 0) continue
      if (!timers.has(toast.id)) {
        start(toast.id, duration)
      }
    }
  }

  const pause = (id) => {
    const entry = timers.get(id)
    if (!entry || entry.timeoutId === null) return
    clearTimeoutFn(entry.timeoutId)
    entry.remaining = Math.max(0, entry.remaining - Math.max(0, nowFn() - entry.startedAt))
    entry.timeoutId = null
  }

  const resume = (id) => {
    const entry = timers.get(id)
    if (!entry || entry.timeoutId !== null) return
    start(id, entry.remaining)
  }

  return {
    sync,
    pause,
    resume,
    clear,
    clearAll,
    has: (id) => timers.has(id),
    size: () => timers.size,
  }
}

const initialState = {
  toasts: [],
  commandPaletteOpen: false,
  theme: getInitialTheme(),
  language: getInitialLanguage(),
  mobileSidebarOpen: false,
  sidebarCollapsed: getInitialSidebarCollapsed(),
  expandedNavGroup: null,
  alertsUnreadCount: 0,
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    addToast: (state, action) => {
      const normalized = normalizeToastPayload(action.payload)
      if (!normalized) return
      const duplicateIsVisible = state.toasts.some(
        (toast) =>
          toast.id === normalized.id ||
          (toast.type === normalized.type &&
            (toast.title || '') === normalized.title &&
            (toast.message || '') === normalized.message)
      )
      if (duplicateIsVisible) return
      if (state.toasts.length >= MAX_VISIBLE_TOASTS) {
        const dropIdx = state.toasts.findIndex((t) => !t.persistent)
        state.toasts.splice(dropIdx >= 0 ? dropIdx : 0, 1)
      }
      state.toasts.push(normalized)
    },
    removeToast: (state, action) => {
      state.toasts = state.toasts.filter((t) => t.id !== action.payload)
    },
    clearToasts: (state) => {
      state.toasts = []
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
    toggleSidebarCollapsed: (state) => {
      state.sidebarCollapsed = !state.sidebarCollapsed
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_sidebar_collapsed', String(state.sidebarCollapsed))
      }
    },
    setSidebarCollapsed: (state, action) => {
      state.sidebarCollapsed = Boolean(action.payload)
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_sidebar_collapsed', String(state.sidebarCollapsed))
      }
    },
    setExpandedNavGroup: (state, action) => {
      state.expandedNavGroup = action.payload || null
    },
    toggleNavGroup: (state, action) => {
      state.expandedNavGroup =
        state.expandedNavGroup === action.payload ? null : action.payload
    },
    setAlertsUnreadCount: (state, action) => {
      const parsed = Number(action.payload)
      state.alertsUnreadCount = Number.isFinite(parsed) && parsed > 0 ? parsed : 0
    },
    toggleTheme: (state) => {
      state.theme = state.theme === 'dark' ? 'light' : 'dark'
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_theme', state.theme)
      }
      if (typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.setAttribute('data-theme', state.theme)
      }
    },
    setTheme: (state, action) => {
      state.theme = action.payload === 'dark' ? 'dark' : 'light'
      if (typeof window !== 'undefined') {
        localStorage.setItem('stocksangati_theme', state.theme)
      }
      if (typeof document !== 'undefined' && document.documentElement) {
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
  clearToasts,
  setCommandPaletteOpen,
  toggleCommandPalette,
  setMobileSidebarOpen,
  toggleMobileSidebar,
  toggleSidebarCollapsed,
  setSidebarCollapsed,
  setExpandedNavGroup,
  toggleNavGroup,
  setAlertsUnreadCount,
  toggleTheme,
  setTheme,
  setLanguage,
} = uiSlice.actions

export const showToast = (title, message, type = 'info', options = {}) => (dispatch) => {
  dispatch(addToast({ id: createToastId(), title, message, type, ...options }))
}

export default uiSlice.reducer
