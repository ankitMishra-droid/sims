import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Bot,
  X,
  Minimize2,
  Maximize2,
  Plus,
  History,
  Trash2,
  Send,
  RefreshCw,
  BookOpen,
  Check,
  AlertCircle,
  Sparkles,
  Coins,
} from 'lucide-react'
import AiMessageContent from './AiMessageContent'
import { filterUserFacingSources } from './aiFormatting'
import { api } from '../../api'
import { useTranslation } from '../../hooks/useTranslation'
import { addToast } from '../../store/uiSlice'
import {
  setAssistantOpen,
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
  setCreditAccount,
  setLastTurnCreditInfo,
} from '../../store/aiSlice'

function buildClientIdempotencyKey(workspaceId, seq) {
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID) {
    return `chat-${workspaceId || 0}-${globalThis.crypto.randomUUID()}`
  }
  return `chat-${workspaceId || 0}-${seq}-${Date.now()}`
}

export default function FloatingAiAssistant() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const location = useLocation()
  const { t, language: uiLanguage } = useTranslation()

  const { user, currentWorkspace } = useSelector((state) => state.auth)
  const {
    isOpen,
    isMinimized,
    isExpanded,
    preferredLanguage,
    conversations,
    activeConversationId,
    messages,
    sending,
    loadingHistory,
    error,
    errorCode,
    errorRetryable,
    lastFailedPrompt,
    creditAccount,
    lastTurnCreditInfo,
  } = useSelector((state) => state.ai)

  const [input, setInput] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [confirmClearId, setConfirmClearId] = useState(null)
  const [actionBusyMsgId, setActionBusyMsgId] = useState(null)
  const messagesEndRef = useRef(null)
  const seqRef = useRef(0)
  const pendingIdempotencyKeyRef = useRef(null)

  const hasWorkspace = !!currentWorkspace?.business?.id
  const workspaceId = currentWorkspace?.business?.id

  useEffect(() => {
    if (!isOpen || !hasWorkspace) return
    let active = true
    const loadPanelData = async () => {
      try {
        const [list, bal] = await Promise.allSettled([
          api.getAiConversations(),
          api.getAiCreditBalance(),
        ])
        if (active && list.status === 'fulfilled') dispatch(setConversations(list.value))
        if (active && bal.status === 'fulfilled') dispatch(setCreditAccount(bal.value))
      } catch {
        // Ignore silent prefetch errors
      }
    }
    loadPanelData()
    return () => {
      active = false
    }
  }, [isOpen, hasWorkspace, workspaceId, dispatch])

  useEffect(() => {
    if (isOpen && !isMinimized && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isOpen, isMinimized])

  if (!user || !hasWorkspace) return null

  const buildPageContext = () => {
    const ctx = { route: location.pathname }
    const prodMatch = location.pathname.match(/\/products\/(\d+)/)
    if (prodMatch) ctx.product_id = Number(prodMatch[1])
    const poMatch = location.pathname.match(/\/purchase-orders\/(\d+)/)
    if (poMatch) ctx.purchase_order_id = Number(poMatch[1])
    return ctx
  }

  const handleOpenConversation = async (convId) => {
    dispatch(setLoadingHistory(true))
    try {
      const detail = await api.getAiConversationDetail(convId)
      dispatch(
        setActiveConversation({
          conversationId: detail.conversation.id,
          messages: detail.messages || [],
        })
      )
      setShowHistory(false)
    } catch (err) {
      dispatch(setAssistantError({ message: err.message }))
    } finally {
      dispatch(setLoadingHistory(false))
    }
  }

  const handleDeleteConversation = async (convId) => {
    try {
      await api.deleteAiConversation(convId)
      dispatch(removeConversationFromList(convId))
      setConfirmClearId(null)
    } catch (err) {
      dispatch(addToast({ title: t('common.error', 'Error'), message: err.message, type: 'error' }))
    }
  }

  const handleSend = async (overrideText = null, { isRetry = false } = {}) => {
    const textToSend = String(overrideText ?? input).trim()
    if (!textToSend || sending) return

    if (overrideText === null) setInput('')
    dispatch(setSending(true))

    seqRef.current += 1
    const idemKey =
      isRetry && pendingIdempotencyKeyRef.current
        ? pendingIdempotencyKeyRef.current
        : buildClientIdempotencyKey(workspaceId, seqRef.current)
    pendingIdempotencyKeyRef.current = idemKey

    const existingLast = messages[messages.length - 1]
    const shouldAppendOpt = !(existingLast && existingLast.role === 'user' && existingLast.content === textToSend)
    if (shouldAppendOpt) {
      dispatch(
        appendOptimisticUserMessage({
          id: `temp-${seqRef.current}`,
          role: 'user',
          content: textToSend,
          language: preferredLanguage === 'auto' ? uiLanguage : preferredLanguage,
          _optimistic: true,
        })
      )
    }

    try {
      const res = await api.sendAiChatMessage(
        {
          message: textToSend,
          conversation_id: activeConversationId,
          preferred_language: preferredLanguage,
          page_context: buildPageContext(),
        },
        { idempotencyKey: idemKey }
      )
      pendingIdempotencyKeyRef.current = null
      dispatch(
        setLastTurnCreditInfo({
          credits_used: res.credits_used ?? 0,
          credits_reserved: res.credits_reserved ?? 0,
          credits_refunded: res.credits_refunded ?? 0,
          usage_source: res.usage_source || 'provider_reported',
          idempotent_replay: !!res.idempotent_replay,
        })
      )
      const detail = await api.getAiConversationDetail(res.conversation.id)
      dispatch(
        setChatMessagesFromServer({
          conversation: detail.conversation,
          messages: detail.messages,
        })
      )
      api.getAiCreditBalance().then((bal) => dispatch(setCreditAccount(bal))).catch(() => {})
    } catch (err) {
      api.getAiCreditBalance().then((bal) => dispatch(setCreditAccount(bal))).catch(() => {})
      dispatch(
        setAssistantError({
          message: err.message || 'The AI assistant is temporarily unavailable. Your inventory operations are still available.',
          errorCode: err.errorCode || null,
          retryable: err.retryable !== false,
          conversationId: err.conversationId || null,
          failedPrompt: textToSend,
        })
      )
    }
  }

  const handleConfirmAction = async (msgId, confirm) => {
    if (!activeConversationId || actionBusyMsgId) return
    setActionBusyMsgId(msgId)
    try {
      const res = await api.confirmAiAssistantAction(activeConversationId, {
        message_id: msgId,
        confirm,
      })
      dispatch(updateMessagePendingAction({ messageId: msgId, pendingAction: res.action }))
      dispatch(
        addToast({
          title: confirm ? t('ai.actionExecuted') : t('ai.actionCancelled'),
          message:
            confirm && res.result?.order_number
              ? `PO ${res.result.order_number} created cleanly.`
              : res.action?.summary || '',
          type: confirm ? 'success' : 'info',
        })
      )
    } catch (err) {
      dispatch(addToast({ title: 'Action Error', message: err.message, type: 'error' }))
    } finally {
      setActionBusyMsgId(null)
    }
  }

  const starters = [t('ai.starter1'), t('ai.starter2'), t('ai.starter3'), t('ai.starter4')]

  return (
    <div className="ai-floating-root" aria-live="polite">
      {!isOpen && (
        <button
          type="button"
          className="ai-fab-btn"
          onClick={() => dispatch(setAssistantOpen(true))}
          title={t('ai.assistantTooltip')}
          aria-label={t('ai.assistantTooltip')}
        >
          <Bot size={20} />
          <span className="ai-fab-label">{t('ai.assistantTitle').split(' ')[0]} AI</span>
        </button>
      )}

      {isOpen && isMinimized && (
        <div className="ai-minimized-pill">
          <button
            type="button"
            className="ai-minimized-restore"
            onClick={() => dispatch(setAssistantMinimized(false))}
          >
            <Bot size={16} />
            <span>{t('ai.assistantTitle')}</span>
          </button>
          <button
            type="button"
            className="icon-btn-sm"
            onClick={() => dispatch(setAssistantOpen(false))}
            title={t('ai.close')}
            aria-label={t('ai.close')}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {isOpen && !isMinimized && (
        <section
          id="stocksangati-ai-dialog"
          className={`ai-panel ${isExpanded ? 'expanded' : ''}`}
          role="dialog"
          aria-label={t('ai.assistantTitle')}
        >
          <header className="ai-panel-header">
            <div className="ai-panel-title-wrap">
              <div className="ai-panel-icon">
                <Sparkles size={16} />
              </div>
              <div style={{ minWidth: 0 }}>
                <div className="ai-panel-title">{t('ai.assistantTitle')}</div>
                <div className="ai-panel-subtitle">
                  {currentWorkspace?.business?.name} • {t('ai.assistantSubtitle')}
                </div>
              </div>
            </div>

            <div className="ai-panel-controls">
              <button
                type="button"
                className="icon-btn-sm"
                title={t('ai.newChat')}
                aria-label={t('ai.newChat')}
                onClick={() => {
                  dispatch(startNewConversationState())
                  setShowHistory(false)
                }}
              >
                <Plus size={15} />
              </button>
              <button
                type="button"
                className={`icon-btn-sm ${showHistory ? 'active' : ''}`}
                title={t('ai.history')}
                aria-label={t('ai.history')}
                onClick={() => setShowHistory((v) => !v)}
              >
                <History size={15} />
              </button>
              <button
                type="button"
                className="icon-btn-sm"
                title={isExpanded ? t('ai.collapse') : t('ai.expand')}
                aria-label={isExpanded ? t('ai.collapse') : t('ai.expand')}
                onClick={() => dispatch(setAssistantExpanded(!isExpanded))}
              >
                <Maximize2 size={14} />
              </button>
              <button
                type="button"
                className="icon-btn-sm"
                title={t('ai.minimize')}
                aria-label={t('ai.minimize')}
                onClick={() => dispatch(setAssistantMinimized(true))}
              >
                <Minimize2 size={14} />
              </button>
              <button
                type="button"
                className="icon-btn-sm"
                title={t('ai.close')}
                aria-label={t('ai.close')}
                onClick={() => dispatch(setAssistantOpen(false))}
              >
                <X size={15} />
              </button>
            </div>
          </header>

          <div className="ai-panel-toolbar">
            <label className="ai-lang-picker">
              <span>{t('ai.languageLabel')}:</span>
              <select
                value={preferredLanguage}
                onChange={(e) => dispatch(setAssistantLanguage(e.target.value))}
                aria-label={t('ai.languageLabel')}
              >
                <option value="auto">{t('ai.langAuto')}</option>
                <option value="en">{t('ai.langEn')}</option>
                <option value="hi">{t('ai.langHi')}</option>
                <option value="mixed">{t('ai.langMixed')}</option>
              </select>
            </label>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              {creditAccount && (
                <button
                  type="button"
                  className={`ai-credit-chip ${
                    creditAccount.status === 'SUSPENDED' || creditAccount.available_credits <= 0
                      ? 'empty'
                      : creditAccount.available_credits <= 10
                      ? 'low'
                      : ''
                  }`}
                  onClick={() => {
                    navigate('/ai-usage')
                    dispatch(setAssistantMinimized(true))
                  }}
                  title={t('ai.creditsLabel')}
                >
                  <Coins size={12} />
                  <span>
                    {creditAccount.status === 'SUSPENDED'
                      ? 'Suspended'
                      : `${Number(creditAccount.available_credits || 0).toFixed(2)} cr`}
                  </span>
                </button>
              )}

              {activeConversationId && (
                <>
                  {confirmClearId === activeConversationId ? (
                    <>
                      <button
                        type="button"
                        className="btn-xs btn-danger"
                        onClick={() => handleDeleteConversation(activeConversationId)}
                      >
                        {t('common.confirm')}
                      </button>
                      <button
                        type="button"
                        className="btn-xs btn-secondary"
                        onClick={() => setConfirmClearId(null)}
                      >
                        {t('common.cancel')}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="icon-btn-sm"
                      title={t('ai.clearChat')}
                      aria-label={t('ai.clearChat')}
                      onClick={() => setConfirmClearId(activeConversationId)}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {showHistory ? (
            <div className="ai-history-list">
              {conversations.length === 0 ? (
                <div className="ai-empty-note">{t('ai.noConversations')}</div>
              ) : (
                conversations.map((conv) => (
                  <div
                    key={conv.id}
                    className={`ai-history-item ${conv.id === activeConversationId ? 'active' : ''}`}
                  >
                    <button
                      type="button"
                      className="ai-history-open"
                      onClick={() => handleOpenConversation(conv.id)}
                    >
                      <div className="ai-history-title">{conv.title}</div>
                      <div className="ai-history-meta">
                        {new Date(conv.updated_at).toLocaleString()}
                      </div>
                    </button>
                    <button
                      type="button"
                      className="icon-btn-sm"
                      aria-label={t('ai.clearChat')}
                      onClick={() => handleDeleteConversation(conv.id)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="ai-messages-area">
              {loadingHistory ? (
                <div className="ai-empty-note">{t('common.loading')}</div>
              ) : messages.length === 0 ? (
                <div className="ai-welcome-box">
                  <div className="ai-welcome-title">{t('ai.welcomeTitle')}</div>
                  <div className="ai-welcome-hint">{t('ai.welcomeHint')}</div>
                  <div className="ai-starter-list">
                    {starters.map((promptText, idx) => (
                      <button
                        key={idx}
                        type="button"
                        className="ai-starter-chip"
                        onClick={() => handleSend(promptText)}
                      >
                        {promptText}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((msg) => {
                  const docSources = filterUserFacingSources(msg.sources)
                  return (
                  <div key={msg.id} className={`ai-msg-row ${msg.role}`}>
                    <div className={`ai-msg-bubble ${msg.role}`}>
                      <AiMessageContent content={msg.content} role={msg.role} />

                      {docSources.length > 0 && (
                        <div className="ai-sources-box">
                          <div className="ai-sources-label">{t('ai.sourcesTitle')}</div>
                          <div className="ai-sources-chips">
                            {docSources.map((src, idx) => (
                              <button
                                key={idx}
                                type="button"
                                className="ai-source-chip"
                                onClick={() => navigate(`/ai-knowledge?doc=${src.document_id}`)}
                                title={src.excerpt || src.title}
                                style={{ cursor: 'pointer' }}
                              >
                                <BookOpen size={11} />
                                <span>
                                  {src.title}
                                  {src.page_number ? ` (p.${src.page_number})` : ''}
                                </span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {msg.pending_action && (
                        <div className="ai-action-card">
                          <div className="ai-action-title">{t('ai.confirmActionTitle')}</div>
                          <div className="ai-action-summary">{msg.pending_action.summary}</div>
                          {msg.pending_action.status === 'PENDING_CONFIRMATION' ? (
                            <div className="ai-action-buttons">
                              <button
                                type="button"
                                className="btn-xs btn-primary"
                                disabled={actionBusyMsgId === msg.id}
                                onClick={() => handleConfirmAction(msg.id, true)}
                              >
                                <Check size={12} /> {t('ai.confirmExecute')}
                              </button>
                              <button
                                type="button"
                                className="btn-xs btn-secondary"
                                disabled={actionBusyMsgId === msg.id}
                                onClick={() => handleConfirmAction(msg.id, false)}
                              >
                                {t('ai.cancelAction')}
                              </button>
                            </div>
                          ) : (
                            <div className="ai-action-resolved">
                              Status: <strong>{msg.pending_action.status}</strong>
                              {msg.pending_action.result?.order_number
                                ? ` (${msg.pending_action.result.order_number})`
                                : ''}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  )
                })
              )}

              {sending && (
                <div className="ai-msg-row assistant">
                  <div className="ai-msg-bubble assistant ai-typing">{t('ai.sending')}</div>
                </div>
              )}

              {error && (
                <div className="ai-error-banner" role="alert">
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    {errorCode === 'INSUFFICIENT_AI_CREDITS' && (
                      <span className="badge badge-danger" style={{ width: 'fit-content' }}>
                        {t('ai.creditsInsufficientBadge')}
                      </span>
                    )}
                    {errorCode === 'QUOTA_EXHAUSTED' && (
                      <span className="badge badge-warning" style={{ width: 'fit-content' }}>
                        {t('ai.quotaExhaustedBadge')}
                      </span>
                    )}
                    {errorCode === 'TENANT_QUOTA_EXCEEDED' && (
                      <span className="badge badge-warning" style={{ width: 'fit-content' }}>
                        {t('ai.tenantQuotaBadge')}
                      </span>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <AlertCircle size={15} />
                      <span>{error}</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.35rem', flexShrink: 0 }}>
                    {(errorCode === 'INSUFFICIENT_AI_CREDITS' || errorCode === 'AI_ACCOUNT_SUSPENDED') && (
                      <button
                        type="button"
                        className="btn-xs btn-primary"
                        onClick={() => {
                          navigate('/ai-usage')
                          dispatch(setAssistantMinimized(true))
                        }}
                      >
                        <Coins size={12} /> {t('ai.viewCreditsBtn')}
                      </button>
                    )}
                    {lastFailedPrompt && errorRetryable && errorCode !== 'INSUFFICIENT_AI_CREDITS' && (
                      <button
                        type="button"
                        className="btn-xs btn-secondary"
                        onClick={() => handleSend(lastFailedPrompt, { isRetry: true })}
                      >
                        <RefreshCw size={12} /> {t('common.retry')}
                      </button>
                    )}
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}

          {lastTurnCreditInfo && !error && (
            <div className="ai-turn-credit-meta">
              <span>
                Last response: {Number(lastTurnCreditInfo.credits_used || 0).toFixed(3)} credits
                {lastTurnCreditInfo.idempotent_replay ? ' (deduplicated)' : ''}
              </span>
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--erp-primary)', cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600 }}
                onClick={() => {
                  navigate('/ai-usage')
                  dispatch(setAssistantMinimized(true))
                }}
              >
                {t('ai.viewCreditsBtn')}
              </button>
            </div>
          )}

          <form
            className="ai-input-bar"
            onSubmit={(e) => {
              e.preventDefault()
              handleSend()
            }}
          >
            <input
              type="text"
              className="form-control ai-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t('ai.inputPlaceholder')}
              disabled={sending}
              aria-label={t('ai.inputPlaceholder')}
            />
            <button
              type="submit"
              className="btn btn-primary ai-send-btn"
              disabled={sending || !input.trim()}
              aria-label={t('ai.send')}
            >
              <Send size={15} />
            </button>
          </form>
        </section>
      )}
    </div>
  )
}
