import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SUPPORTED_LANGUAGES,
  getLanguageDirection,
  translate,
} from '../src/i18n/translations.js'
import { store } from '../src/store/index.js'
import {
  setCredentials,
  setWorkspaces,
  setCurrentWorkspace,
  setOnboardingProgress,
  switchWorkspaceReset,
  logout,
} from '../src/store/authSlice.js'
import { setLanguage } from '../src/store/uiSlice.js'

// Mock browser globals safely for Node integration tests
function installMockWindow() {
  const storage = new Map()
  const events = []
  globalThis.window = {
    location: { protocol: 'http:', hostname: '127.0.0.1' },
    dispatchEvent: (ev) => events.push(ev),
  }
  globalThis.CustomEvent = class {
    constructor(type) {
      this.type = type
    }
  }
  globalThis.localStorage = {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: (k) => storage.delete(k),
    clear: () => storage.clear(),
  }
  return { storage, events }
}

test('i18n dictionaries provide complete EN and HI coverage with regional fallback and RTL direction', () => {
  assert.equal(SUPPORTED_LANGUAGES.length, 12)
  assert.equal(getLanguageDirection('en'), 'ltr')
  assert.equal(getLanguageDirection('hi'), 'ltr')
  assert.equal(getLanguageDirection('ur'), 'rtl')

  assert.equal(translate('en', 'nav.dashboard'), 'Dashboard')
  assert.notEqual(translate('hi', 'nav.dashboard'), 'Dashboard')
  assert.ok(translate('hi', 'onboarding.steps.1.title').length > 0)
  // Fallback from untranslated regional language to English
  assert.equal(translate('bho', 'nav.products'), 'Products')
})

test('Redux store wipes workspace-specific slices on workspace switch and logout', () => {
  installMockWindow()
  store.dispatch(
    setCredentials({
      token: 'tok-1',
      refreshToken: 'ref-1',
      user: { id: 1, name: 'Ramesh', role: 'owner', active_business_id: 10 },
    })
  )
  store.dispatch(
    setWorkspaces([
      { business: { id: 10, name: 'Store A', business_type: 'retailer' }, role: 'owner', permissions: [], is_active_workspace: true },
      { business: { id: 20, name: 'Depot B', business_type: 'wholesaler' }, role: 'owner', permissions: [], is_active_workspace: false },
    ])
  )
  assert.equal(store.getState().auth.isAuthenticated, true)
  assert.equal(store.getState().auth.currentWorkspace.business.id, 10)

  // Switch workspace -> clears cached state & updates active business
  store.dispatch(
    switchWorkspaceReset({
      token: 'tok-2',
      refreshToken: 'ref-2',
      user: { id: 1, name: 'Ramesh', role: 'owner', active_business_id: 20 },
      workspace: { business: { id: 20, name: 'Depot B', business_type: 'wholesaler' }, role: 'owner', permissions: [], is_active_workspace: true },
    })
  )
  assert.equal(store.getState().auth.token, 'tok-2')
  assert.equal(store.getState().auth.currentWorkspace.business.id, 20)
  assert.deepEqual(store.getState().products.items, [])
  assert.deepEqual(store.getState().sales.items, [])

  // Language persistence handles EN, HI, and regional preference
  store.dispatch(setLanguage('hi'))
  assert.equal(store.getState().ui.language, 'hi')
  assert.equal(globalThis.localStorage.getItem('stocksangati_lang'), 'hi')

  store.dispatch(logout())
  assert.equal(store.getState().auth.isAuthenticated, false)
  assert.equal(store.getState().auth.workspacesLoaded, false)
  assert.equal(store.getState().auth.token, null)
  assert.equal(globalThis.localStorage.getItem('stocksangati_token'), null)
})

test('First-time workspace setup tracks onboarding_completed transition before dashboard access', () => {
  installMockWindow()
  store.dispatch(
    setCredentials({
      token: 'tok-first',
      refreshToken: 'ref-first',
      user: { id: 9, name: 'New Owner', role: 'owner', active_business_id: null },
    })
  )
  store.dispatch(setWorkspaces([]))
  assert.equal(store.getState().auth.workspacesLoaded, true)
  assert.equal(store.getState().auth.currentWorkspace, null)

  // Workspace created -> onboarding_completed starts false
  store.dispatch(
    setCurrentWorkspace({
      business: { id: 55, name: 'First Store', business_type: 'retailer', onboarding_completed: false },
      role: 'owner',
      permissions: ['onboarding.manage'],
      is_active_workspace: true,
    })
  )
  assert.equal(store.getState().auth.currentWorkspace.business.onboarding_completed, false)

  // Step 10 completes onboarding -> currentWorkspace & workspaces update cleanly for dashboard access
  store.dispatch(setOnboardingProgress({ business_id: 55, current_step: 10, is_completed: true }))
  assert.equal(store.getState().auth.currentWorkspace.business.onboarding_completed, true)
  assert.equal(store.getState().auth.workspaces[0].business.onboarding_completed, true)
  store.dispatch(logout())
})

test('API client sends auth/workspace headers and automatically refreshes expired access token', async () => {
  const { storage, events } = installMockWindow()
  storage.set('stocksangati_token', 'expired-access-token')
  storage.set('stocksangati_refresh_token', 'valid-refresh-token')
  storage.set('stocksangati_user', JSON.stringify({ id: 7, active_business_id: 42 }))

  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, headers: init?.headers || {}, body: init?.body })
    if (url.endsWith('/api/products/') && init.headers.Authorization === 'Bearer expired-access-token') {
      return new Response(JSON.stringify({ detail: 'Expired token' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.endsWith('/api/auth/refresh')) {
      return new Response(
        JSON.stringify({
          access_token: 'fresh-access-token',
          refresh_token: 'fresh-refresh-token',
          user: { id: 7, active_business_id: 42 },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      )
    }
    if (url.endsWith('/api/products/') && init.headers.Authorization === 'Bearer fresh-access-token') {
      return new Response(JSON.stringify({ data: [{ id: 1, sku: 'SKU-1' }], total: 1 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({ detail: 'Unexpected call' }), {
      status: 401,
      headers: { 'content-type': 'application/json' },
    })
  }

  const { api } = await import('../src/api.js')
  const products = await api.getProducts()
  assert.equal(products.length, 1)
  assert.equal(products[0].sku, 'SKU-1')
  assert.equal(calls[0].headers['X-Business-Id'], '42')
  assert.equal(storage.get('stocksangati_token'), 'fresh-access-token')
  assert.equal(events.length, 0)

  // Now simulate refresh failure -> emits auth-expired and clears storage
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'Revoked' }), {
      status: 401,
      headers: { 'content-type': 'application/json' },
    })

  await assert.rejects(() => api.getMe())
  assert.equal(storage.get('stocksangati_token'), undefined)
  assert.equal(events.length, 1)
  assert.equal(events[0].type, 'stocksangati:auth-expired')
})

test('Typography design system loads Inter and Noto Sans Devanagari and covers all supported scripts', async () => {
  const fs = await import('node:fs')
  const path = await import('node:path')
  const rootDir = path.resolve(import.meta.dirname, '..')
  const indexHtml = fs.readFileSync(path.join(rootDir, 'index.html'), 'utf8')
  const css = fs.readFileSync(path.join(rootDir, 'src/index.css'), 'utf8')

  // Verify Google Fonts import optimization (Inter + Noto Sans Devanagari + JetBrains Mono, no Plus Jakarta Sans bloat)
  assert.match(indexHtml, /Inter:wght@400;500;600/)
  assert.match(indexHtml, /Noto\+Sans\+Devanagari:wght@400;500;600/)
  assert.doesNotMatch(indexHtml, /Plus\+Jakarta\+Sans/)

  // Verify design tokens and Indic/RTL script rules exist for every supported language
  for (const token of [
    '--font-family-latin',
    '--font-family-devanagari',
    '--font-family-bengali',
    '--font-family-gujarati',
    '--font-family-gurmukhi',
    '--font-family-tamil',
    '--font-family-telugu',
    '--font-family-kannada',
    '--font-family-malayalam',
    '--font-family-urdu',
    '--text-xs',
    '--text-base',
    '--text-2xl',
    '--leading-normal',
    '--font-weight-semibold',
  ]) {
    assert.ok(css.includes(token), `Missing CSS typography token: ${token}`)
  }

  for (const lang of SUPPORTED_LANGUAGES.map((l) => l.code).filter((c) => c !== 'en')) {
    assert.ok(css.includes(`[lang="${lang}"]`), `Missing CSS [lang="${lang}"] font override`)
  }
})
