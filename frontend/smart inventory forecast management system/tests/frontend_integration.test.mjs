import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

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
  const docAttrs = new Map()
  globalThis.window = {
    location: { protocol: 'http:', hostname: '127.0.0.1' },
    dispatchEvent: (ev) => events.push(ev),
  }
  globalThis.document = {
    documentElement: {
      setAttribute: (k, v) => docAttrs.set(k, String(v)),
      getAttribute: (k) => (docAttrs.has(k) ? docAttrs.get(k) : null),
    },
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
  return { storage, events, docAttrs }
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

test('Phase 6 intelligence translations (EN/HI) and confirmed PO API integration work cleanly', async () => {
  assert.equal(translate('en', 'nav.intelligenceOverview'), 'Intelligence Overview')
  assert.notEqual(translate('hi', 'nav.intelligenceOverview'), 'Intelligence Overview')
  for (const key of [
    'intelligence.overviewTitle',
    'intelligence.historicalVsForecast',
    'intelligence.confirmPoTitle',
    'intelligence.whySuggested',
    'intelligence.reviewAndCreatePo',
    'intelligence.draftPoNotice',
  ]) {
    const enVal = translate('en', key)
    const hiVal = translate('hi', key)
    assert.ok(enVal && !enVal.includes('intelligence.'), `Missing EN key ${key}`)
    assert.ok(hiVal && hiVal !== enVal, `Missing HI translation for ${key}`)
  }

  const { storage } = installMockWindow()
  storage.set('stocksangati_token', 'tok-intel')
  storage.set('stocksangati_user', JSON.stringify({ id: 3, active_business_id: 11 }))

  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method || 'GET', body: init?.body ? JSON.parse(init.body) : null })
    if (url.includes('/api/intelligence/overview')) {
      return new Response(JSON.stringify({ status: 'success', data: { reorder_candidates_count: 2 } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/api/intelligence/recommendations/42/convert-to-po')) {
      return new Response(JSON.stringify({ status: 'success', purchase_order_id: 99, order_number: 'PO-0099' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({ status: 'success', data: [] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  const { api } = await import('../src/api.js')
  const ov = await api.getIntelligenceOverview()
  assert.equal(ov.reorder_candidates_count, 2)

  const poRes = await api.convertIntelligenceRecommendationToPo(42, {
    supplier_id: 7,
    ordered_quantity: 24,
    expected_delivery_date: '2026-12-05',
  })
  assert.equal(poRes.order_number, 'PO-0099')
  const poCall = calls.find((c) => c.url.includes('/convert-to-po'))
  assert.equal(poCall.method, 'POST')
  assert.equal(poCall.body.confirmed, true)
  assert.equal(poCall.body.ordered_quantity, 24)
})

test('Phase 8 AI translations (EN/HI), Redux workspace isolation, and multipart/chat API client work cleanly', async () => {
  assert.equal(translate('en', 'nav.aiKnowledge'), 'Knowledge Base (AI)')
  assert.notEqual(translate('hi', 'nav.aiKnowledge'), 'Knowledge Base (AI)')

  for (const key of [
    'ai.assistantTitle',
    'ai.newChat',
    'ai.sourcesTitle',
    'ai.confirmExecute',
    'ai.knowledgeTitle',
    'ai.uploadButton',
    'ai.retryIngest',
    'ai.ocrWarning',
    'ai.starter3',
  ]) {
    const enVal = translate('en', key)
    const hiVal = translate('hi', key)
    assert.ok(enVal && !enVal.startsWith('ai.'), `Missing EN key ${key}`)
    if (key !== 'ai.starter3') {
      assert.ok(hiVal && hiVal !== enVal, `Missing HI translation for ${key}`)
    }
  }

  const { storage } = installMockWindow()
  const {
    setAssistantOpen,
    setAssistantLanguage,
    setChatMessagesFromServer,
    updateMessagePendingAction,
    setDocuments,
  } = await import('../src/store/aiSlice.js')

  store.dispatch(
    setCredentials({
      token: 'tok-ai-1',
      refreshToken: 'ref-ai-1',
      user: { id: 1, name: 'Asha', role: 'admin', active_business_id: 10 },
    })
  )
  store.dispatch(setAssistantOpen(true))
  store.dispatch(setAssistantLanguage('hi'))
  store.dispatch(
    setChatMessagesFromServer({
      conversation: { id: 77, title: 'Low Stock Check' },
      messages: [
        { id: 1, role: 'user', content: 'मेरा स्टॉक कैसा है?' },
        {
          id: 2,
          role: 'assistant',
          content: 'BASMATI-5KG कम है [1].',
          pending_action: { status: 'PENDING_CONFIRMATION', summary: 'Create Draft PO' },
        },
      ],
    })
  )
  store.dispatch(setDocuments([{ id: 5, title: 'Store A SOP', status: 'COMPLETED' }]))
  assert.equal(store.getState().ai.activeConversationId, 77)
  assert.equal(store.getState().ai.messages.length, 2)
  store.dispatch(
    updateMessagePendingAction({
      messageId: 2,
      pendingAction: { status: 'EXECUTED', result: { order_number: 'PO-001' } },
    })
  )
  assert.equal(store.getState().ai.messages[1].pending_action.status, 'EXECUTED')

  // Switching workspace must clear previous business AI conversations & documents
  store.dispatch(
    switchWorkspaceReset({
      token: 'tok-ai-2',
      refreshToken: 'ref-ai-2',
      user: { id: 1, name: 'Asha', role: 'owner', active_business_id: 20 },
      workspace: { business: { id: 20, name: 'Store B', business_type: 'retailer' }, role: 'owner', permissions: [], is_active_workspace: true },
    })
  )
  assert.equal(store.getState().ai.activeConversationId, null)
  assert.deepEqual(store.getState().ai.messages, [])
  assert.deepEqual(store.getState().ai.documents, [])

  // API client check for FormData upload (no JSON content-type) and chat POST
  storage.set('stocksangati_token', 'tok-ai-2')
  storage.set('stocksangati_user', JSON.stringify({ id: 1, active_business_id: 20 }))
  const recorded = []
  globalThis.FormData = class MockFormData {
    constructor() {
      this.fields = []
    }
    append(k, v) {
      this.fields.push([k, v])
    }
  }
  globalThis.fetch = async (url, init) => {
    recorded.push({ url, method: init?.method || 'GET', headers: init?.headers || {}, body: init?.body })
    return new Response(
      JSON.stringify({ document: { id: 9, status: 'PENDING' }, conversation: { id: 88 } }),
      { status: 200, headers: { 'content-type': 'application/json' } }
    )
  }

  const { api } = await import('../src/api.js')
  await api.uploadAiDocument({ name: 'guide.pdf' }, { docCategory: 'manual' })
  const upCall = recorded.find((r) => r.url.includes('/api/ai/documents'))
  assert.equal(upCall.method, 'POST')
  assert.equal(upCall.headers['Content-Type'], undefined)
  assert.equal(upCall.headers['X-Business-Id'], '20')

  await api.sendAiChatMessage({ message: 'Which orders are pending?', preferred_language: 'en' })
  const chatCall = recorded.find((r) => r.url.includes('/api/ai/chat'))
  assert.equal(chatCall.method, 'POST')
  assert.equal(chatCall.headers['Content-Type'], 'application/json')

  // Verify FastAPI structured object error detail unwraps cleanly into errorCode / retryable / conversationId
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: {
          message: 'The AI assistant is temporarily unavailable due to provider quota restrictions.',
          error_code: 'QUOTA_EXHAUSTED',
          retryable: false,
          conversation_id: 91,
        },
      }),
      { status: 429, headers: { 'content-type': 'application/json' } }
    )
  let caughtErr = null
  try {
    await api.sendAiChatMessage({ message: 'Hello' })
  } catch (e) {
    caughtErr = e
  }
  assert.ok(caughtErr)
  assert.equal(caughtErr.status, 429)
  assert.equal(caughtErr.errorCode, 'QUOTA_EXHAUSTED')
  assert.equal(caughtErr.retryable, false)
  assert.equal(caughtErr.conversationId, 91)
  assert.ok(caughtErr.message.includes('quota restrictions'))
  store.dispatch(logout())
})

test('Frontend AI formatting parses structured lists and hides internal non-document source badges', async () => {
  const { filterUserFacingSources, parseMarkdownBlocks } = await import(
    '../src/components/ai/aiFormatting.js'
  )

  const filtered = filterUserFacingSources([
    { source_kind: 'business_tool', title: 'Live Inventory', tool_name: 'get_low_stock_products' },
    { source_kind: 'forecast_intelligence', title: 'Internal Forecast', tool_name: 'get_forecast_summary' },
    { source_kind: 'document', document_id: 14, title: 'Warehouse Receiving SOP', page_number: 2 },
  ])
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].title, 'Warehouse Receiving SOP')

  const sampleReply = `9 products need attention:

1. **Ergotron LX Monitor Arm**
   - Stock available: 19 units
   - Priority: Critical

2. **Crucial Pro 64GB DDR5 RAM Kit**
   - Stock available: 36 units`

  const blocks = parseMarkdownBlocks(sampleReply)
  assert.equal(blocks[0].type, 'p')
  assert.equal(blocks[1].type, 'ol')
  assert.equal(blocks[1].items.length, 2)
  assert.equal(blocks[1].items[0].subBullets.length, 2)
  assert.equal(blocks[1].items[1].subBullets[0], 'Stock available: 36 units')
})

test('Phase 9 AI credit Redux state, idempotency header forwarding & HTTP 402 error parsing', async () => {
  const { store } = await import('../src/store/index.js')
  const { setCreditAccount, setLastTurnCreditInfo, setAssistantError } = await import('../src/store/aiSlice.js')
  const { switchWorkspaceReset } = await import('../src/store/authSlice.js')
  const { api } = await import('../src/api.js')
  const { translate } = await import('../src/i18n/translations.js')

  store.dispatch(setCreditAccount({ available_credits: 42.5, reserved_credits: 0, status: 'ACTIVE', plan_tier: 'pro' }))
  store.dispatch(setLastTurnCreditInfo({ credits_used: 0.145, idempotent_replay: false }))
  assert.equal(store.getState().ai.creditAccount.available_credits, 42.5)
  assert.equal(store.getState().ai.lastTurnCreditInfo.credits_used, 0.145)

  assert.equal(translate('en', 'nav.aiUsage'), 'AI Credits & Usage')
  assert.ok(translate('hi', 'nav.aiUsage').length > 0)

  // Verify idempotency key forwarding & 402 INSUFFICIENT_AI_CREDITS extraction
  const seenCalls = []
  globalThis.fetch = async (url, init) => {
    seenCalls.push({ url, headers: init?.headers || {}, body: init?.body })
    return new Response(
      JSON.stringify({
        detail: {
          message: 'Insufficient AI credits (0.0 available).',
          error_code: 'INSUFFICIENT_AI_CREDITS',
          retryable: false,
        },
      }),
      { status: 402, headers: { 'content-type': 'application/json' } }
    )
  }

  let err402 = null
  try {
    await api.sendAiChatMessage({ message: 'Hi' }, { idempotencyKey: 'idem-ui-99' })
  } catch (err) {
    err402 = err
  }
  assert.ok(err402)
  assert.equal(err402.status, 402)
  assert.equal(err402.errorCode, 'INSUFFICIENT_AI_CREDITS')
  assert.equal(err402.retryable, false)
  assert.equal(seenCalls[0].headers['Idempotency-Key'], 'idem-ui-99')

  store.dispatch(
    setAssistantError({
      message: err402.message,
      errorCode: err402.errorCode,
      retryable: err402.retryable,
    })
  )
  assert.equal(store.getState().ai.errorCode, 'INSUFFICIENT_AI_CREDITS')
  assert.equal(store.getState().ai.errorRetryable, false)

  // Workspace reset clears AI state cleanly
  store.dispatch(
    switchWorkspaceReset({
      token: 'tok-reset',
      refreshToken: 'ref-reset',
      user: { id: 1, name: 'Test', role: 'owner', active_business_id: 99 },
      workspace: { business: { id: 99, name: 'Store Z', business_type: 'retailer' }, role: 'owner', permissions: [], is_active_workspace: true },
    })
  )
  assert.equal(store.getState().ai.activeConversationId, null)
})

test('Phase 10 translations, alert APIs, and CSV import endpoint methods work cleanly', async () => {
  const { translate } = await import('../src/i18n/translations.js')
  const { api } = await import('../src/api.js')
  const { store } = await import('../src/store/index.js')
  const { setCredentials, logout } = await import('../src/store/authSlice.js')

  for (const key of ['common.importCsv', 'common.markAllRead', 'common.dismiss', 'common.restore', 'common.showDismissed']) {
    assert.ok(translate('en', key).length > 0 && translate('en', key) !== key)
    assert.ok(translate('hi', key).length > 0 && translate('hi', key) !== key)
  }

  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method || 'GET', body: init?.body, headers: init?.headers || {} })
    return new Response(JSON.stringify({ alerts: [], unread_count: 0, active_count: 0, dismissed_count: 0 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  store.dispatch(
    setCredentials({
      token: 'tok-p10',
      user: { id: 1, name: 'Test', role: 'owner', active_business_id: 5 },
    })
  )

  await api.getStockAlerts(true)
  assert.ok(calls.some((c) => c.url.includes('/api/inventory/alerts?include_dismissed=true')))

  await api.dismissStockAlert({ alert_key: 'low_stock:9', product_id: 9 })
  const disCall = calls.find((c) => c.url.includes('/api/inventory/alerts/dismiss'))
  assert.equal(disCall.method, 'POST')

  await api.reopenStockAlert('low_stock:9')
  const repCall = calls.find((c) => c.url.includes('/api/inventory/alerts/reopen'))
  assert.equal(repCall.method, 'POST')

  await api.importProductsCsv({ name: 'products.csv' })
  const impCall = calls.find((c) => c.url.includes('/api/products/import-csv'))
  assert.equal(impCall.method, 'POST')
  assert.equal(impCall.headers['Content-Type'], undefined)

  store.dispatch(logout())
})

test('Task 1: toast notifications support success/error/warning/info, dedup, manual dismiss, independent 5s timers, hover pause & cleanup', async () => {
  installMockWindow()
  const { store } = await import('../src/store/index.js')
  const {
    DEFAULT_TOAST_DURATION_MS,
    addToast,
    removeToast,
    clearToasts,
    showToast,
    createToastTimerController,
  } = await import('../src/store/uiSlice.js')

  assert.equal(DEFAULT_TOAST_DURATION_MS, 5000)
  store.dispatch(clearToasts())

  // Dispatch all four notification types
  store.dispatch(showToast('Saved', 'Product saved cleanly.', 'success'))
  store.dispatch(showToast('Failed', 'Could not reach server.', 'error'))
  store.dispatch(addToast({ title: 'Low Stock', message: 'Item SKU-01 below reorder point.', type: 'warning' }))
  store.dispatch(addToast({ title: 'Info', message: 'Sync scheduled.', type: 'info' }))

  let toasts = store.getState().ui.toasts
  assert.equal(toasts.length, 4)
  assert.deepEqual(
    toasts.map((t) => t.type),
    ['success', 'error', 'warning', 'info']
  )
  assert.ok(toasts.every((t) => t.duration === 5000 && t.persistent === false))

  // Deduplicate identical visible notifications (including whitespace/empty payloads)
  store.dispatch(addToast({ title: '  Low Stock  ', message: 'Item SKU-01 below reorder point.', type: 'warning' }))
  store.dispatch(addToast({ title: '   ', message: '   ', type: 'info' }))
  assert.equal(store.getState().ui.toasts.length, 4)

  // Deterministic timer harness to test independent 5s timers, hover pause, manual dismissal & unmount cleanup
  let now = 0
  let nextTimerId = 1
  const scheduled = new Map()
  const setTimeoutFn = (fn, delay) => {
    const id = nextTimerId++
    scheduled.set(id, { id, fireAt: now + delay, fn })
    return id
  }
  const clearTimeoutFn = (id) => {
    scheduled.delete(id)
  }
  const advanceBy = (ms) => {
    const target = now + ms
    while (true) {
      const due = [...scheduled.values()]
        .filter((t) => t.fireAt <= target)
        .sort((a, b) => a.fireAt - b.fireAt)
      if (!due.length) break
      now = due[0].fireAt
      scheduled.delete(due[0].id)
      due[0].fn()
    }
    now = target
  }

  const expiredIds = []
  const ctrl = createToastTimerController({
    onExpire: (id) => {
      expiredIds.push(id)
      store.dispatch(removeToast(id))
    },
    setTimeoutFn,
    clearTimeoutFn,
    nowFn: () => now,
  })

  // Sync first toast at t=0
  const tSuccess = store.getState().ui.toasts[0]
  const tError = store.getState().ui.toasts[1]
  const tWarning = store.getState().ui.toasts[2]
  const tInfo = store.getState().ui.toasts[3]

  ctrl.sync([tSuccess, tError])
  assert.equal(ctrl.size(), 2)
  assert.equal(scheduled.size, 2)

  // Advance 2s, add warning + info -> independent 5s clocks
  advanceBy(2000)
  ctrl.sync([tSuccess, tError, tWarning, tInfo])
  assert.equal(ctrl.size(), 4)
  assert.equal(scheduled.size, 4)

  // Hover-pause error toast at t=2s (remaining=3000ms); repeated pause must not corrupt remaining
  ctrl.pause(tError.id)
  advanceBy(1000)
  ctrl.pause(tError.id)

  // Manual dismissal of info toast at t=3s clears its timer immediately
  store.dispatch(removeToast(tInfo.id))
  ctrl.sync(store.getState().ui.toasts)
  assert.equal(ctrl.has(tInfo.id), false)
  assert.equal(scheduled.size, 2) // success + warning active; error paused; info cleared

  // Advance to t=5s -> only success toast expires; warning stays until t=7s; paused error stays open
  advanceBy(2000)
  assert.deepEqual(expiredIds, [tSuccess.id])
  ctrl.sync(store.getState().ui.toasts)
  assert.deepEqual(
    store.getState().ui.toasts.map((t) => t.id),
    [tError.id, tWarning.id]
  )

  // Resume paused error toast at t=5s -> 3000ms left (expires at t=8s)
  ctrl.resume(tError.id)
  advanceBy(2000) // now t=7s -> warning expires (added at t=2s)
  ctrl.sync(store.getState().ui.toasts)
  assert.deepEqual(expiredIds, [tSuccess.id, tWarning.id])
  assert.deepEqual(
    store.getState().ui.toasts.map((t) => t.id),
    [tError.id]
  )

  // Persistent toast does not schedule an auto-close timer
  store.dispatch(addToast({ title: 'Critical', message: 'Action required', type: 'error', persistent: true }))
  const tPersistent = store.getState().ui.toasts.find((t) => t.persistent)
  ctrl.sync(store.getState().ui.toasts)
  assert.equal(ctrl.has(tPersistent.id), false)

  // Advance to t=8s -> paused/resumed error expires cleanly
  advanceBy(1000)
  ctrl.sync(store.getState().ui.toasts)
  assert.deepEqual(expiredIds, [tSuccess.id, tWarning.id, tError.id])
  assert.deepEqual(
    store.getState().ui.toasts.map((t) => t.id),
    [tPersistent.id]
  )

  // Unmount cleanup cancels any pending timers safely
  store.dispatch(addToast({ title: 'Temp', message: 'Cleanup check', type: 'info' }))
  ctrl.sync(store.getState().ui.toasts)
  assert.ok(ctrl.size() >= 1)
  ctrl.clearAll()
  assert.equal(ctrl.size(), 0)
  assert.equal(scheduled.size, 0)
  store.dispatch(clearToasts())
})

test('Task 2: desktop top navigation StockSangati AI toggle preserves authentication and conversation history', async () => {
  installMockWindow()
  const { store } = await import('../src/store/index.js')
  const { setCredentials, setWorkspaces, logout } = await import('../src/store/authSlice.js')
  const {
    toggleAssistantOpen,
    setAssistantMinimized,
    setConversations,
    setActiveConversation,
  } = await import('../src/store/aiSlice.js')
  const { translate } = await import('../src/i18n/translations.js')

  assert.equal(translate('en', 'ai.navButton'), 'StockSangati AI')
  assert.equal(translate('hi', 'ai.navButton'), 'StockSangati AI')

  store.dispatch(
    setCredentials({
      token: 'tok-ai-header',
      refreshToken: 'ref-ai-header',
      user: { id: 5, name: 'Sanjana', role: 'owner', active_business_id: 3 },
    })
  )
  store.dispatch(
    setWorkspaces([
      {
        business: { id: 3, name: 'Sanjana Supermarket', business_type: 'retailer' },
        role: 'owner',
        permissions: ['ai.use'],
        is_active_workspace: true,
      },
    ])
  )
  store.dispatch(
    setConversations([{ id: 41, title: 'Low stock check', updated_at: '2026-11-28T01:00:00Z' }])
  )
  store.dispatch(
    setActiveConversation({
      conversationId: 41,
      messages: [
        { id: 1, role: 'user', content: 'Which products are running low?' },
        { id: 2, role: 'assistant', content: 'Sugar and Toor Dal are out of stock.' },
      ],
    })
  )

  // Opening via top nav button opens assistant cleanly without losing history or auth
  assert.equal(store.getState().ai.isOpen, false)
  store.dispatch(toggleAssistantOpen())
  assert.equal(store.getState().ai.isOpen, true)
  assert.equal(store.getState().ai.isMinimized, false)
  assert.equal(store.getState().ai.activeConversationId, 41)
  assert.equal(store.getState().ai.messages.length, 2)
  assert.equal(store.getState().auth.token, 'tok-ai-header')
  assert.equal(store.getState().auth.isAuthenticated, true)

  // Clicking top nav toggle while minimized restores panel instead of closing
  store.dispatch(setAssistantMinimized(true))
  store.dispatch(toggleAssistantOpen())
  assert.equal(store.getState().ai.isOpen, true)
  assert.equal(store.getState().ai.isMinimized, false)
  assert.equal(store.getState().ai.conversations.length, 1)
  assert.equal(store.getState().ai.messages.length, 2)

  // Clicking top nav toggle while expanded closes panel while preserving conversation state
  store.dispatch(toggleAssistantOpen())
  assert.equal(store.getState().ai.isOpen, false)
  assert.equal(store.getState().ai.activeConversationId, 41)
  assert.equal(store.getState().ai.messages.length, 2)
  assert.equal(store.getState().auth.token, 'tok-ai-header')

  store.dispatch(logout())
})

test('Section 4.5: theme defaults to light on fresh storage and preserves saved preferences', async () => {
  const { storage, docAttrs } = installMockWindow()
  const {
    getInitialTheme,
    setTheme,
    toggleTheme,
  } = await import('../src/store/uiSlice.js')

  // Fresh first-time visitor gets light theme
  storage.clear()
  assert.equal(getInitialTheme(), 'light')
  assert.equal(store.getState().ui.theme, 'light')

  // Explicit saved dark theme in either stocksangati_theme or legacy sims_theme is preserved
  storage.set('stocksangati_theme', 'dark')
  assert.equal(getInitialTheme(), 'dark')
  storage.clear()
  storage.set('sims_theme', 'dark')
  assert.equal(getInitialTheme(), 'dark')

  // Toggling persists to localStorage and sets documentElement[data-theme]
  storage.clear()
  store.dispatch(setTheme('dark'))
  assert.equal(store.getState().ui.theme, 'dark')
  assert.equal(storage.get('stocksangati_theme'), 'dark')
  assert.equal(docAttrs.get('data-theme'), 'dark')

  store.dispatch(toggleTheme())
  assert.equal(store.getState().ui.theme, 'light')
  assert.equal(storage.get('stocksangati_theme'), 'light')
  assert.equal(docAttrs.get('data-theme'), 'light')
})

test('Sections 4.3 & 4.4: sidebar collapse persistence, accordion single-group focus, and alert badge clamping', async () => {
  const { storage } = installMockWindow()
  const {
    getInitialSidebarCollapsed,
    toggleSidebarCollapsed,
    setSidebarCollapsed,
    setExpandedNavGroup,
    toggleNavGroup,
    findActiveNavGroupId,
    setAlertsUnreadCount,
  } = await import('../src/store/uiSlice.js')

  storage.clear()
  assert.equal(getInitialSidebarCollapsed(), false)
  assert.equal(store.getState().ui.sidebarCollapsed, false)

  store.dispatch(toggleSidebarCollapsed())
  assert.equal(store.getState().ui.sidebarCollapsed, true)
  assert.equal(storage.get('stocksangati_sidebar_collapsed'), 'true')
  assert.equal(getInitialSidebarCollapsed(), true)

  store.dispatch(setSidebarCollapsed(false))
  assert.equal(store.getState().ui.sidebarCollapsed, false)
  assert.equal(storage.get('stocksangati_sidebar_collapsed'), 'false')

  // Longest/exact route group resolution for accordion sync
  const groups = [
    { id: 'overview', items: [{ path: '/dashboard', end: true }] },
    { id: 'inventory', items: [{ path: '/products' }, { path: '/inventory' }] },
    { id: 'procurement', items: [{ path: '/suppliers' }, { path: '/purchase-orders' }] },
    { id: 'settings', items: [{ path: '/settings/security' }] },
  ]
  assert.equal(findActiveNavGroupId(groups, '/dashboard'), 'overview')
  assert.equal(findActiveNavGroupId(groups, '/purchase-orders'), 'procurement')
  assert.equal(findActiveNavGroupId(groups, '/inventory/adjustments'), 'inventory')
  assert.equal(findActiveNavGroupId(groups, '/settings/security'), 'settings')
  assert.equal(findActiveNavGroupId(groups, '/unknown-route'), null)

  // Only one expanded accordion group at a time, and clicking active toggles closed
  store.dispatch(setExpandedNavGroup('procurement'))
  assert.equal(store.getState().ui.expandedNavGroup, 'procurement')
  store.dispatch(toggleNavGroup('inventory'))
  assert.equal(store.getState().ui.expandedNavGroup, 'inventory')
  store.dispatch(toggleNavGroup('inventory'))
  assert.equal(store.getState().ui.expandedNavGroup, null)

  // Mobile drawer unread alerts counter clamps non-positive/invalid counts
  store.dispatch(setAlertsUnreadCount(7))
  assert.equal(store.getState().ui.alertsUnreadCount, 7)
  store.dispatch(setAlertsUnreadCount(-4))
  assert.equal(store.getState().ui.alertsUnreadCount, 0)
  store.dispatch(setAlertsUnreadCount('invalid'))
  assert.equal(store.getState().ui.alertsUnreadCount, 0)
})

test('Section 5: form validators support multi-character strings, decimals, empty edits, and monotonic row keys', async () => {
  const {
    createStableRowKey,
    validateAndBuildPurchaseOrderPayload,
    validateAndBuildProductPayload,
    validateAndBuildSupplierPayload,
    validateAndBuildSalePayload,
  } = await import('../src/utils/formHelpers.js')

  // Monotonic stable keys prevent middle-row removal from shifting sibling keys
  const keys = [createStableRowKey('po'), createStableRowKey('po'), createStableRowKey('po')]
  assert.equal(new Set(keys).size, 3)
  const remainingKeys = [keys[0], keys[2]]
  const nextKey = createStableRowKey('po')
  assert.equal(remainingKeys.includes(nextKey), false)

  // Purchase Order payload builder accepts multi-word strings, integer strings, and decimal unit costs
  const poForm = {
    supplier_id: '12',
    expected_delivery_date: '2026-12-05',
    notes: 'Festive urgent order - Lot #A19',
    items: [
      { _key: keys[0], product_id: '34', ordered_quantity: '125', unit_cost: '45.75' },
      { _key: keys[2], product_id: '35', ordered_quantity: '8', unit_cost: '0.00' },
    ],
  }
  const poOk = validateAndBuildPurchaseOrderPayload(poForm)
  assert.equal(poOk.error, '')
  assert.deepEqual(poOk.payload, {
    supplier_id: 12,
    expected_delivery_date: '2026-12-05',
    notes: 'Festive urgent order - Lot #A19',
    items: [
      { product_id: 34, ordered_quantity: 125, unit_cost: 45.75 },
      { product_id: 35, ordered_quantity: 8, unit_cost: 0 },
    ],
  })

  // Invalid PO quantity preserves input shape and returns validation message
  const badPo = validateAndBuildPurchaseOrderPayload({
    ...poForm,
    items: [{ _key: keys[0], product_id: '34', ordered_quantity: '', unit_cost: '10' }],
  })
  assert.match(badPo.error, /Ordered quantity/)
  assert.equal(badPo.payload, null)

  // Product payload validation handles long names, numeric strings, optional blank caps
  const prodOk = validateAndBuildProductPayload(
    {
      sku: 'RICE-PREM-25KG',
      name: 'Premium Organic Basmati Rice 25kg',
      category: 'Grains & Staples',
      unit: 'bag',
      cost_price: '1250.50',
      selling_price: '1499.00',
      reorder_level: '15',
      min_order_quantity: '10',
      order_pack_size: '5',
      max_stock_level: '',
      review_period_days: '7',
      initial_daily_demand: '3.25',
      supplier_id: '',
      current_stock: '40',
    },
    'add'
  )
  assert.equal(prodOk.error, '')
  assert.equal(prodOk.payload.cost_price, 1250.5)
  assert.equal(prodOk.payload.max_stock_level, null)
  assert.equal(prodOk.payload.initial_daily_demand, 3.25)
  assert.equal(prodOk.payload.current_stock, 40)

  const prodBad = validateAndBuildProductPayload({ sku: 'A', name: 'Item', cost_price: '-1', selling_price: '2' }, 'add')
  assert.match(prodBad.error, /Cost price/)

  // Supplier payload validation
  const supOk = validateAndBuildSupplierPayload({
    name: 'Shree Ganesh Traders Pvt Ltd',
    contact_person: 'Rajesh Verma',
    email: 'orders@ganesh.in',
    phone: '+91 98765 43210',
    address: 'Plot 14, Market Yard, Jaipur',
    lead_time_days: '0',
  })
  assert.equal(supOk.error, '')
  assert.equal(supOk.payload.lead_time_days, 0)
  const supBadEmail = validateAndBuildSupplierPayload({ name: 'Test', lead_time_days: '5', email: 'not-an-email' })
  assert.match(supBadEmail.error, /email/)

  // Sale payload validation & stock guard
  const saleOk = validateAndBuildSalePayload(
    { productId: '9', quantity: '12', sellingPrice: '', notes: 'Counter INV-88' },
    { availableStock: 20 }
  )
  assert.equal(saleOk.error, '')
  assert.deepEqual(saleOk.payload, {
    product_id: 9,
    quantity_sold: 12,
    selling_price: null,
    notes: 'Counter INV-88',
  })
  const saleOver = validateAndBuildSalePayload(
    { productId: '9', quantity: '25', sellingPrice: '10', notes: '' },
    { availableStock: 20 }
  )
  assert.match(saleOver.error, /20 units available/)
})

test('Section 6: contextual placeholders and navigation labels exist in both EN and HI without generic text', () => {
  const placeholderKeys = [
    'placeholders.productSku',
    'placeholders.productName',
    'placeholders.productCategory',
    'placeholders.costPrice',
    'placeholders.sellingPrice',
    'placeholders.openingStock',
    'placeholders.reorderLevel',
    'placeholders.moq',
    'placeholders.packSize',
    'placeholders.reviewDays',
    'placeholders.maxStock',
    'placeholders.coldStartDemand',
    'placeholders.supplierName',
    'placeholders.supplierContact',
    'placeholders.supplierEmail',
    'placeholders.supplierPhone',
    'placeholders.supplierLeadDays',
    'placeholders.supplierAddress',
    'placeholders.poNotes',
    'placeholders.poQuantity',
    'placeholders.poUnitCost',
    'placeholders.saleQuantity',
    'placeholders.saleNotes',
    'placeholders.adjustQuantity',
    'placeholders.adjustReason',
    'placeholders.receiptNotes',
    'placeholders.searchProducts',
    'placeholders.searchSuppliers',
    'placeholders.searchOrders',
    'placeholders.searchSales',
    'placeholders.searchStock',
    'placeholders.businessName',
    'placeholders.gstin',
    'placeholders.currency',
    'placeholders.thresholdDefault',
    'placeholders.personName',
    'placeholders.workEmail',
    'placeholders.currentPassword',
    'placeholders.newPassword',
    'placeholders.confirmPassword',
    'placeholders.simRestockQty',
    'placeholders.simRestockDay',
  ]
  const banned = new Set(['enter value', 'type here', 'enter data', 'quantity', 'day', 'opening qty'])

  for (const key of placeholderKeys) {
    const enVal = translate('en', key)
    const hiVal = translate('hi', key)
    assert.ok(enVal && enVal !== key, `Missing EN translation for ${key}`)
    assert.ok(hiVal && hiVal !== key, `Missing HI translation for ${key}`)
    assert.equal(banned.has(enVal.trim().toLowerCase()), false, `Generic EN placeholder for ${key}: ${enVal}`)
    assert.equal(banned.has(hiVal.trim().toLowerCase()), false, `Generic HI placeholder for ${key}: ${hiVal}`)
  }

  for (const commonKey of [
    'common.notifications',
    'common.collapseSidebar',
    'common.expandSidebar',
    'common.lightTheme',
    'common.darkTheme',
    'common.accountSettings',
  ]) {
    const enVal = translate('en', commonKey)
    const hiVal = translate('hi', commonKey)
    assert.ok(enVal && enVal !== commonKey, `Missing EN common key ${commonKey}`)
    assert.ok(hiVal && hiVal !== commonKey, `Missing HI common key ${commonKey}`)
    assert.notEqual(hiVal, enVal, `HI common key ${commonKey} should be localized`)
  }
})

test('Section 7: ML restructure shows 4 primary models cleanly with honest metrics and zero ARMIA typo', () => {
  const srcRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src')
  const walkFiles = (dir) => {
    const out = []
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, ent.name)
      if (ent.isDirectory()) out.push(...walkFiles(full))
      else if (/\.(js|jsx)$/.test(ent.name)) out.push(full)
    }
    return out
  }

  for (const file of walkFiles(srcRoot)) {
    const text = fs.readFileSync(file, 'utf8')
    assert.equal(text.includes('ARMIA'), false, `Unexpected typo ARMIA in ${file}`)
    assert.equal(/90%\s*accuracy/i.test(text), false, `Fabricated 90% accuracy string found in ${file}`)
  }

  const fpText = fs.readFileSync(path.join(srcRoot, 'pages', 'ForecastingPage.jsx'), 'utf8')
  const selectMatch = fpText.match(/id="forecast-model-select"[\s\S]*?<\/select>/)
  assert.ok(selectMatch, 'Expected forecast-model-select dropdown in ForecastingPage.jsx')
  const optionVals = [...selectMatch[0].matchAll(/<option\s+value="([^"]+)"/g)].map((m) => m[1])
  assert.deepEqual(optionVals, ['auto', 'arima', 'xgboost', 'random_forest', 'lstm'])
  assert.ok(fpText.includes("label: '10Y'") && fpText.includes('days: 3650'), 'Expected 10Y graph preset')
  assert.ok(fpText.includes('id="forecast-history-resolution"'), 'Expected resolution selector')

  for (const mlKey of [
    'intelligence.syntheticDemoTag',
    'intelligence.syntheticDatasetNotice',
    'intelligence.baselineFallbackBanner',
    'intelligence.modelGovernanceTitle',
    'intelligence.primaryLeaderboardTitle',
    'intelligence.errorComparisonTitle',
    'intelligence.biasComparisonTitle',
    'intelligence.biasConvention',
    'intelligence.graphRangeLabel',
    'intelligence.graphResolutionLabel',
  ]) {
    const enVal = translate('en', mlKey)
    const hiVal = translate('hi', mlKey)
    assert.ok(enVal && enVal !== mlKey, `Missing EN key ${mlKey}`)
    assert.ok(hiVal && hiVal !== mlKey, `Missing HI key ${mlKey}`)
    assert.notEqual(hiVal, enVal, `Expected HI translation for ${mlKey}`)
  }
})

test('Regression: API client never retries server 4xx/5xx HTTP errors via duplicate relative fallback fetch', async () => {
  const { storage } = installMockWindow()
  storage.set('stocksangati_token', 'valid-token')
  storage.set('stocksangati_user', JSON.stringify({ id: 7, active_business_id: 42 }))

  let fetchCount = 0
  globalThis.fetch = async () => {
    fetchCount += 1
    return new Response(JSON.stringify({ detail: 'Validation error' }), {
      status: 400,
      headers: { 'content-type': 'application/json' },
    })
  }

  const { api } = await import('../src/api.js')
  await assert.rejects(
    () => api.createSale({ product_id: 1, quantity_sold: 100 }),
    (err) => err.status === 400 && err.message === 'Validation error'
  )
  assert.equal(fetchCount, 1, 'HTTP 400 error must not fire a duplicate fallback fetch')

  // True network TypeError still attempts single relative fallback cleanly
  const urls = []
  globalThis.fetch = async (url) => {
    urls.push(url)
    if (urls.length === 1) {
      throw new TypeError('Failed to fetch')
    }
    return new Response(JSON.stringify({ data: [{ id: 1, name: 'Widget' }] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  const prods = await api.getProducts()
  assert.equal(urls.length, 2)
  assert.equal(prods.length, 1)
})
