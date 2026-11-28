import { createSlice } from '@reduxjs/toolkit'

const initialState = {
  isOpen: false,
  isMinimized: false,
  isExpanded: false,
  preferredLanguage: 'auto',
  conversations: [],
  activeConversationId: null,
  messages: [],
  sending: false,
  loadingHistory: false,
  error: null,
  errorCode: null,
  errorRetryable: true,
  lastFailedPrompt: null,
  documents: [],
  documentsLoading: false,
  aiHealth: null,
  creditAccount: null,
  creditLoading: false,
  pricingSchedule: null,
  usageSummary: null,
  lastTurnCreditInfo: null,
}

const aiSlice = createSlice({
  name: 'ai',
  initialState,
  reducers: {
    setAssistantOpen: (state, action) => {
      state.isOpen = !!action.payload
      if (action.payload) state.isMinimized = false
    },
    toggleAssistantOpen: (state) => {
      if (state.isOpen && state.isMinimized) {
        state.isMinimized = false
        return
      }
      state.isOpen = !state.isOpen
      if (state.isOpen) state.isMinimized = false
    },
    setAssistantMinimized: (state, action) => {
      state.isMinimized = !!action.payload
    },
    setAssistantExpanded: (state, action) => {
      state.isExpanded = !!action.payload
    },
    setAssistantLanguage: (state, action) => {
      state.preferredLanguage = action.payload || 'auto'
    },
    setConversations: (state, action) => {
      state.conversations = Array.isArray(action.payload) ? action.payload : []
    },
    setActiveConversation: (state, action) => {
      const { conversationId, messages } = action.payload || {}
      state.activeConversationId = conversationId || null
      if (messages !== undefined) {
        state.messages = Array.isArray(messages) ? messages : []
      }
      state.error = null
    },
    startNewConversationState: (state) => {
      state.activeConversationId = null
      state.messages = []
      state.error = null
      state.lastFailedPrompt = null
    },
    setSending: (state, action) => {
      state.sending = !!action.payload
      if (action.payload) {
        state.error = null
        state.errorCode = null
        state.errorRetryable = true
      }
    },
    setLoadingHistory: (state, action) => {
      state.loadingHistory = !!action.payload
    },
    appendOptimisticUserMessage: (state, action) => {
      state.messages.push(action.payload)
    },
    applyChatSuccess: (state, action) => {
      const { conversation, message } = action.payload
      if (conversation?.id) {
        state.activeConversationId = conversation.id
        const idx = state.conversations.findIndex((c) => c.id === conversation.id)
        if (idx >= 0) {
          state.conversations[idx] = conversation
        } else {
          state.conversations.unshift(conversation)
        }
      }
      if (message) {
        state.messages = state.messages.filter((m) => !m._optimistic)
        state.messages.push({
          id: `user-${message.id}`,
          role: 'user',
          content: action.payload.userText,
          language: message.language,
          created_at: message.created_at,
        })
        // Prevent duplicate user message if already persisted from server
        const nonOpt = state.messages.filter((m) => m.id !== `user-${message.id}`)
        state.messages = nonOpt
      }
      state.sending = false
      state.error = null
      state.lastFailedPrompt = null
    },
    setChatMessagesFromServer: (state, action) => {
      const { conversation, messages } = action.payload
      if (conversation?.id) {
        state.activeConversationId = conversation.id
        const idx = state.conversations.findIndex((c) => c.id === conversation.id)
        if (idx >= 0) {
          state.conversations[idx] = conversation
        } else {
          state.conversations.unshift(conversation)
        }
      }
      if (Array.isArray(messages)) {
        state.messages = messages
      }
      state.sending = false
      state.error = null
      state.errorCode = null
      state.errorRetryable = true
      state.lastFailedPrompt = null
    },
    setAssistantError: (state, action) => {
      const {
        message,
        errorCode = null,
        retryable = true,
        conversationId = null,
        failedPrompt = null,
      } =
        typeof action.payload === 'string'
          ? { message: action.payload }
          : action.payload || {}
      state.sending = false
      state.error = message || 'AI assistant request failed.'
      state.errorCode = errorCode
      state.errorRetryable = retryable !== false
      if (conversationId && !state.activeConversationId) {
        state.activeConversationId = conversationId
      }
      if (failedPrompt !== null) {
        state.lastFailedPrompt = failedPrompt
      }
    },
    updateMessagePendingAction: (state, action) => {
      const { messageId, pendingAction } = action.payload
      state.messages = state.messages.map((m) =>
        m.id === messageId ? { ...m, pending_action: pendingAction } : m
      )
    },
    removeConversationFromList: (state, action) => {
      const cid = action.payload
      state.conversations = state.conversations.filter((c) => c.id !== cid)
      if (state.activeConversationId === cid) {
        state.activeConversationId = null
        state.messages = []
      }
    },
    setDocuments: (state, action) => {
      state.documents = Array.isArray(action.payload) ? action.payload : []
    },
    setDocumentsLoading: (state, action) => {
      state.documentsLoading = !!action.payload
    },
    setAiHealth: (state, action) => {
      state.aiHealth = action.payload
    },
    setCreditAccount: (state, action) => {
      state.creditAccount = action.payload || null
    },
    setCreditLoading: (state, action) => {
      state.creditLoading = !!action.payload
    },
    setPricingSchedule: (state, action) => {
      state.pricingSchedule = action.payload || null
    },
    setUsageSummary: (state, action) => {
      state.usageSummary = action.payload || null
    },
    setLastTurnCreditInfo: (state, action) => {
      state.lastTurnCreditInfo = action.payload || null
    },
  },
})

export const {
  setAssistantOpen,
  toggleAssistantOpen,
  setAssistantMinimized,
  setAssistantExpanded,
  setAssistantLanguage,
  setConversations,
  setActiveConversation,
  startNewConversationState,
  setSending,
  setLoadingHistory,
  appendOptimisticUserMessage,
  setChatMessagesFromServer,
  setAssistantError,
  updateMessagePendingAction,
  removeConversationFromList,
  setDocuments,
  setDocumentsLoading,
  setAiHealth,
  setCreditAccount,
  setCreditLoading,
  setPricingSchedule,
  setUsageSummary,
  setLastTurnCreditInfo,
} = aiSlice.actions

export default aiSlice.reducer
