import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { Bar } from 'react-chartjs-2'
import {
  Activity,
  AlertTriangle,
  Coins,
  Cpu,
  History,
  Info,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  SlidersHorizontal,
  TrendingUp,
} from 'lucide-react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import { addToast } from '../store/uiSlice'
import {
  setCreditAccount,
  setPricingSchedule,
  setUsageSummary,
} from '../store/aiSlice'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import ChartCard from '../components/charts/ChartCard'
import { getChartTheme } from '../components/charts/ChartSetup'
import { LoadingState, EmptyState } from '../components/common/StateBlocks'

const TX_BADGE = {
  INITIAL_GRANT: 'badge-info',
  PURCHASE: 'badge-success',
  PROMOTIONAL_CREDIT: 'badge-success',
  PLAN_ALLOCATION: 'badge-info',
  MANUAL_ADJUSTMENT: 'badge-warning',
  REQUEST_RESERVATION: 'badge-neutral',
  REQUEST_CAPTURE: 'badge-neutral',
  REQUEST_REFUND: 'badge-success',
  EXPIRATION: 'badge-danger',
}

export default function AIUsagePage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t } = useTranslation()

  const { currentWorkspace } = useSelector((state) => state.auth)
  const theme = useSelector((state) => state.ui.theme)
  const isDark = theme === 'dark'
  const chartColors = getChartTheme(isDark)

  const permissions = currentWorkspace?.permissions || []
  const role = String(currentWorkspace?.role || '').toLowerCase()
  const canManageCredits =
    permissions.includes('ai.credits.manage') ||
    (permissions.length === 0 && (role === 'owner' || role === 'admin'))

  const [loading, setLoading] = useState(true)
  const [windowDays, setWindowDays] = useState(30)
  const [activeTab, setActiveTab] = useState('overview')

  const [account, setAccount] = useState(null)
  const [pricing, setPricing] = useState(null)
  const [summary, setSummary] = useState(null)

  const [txPage, setTxPage] = useState({ items: [], total: 0, limit: 15, offset: 0 })
  const [txFilter, setTxFilter] = useState('')

  const [logsPage, setLogsPage] = useState({ items: [], total: 0, limit: 15, offset: 0 })
  const [logStatusFilter, setLogStatusFilter] = useState('')
  const [logOpFilter, setLogOpFilter] = useState('')

  const [adminFailures, setAdminFailures] = useState(null)
  const [busyRecoverId, setBusyRecoverId] = useState(null)

  const adjSeqRef = useRef(0)

  // Admin credit adjustment form
  const [adjType, setAdjType] = useState('PURCHASE')
  const [adjAmount, setAdjAmount] = useState('100')
  const [adjReason, setAdjReason] = useState('')
  const [adjRef, setAdjRef] = useState('')
  const [adjBusy, setAdjBusy] = useState(false)

  // Admin policy form
  const [policyForm, setPolicyForm] = useState({
    status: 'ACTIVE',
    plan_tier: 'starter',
    rpm_limit: 20,
    daily_request_limit: 500,
    daily_token_limit: 500000,
    max_credits_per_operation: 25,
    max_concurrent_requests: 5,
    max_context_turns: 8,
    max_document_mb: 15,
    reason: '',
  })
  const [policyBusy, setPolicyBusy] = useState(false)

  const syncPolicyForm = useCallback((acc) => {
    if (!acc) return
    setPolicyForm((prev) => ({
      ...prev,
      status: acc.status || 'ACTIVE',
      plan_tier: acc.plan_tier || 'starter',
      rpm_limit: acc.limits?.rpm_limit ?? 20,
      daily_request_limit: acc.limits?.daily_request_limit ?? 500,
      daily_token_limit: acc.limits?.daily_token_limit ?? 500000,
      max_credits_per_operation: acc.limits?.max_credits_per_operation ?? 25,
      max_concurrent_requests: acc.limits?.max_concurrent_requests ?? 5,
      max_context_turns: acc.limits?.max_context_turns ?? 8,
      max_document_mb: acc.limits?.max_document_mb ?? 15,
    }))
  }, [])

  const loadCoreData = useCallback(async () => {
    setLoading(true)
    try {
      const [accRes, priceRes, sumRes] = await Promise.all([
        api.getAiCreditBalance(),
        api.getAiCreditPricing(),
        api.getAiUsageSummary(windowDays),
      ])
      setAccount(accRes)
      setPricing(priceRes)
      setSummary(sumRes)
      syncPolicyForm(accRes)
      dispatch(setCreditAccount(accRes))
      dispatch(setPricingSchedule(priceRes))
      dispatch(setUsageSummary(sumRes))

      if (canManageCredits) {
        try {
          const failRes = await api.getAiAdminFailures()
          setAdminFailures(failRes)
        } catch {
          setAdminFailures(null)
        }
      }
    } catch (err) {
      dispatch(addToast({ title: 'Error', message: err.message, type: 'error' }))
    } finally {
      setLoading(false)
    }
  }, [windowDays, canManageCredits, dispatch, syncPolicyForm])

  const loadTransactions = useCallback(
    async (offset = 0) => {
      try {
        const res = await api.getAiCreditTransactions({
          transactionType: txFilter,
          limit: 15,
          offset,
        })
        setTxPage(res)
      } catch (err) {
        dispatch(addToast({ title: 'Ledger Load Failed', message: err.message, type: 'error' }))
      }
    },
    [txFilter, dispatch]
  )

  const loadLogs = useCallback(
    async (offset = 0) => {
      try {
        const res = await api.getAiUsageLogs({
          status: logStatusFilter,
          operationType: logOpFilter,
          limit: 15,
          offset,
        })
        setLogsPage(res)
      } catch (err) {
        dispatch(addToast({ title: 'Usage Logs Failed', message: err.message, type: 'error' }))
      }
    },
    [logStatusFilter, logOpFilter, dispatch]
  )

  useEffect(() => {
    let active = true
    Promise.all([
      api.getAiCreditBalance(),
      api.getAiCreditPricing(),
      api.getAiUsageSummary(windowDays),
    ])
      .then(async ([accRes, priceRes, sumRes]) => {
        if (!active) return
        setAccount(accRes)
        setPricing(priceRes)
        setSummary(sumRes)
        syncPolicyForm(accRes)
        dispatch(setCreditAccount(accRes))
        dispatch(setPricingSchedule(priceRes))
        dispatch(setUsageSummary(sumRes))
        if (canManageCredits) {
          try {
            const failRes = await api.getAiAdminFailures()
            if (active) setAdminFailures(failRes)
          } catch {
            if (active) setAdminFailures(null)
          }
        }
      })
      .catch((err) => {
        if (active) dispatch(addToast({ title: 'Error', message: err.message, type: 'error' }))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [windowDays, canManageCredits, dispatch, syncPolicyForm])

  useEffect(() => {
    let active = true
    api
      .getAiCreditTransactions({ transactionType: txFilter, limit: 15, offset: 0 })
      .then((res) => {
        if (active) setTxPage(res)
      })
      .catch((err) => {
        if (active) dispatch(addToast({ title: 'Ledger Load Failed', message: err.message, type: 'error' }))
      })
    return () => {
      active = false
    }
  }, [txFilter, dispatch])

  useEffect(() => {
    let active = true
    api
      .getAiUsageLogs({ status: logStatusFilter, operationType: logOpFilter, limit: 15, offset: 0 })
      .then((res) => {
        if (active) setLogsPage(res)
      })
      .catch((err) => {
        if (active) dispatch(addToast({ title: 'Usage Logs Failed', message: err.message, type: 'error' }))
      })
    return () => {
      active = false
    }
  }, [logStatusFilter, logOpFilter, dispatch])

  const trendChartData = useMemo(() => {
    const trends = summary?.daily_trends || []
    return {
      labels: trends.map((d) => d.date),
      datasets: [
        {
          label: 'Credits Consumed',
          data: trends.map((d) => Number(d.credits_consumed || 0)),
          backgroundColor: chartColors.palette?.[1] || '#10b981',
          borderRadius: 6,
        },
        {
          label: 'Credits Refunded',
          data: trends.map((d) => Number(d.credits_refunded || 0)),
          backgroundColor: chartColors.palette?.[3] || '#f59e0b',
          borderRadius: 6,
        },
      ],
    }
  }, [summary, chartColors])

  const handleAdjustCredits = async (e) => {
    e.preventDefault()
    if (adjBusy) return
    const delta = Number(adjAmount)
    if (!Number.isFinite(delta) || delta === 0) {
      dispatch(addToast({ title: 'Validation', message: 'Enter a non-zero credit amount.', type: 'warning' }))
      return
    }
    if (adjReason.trim().length < 3) {
      dispatch(addToast({ title: 'Validation', message: 'Enter a clear reason (at least 3 characters).', type: 'warning' }))
      return
    }
    setAdjBusy(true)
    adjSeqRef.current += 1
    const idem =
      typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID
        ? `ui-adj-${globalThis.crypto.randomUUID()}`
        : `ui-adj-${adjType}-${adjSeqRef.current}`
    try {
      const res = await api.adjustAiCredits(
        {
          credit_delta: delta,
          transaction_type: adjType,
          reason: adjReason.trim(),
          billing_reference: adjRef.trim() || null,
          idempotency_key: idem,
        },
        idem
      )
      setAccount(res.account)
      dispatch(setCreditAccount(res.account))
      setAdjReason('')
      setAdjRef('')
      dispatch(
        addToast({
          title: 'Credits Updated',
          message: `Available balance is now ${Number(res.account.available_credits).toFixed(3)} credits.`,
          type: 'success',
        })
      )
      await Promise.all([loadCoreData(), loadTransactions(0)])
    } catch (err) {
      dispatch(addToast({ title: 'Adjustment Failed', message: err.message, type: 'error' }))
    } finally {
      setAdjBusy(false)
    }
  }

  const handleSavePolicies = async (e) => {
    e.preventDefault()
    if (policyBusy) return
    if (policyForm.reason.trim().length < 3) {
      dispatch(addToast({ title: 'Validation', message: 'Provide a policy update reason (at least 3 chars).', type: 'warning' }))
      return
    }
    setPolicyBusy(true)
    try {
      const updated = await api.updateAiPolicies({
        status: policyForm.status,
        plan_tier: policyForm.plan_tier,
        rpm_limit: Number(policyForm.rpm_limit),
        daily_request_limit: Number(policyForm.daily_request_limit),
        daily_token_limit: Number(policyForm.daily_token_limit),
        max_credits_per_operation: Number(policyForm.max_credits_per_operation),
        max_concurrent_requests: Number(policyForm.max_concurrent_requests),
        max_context_turns: Number(policyForm.max_context_turns),
        max_document_mb: Number(policyForm.max_document_mb),
        reason: policyForm.reason.trim(),
      })
      setAccount(updated)
      dispatch(setCreditAccount(updated))
      setPolicyForm((prev) => ({ ...prev, reason: '' }))
      dispatch(addToast({ title: 'Policies Saved', message: 'Workspace AI quota policies updated.', type: 'success' }))
    } catch (err) {
      dispatch(addToast({ title: 'Update Failed', message: err.message, type: 'error' }))
    } finally {
      setPolicyBusy(false)
    }
  }

  const handleRecoverDoc = async (docId, mode) => {
    setBusyRecoverId(docId)
    try {
      const updated = await api.recoverAiIngestion(docId, {
        mode,
        reason: `Admin triggered ${mode} from AI Usage dashboard`,
      })
      dispatch(
        addToast({
          title: 'Recovery Triggered',
          message: `${updated.title} (${updated.status})`,
          type: updated.status === 'COMPLETED' ? 'success' : 'info',
        })
      )
      await Promise.all([loadCoreData(), loadLogs(0)])
    } catch (err) {
      dispatch(addToast({ title: 'Recovery Failed', message: err.message, type: 'error' }))
    } finally {
      setBusyRecoverId(null)
    }
  }

  if (loading && !account) {
    return <LoadingState message={t('common.loading')} />
  }

  const totals = summary?.totals || {}

  return (
    <div className="page-container">
      <PageHeader
        title={t('ai.aiUsageTitle')}
        subtitle={t('ai.aiUsageSubtitle')}
        actions={
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <select
              className="form-control"
              style={{ width: 'auto' }}
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              aria-label="Reporting window"
            >
              <option value={7}>Last 7 Days</option>
              <option value={30}>Last 30 Days</option>
              <option value={90}>Last 90 Days</option>
            </select>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                loadCoreData()
                loadTransactions(txPage.offset)
                loadLogs(logsPage.offset)
              }}
            >
              <RefreshCw size={15} /> {t('common.refresh')}
            </button>
          </div>
        }
      />

      {account && account.status === 'SUSPENDED' && (
        <div className="ai-rate-banner" style={{ borderColor: 'var(--status-danger-text)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--status-danger-text)' }}>
            <ShieldAlert size={18} />
            <strong>AI Assistant Suspended for this Workspace</strong>
          </div>
          <span className="badge badge-danger">SUSPENDED</span>
        </div>
      )}

      {pricing && (
        <div className="ai-rate-banner">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
            <Info size={16} color="var(--erp-primary)" />
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                Pricing Schedule ({pricing.pricing_version})
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>
                {pricing.approval_notice}
              </div>
            </div>
          </div>
          <span className={`badge ${pricing.rate_approval_required ? 'badge-warning' : 'badge-success'}`}>
            {pricing.rate_approval_required ? 'Configurable Default Rates' : 'Commercial Rates Active'}
          </span>
        </div>
      )}

      <div className="kpi-grid" style={{ marginBottom: '1.25rem' }}>
        <KpiCard
          label="Available AI Credits"
          value={Number(account?.available_credits || 0).toFixed(3)}
          subtitle={`Reserved in-flight: ${Number(account?.reserved_credits || 0).toFixed(3)} cr • ${account?.plan_tier || 'starter'}`}
          icon={Coins}
          variant={
            Number(account?.available_credits || 0) <= 0
              ? 'rose'
              : Number(account?.available_credits || 0) <= 10
              ? 'amber'
              : 'emerald'
          }
        />
        <KpiCard
          label={`Consumed (${windowDays}d)`}
          value={Number(totals.credits_consumed || 0).toFixed(3)}
          subtitle={`Lifetime consumed: ${Number(account?.lifetime_consumed_credits || 0).toFixed(3)} cr`}
          icon={TrendingUp}
          variant="blue"
        />
        <KpiCard
          label={`Requests & Tokens (${windowDays}d)`}
          value={`${totals.successful_requests || 0} / ${totals.requests || 0}`}
          subtitle={`${Number(totals.total_tokens || 0).toLocaleString()} total tokens`}
          icon={Cpu}
          variant="default"
        />
        <KpiCard
          label="Refunded & Quota Events"
          value={Number(totals.credits_refunded || 0).toFixed(3)}
          subtitle={`Provider quota failures: ${totals.provider_quota_failures || 0}`}
          icon={Activity}
          variant={Number(totals.provider_quota_failures || 0) > 0 ? 'amber' : 'emerald'}
        />
      </div>

      <div className="ai-tab-bar">
        <button
          type="button"
          className={`btn ${activeTab === 'overview' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('overview')}
        >
          <TrendingUp size={15} /> Usage Breakdown
        </button>
        <button
          type="button"
          className={`btn ${activeTab === 'ledger' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('ledger')}
        >
          <Coins size={15} /> Credit Ledger ({txPage.total})
        </button>
        <button
          type="button"
          className={`btn ${activeTab === 'logs' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('logs')}
        >
          <History size={15} /> Request History ({logsPage.total})
        </button>
        {canManageCredits && (
          <button
            type="button"
            className={`btn ${activeTab === 'admin' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab('admin')}
          >
            <SlidersHorizontal size={15} /> Admin Controls & Recovery
          </button>
        )}
      </div>

      {activeTab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="ai-admin-grid">
            <ChartCard
              title="Daily AI Credit Consumption & Refunds"
              subtitle={`Last ${windowDays} days`}
              isEmpty={(summary?.daily_trends || []).length === 0}
              emptyText="No metered AI usage recorded in this window."
            >
              <Bar
                data={trendChartData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: { legend: { position: 'bottom' } },
                }}
              />
            </ChartCard>

            <div className="table-card" style={{ padding: '1rem' }}>
              <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '0.96rem' }}>
                Workspace Rate & Quota Policies
              </h3>
              {account?.limits && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.65rem', fontSize: '0.85rem' }}>
                  <div><strong>Plan Tier:</strong> {account.plan_tier}</div>
                  <div><strong>Status:</strong> {account.status}</div>
                  <div><strong>RPM Limit:</strong> {account.limits.rpm_limit} / min</div>
                  <div><strong>Daily Requests:</strong> {account.limits.daily_request_limit} / day</div>
                  <div><strong>Daily Token Cap:</strong> {Number(account.limits.daily_token_limit).toLocaleString()}</div>
                  <div><strong>Max Cost / Req:</strong> {account.limits.max_credits_per_operation} cr</div>
                  <div><strong>Max Concurrent:</strong> {account.limits.max_concurrent_requests}</div>
                  <div><strong>Max Doc Upload:</strong> {account.limits.max_document_mb} MB</div>
                </div>
              )}

              <h4 style={{ margin: '1rem 0 0.5rem 0', fontSize: '0.9rem' }}>By Operation</h4>
              {(summary?.by_operation || []).length === 0 ? (
                <div style={{ fontSize: '0.84rem', color: 'var(--erp-text-muted)' }}>No operations recorded yet.</div>
              ) : (
                <table className="erp-table">
                  <thead>
                    <tr>
                      <th>Operation</th>
                      <th>Requests</th>
                      <th>Tokens</th>
                      <th>Credits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_operation.map((op) => (
                      <tr key={op.operation_type}>
                        <td>{op.operation_type}</td>
                        <td>{op.requests}</td>
                        <td>{Number(op.total_tokens || 0).toLocaleString()}</td>
                        <td>{Number(op.credits_consumed || 0).toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {pricing && (
            <div className="table-card" style={{ padding: '1rem' }}>
              <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '0.96rem' }}>Active Credit Tariff</h3>
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Capability</th>
                    <th>Base Fee</th>
                    <th>Metered Unit Rate</th>
                    <th>Minimum</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>AI Assistant Chat ({pricing.pricing_version})</td>
                    <td>{pricing.text_generation?.base_credits} cr</td>
                    <td>
                      {pricing.text_generation?.input_credits_per_1k_tokens} cr / 1K input tokens •{' '}
                      {pricing.text_generation?.output_credits_per_1k_tokens} cr / 1K output tokens
                    </td>
                    <td>{pricing.text_generation?.min_credits} cr</td>
                  </tr>
                  <tr>
                    <td>Embeddings & Semantic Query</td>
                    <td>{pricing.embedding?.base_credits} cr</td>
                    <td>{pricing.embedding?.credits_per_1k_tokens} cr / 1K tokens</td>
                    <td>{pricing.embedding?.min_credits} cr</td>
                  </tr>
                  <tr>
                    <td>Document Ingestion Batch</td>
                    <td>{pricing.document_ingestion?.base_credits} cr</td>
                    <td>{pricing.document_ingestion?.per_chunk_credits} cr / chunk + token usage</td>
                    <td>{pricing.embedding?.min_credits} cr</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'ledger' && (
        <div className="table-card">
          <div className="ai-filter-bar">
            <select
              className="form-control"
              style={{ maxWidth: '220px' }}
              value={txFilter}
              onChange={(e) => setTxFilter(e.target.value)}
            >
              <option value="">All Transaction Types</option>
              <option value="INITIAL_GRANT">Initial Grant</option>
              <option value="PURCHASE">Purchase</option>
              <option value="PROMOTIONAL_CREDIT">Promotional Credit</option>
              <option value="PLAN_ALLOCATION">Plan Allocation</option>
              <option value="MANUAL_ADJUSTMENT">Manual Adjustment</option>
              <option value="REQUEST_RESERVATION">Reservation</option>
              <option value="REQUEST_CAPTURE">Capture</option>
              <option value="REQUEST_REFUND">Refund</option>
              <option value="EXPIRATION">Expiration</option>
            </select>
          </div>
          {txPage.items.length === 0 ? (
            <EmptyState
              title="No credit transactions yet"
              message="Credit grants, reservations, captures, and refunds appear here automatically."
            />
          ) : (
            <div className="table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Delta</th>
                    <th>Balance After</th>
                    <th>Reserved After</th>
                    <th>Reason</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {txPage.items.map((tx) => (
                    <tr key={tx.id}>
                      <td>
                        <span className={`badge ${TX_BADGE[tx.transaction_type] || 'badge-neutral'}`}>
                          {tx.transaction_type}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600 }}>
                        {tx.credit_change > 0
                          ? `+${Number(tx.credit_change).toFixed(3)}`
                          : tx.credit_change < 0
                          ? Number(tx.credit_change).toFixed(3)
                          : `(${Number(tx.amount).toFixed(3)})`}
                      </td>
                      <td>{Number(tx.available_after).toFixed(3)}</td>
                      <td>{Number(tx.reserved_after).toFixed(3)}</td>
                      <td>{tx.reason}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)' }}>
                        {tx.created_at ? new Date(tx.created_at).toLocaleString() : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.75rem 1rem' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
              Showing {txPage.items.length} of {txPage.total}
            </span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                type="button"
                className="btn-xs btn-secondary"
                disabled={txPage.offset === 0}
                onClick={() => loadTransactions(Math.max(0, txPage.offset - txPage.limit))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-xs btn-secondary"
                disabled={txPage.offset + txPage.limit >= txPage.total}
                onClick={() => loadTransactions(txPage.offset + txPage.limit)}
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'logs' && (
        <div className="table-card">
          <div className="ai-filter-bar">
            <select
              className="form-control"
              style={{ maxWidth: '170px' }}
              value={logStatusFilter}
              onChange={(e) => setLogStatusFilter(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="ok">Completed (ok)</option>
              <option value="error">Failed / Refunded</option>
              <option value="reserved">Reserved</option>
            </select>
            <select
              className="form-control"
              style={{ maxWidth: '190px' }}
              value={logOpFilter}
              onChange={(e) => setLogOpFilter(e.target.value)}
            >
              <option value="">All Operations</option>
              <option value="chat_rag">Chat Assistant</option>
              <option value="ingestion_embed">Document Ingestion</option>
              <option value="query_embed">Knowledge Retrieval</option>
            </select>
          </div>
          {logsPage.items.length === 0 ? (
            <EmptyState title="No AI request logs yet" message="Every metered AI call is audited here." />
          ) : (
            <div className="table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Operation / Model</th>
                    <th>Status</th>
                    <th>Tokens (In / Out)</th>
                    <th>Consumed / Refunded</th>
                    <th>Source</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {logsPage.items.map((log) => (
                    <tr key={log.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{log.operation_type}</div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                          {log.model_name || '-'}
                        </div>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            log.status === 'ok'
                              ? 'badge-success'
                              : log.status === 'error'
                              ? 'badge-danger'
                              : 'badge-warning'
                          }`}
                        >
                          {log.status}
                        </span>
                        {log.error_code && (
                          <div style={{ fontSize: '0.74rem', color: 'var(--status-danger-text)', marginTop: '0.2rem' }}>
                            {log.error_code} ({log.error_category || 'error'})
                          </div>
                        )}
                      </td>
                      <td>
                        {log.total_tokens} ({log.prompt_tokens} / {log.candidates_tokens})
                      </td>
                      <td>
                        <strong>{Number(log.credits_consumed).toFixed(3)}</strong> cr
                        {log.credits_refunded > 0 && (
                          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                            Refunded: {Number(log.credits_refunded).toFixed(3)} cr
                          </div>
                        )}
                      </td>
                      <td>{log.usage_source}</td>
                      <td>{log.duration_ms ? `${Math.round(log.duration_ms)} ms` : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.75rem 1rem' }}>
            <span style={{ fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
              Showing {logsPage.items.length} of {logsPage.total}
            </span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                type="button"
                className="btn-xs btn-secondary"
                disabled={logsPage.offset === 0}
                onClick={() => loadLogs(Math.max(0, logsPage.offset - logsPage.limit))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-xs btn-secondary"
                disabled={logsPage.offset + logsPage.limit >= logsPage.total}
                onClick={() => loadLogs(logsPage.offset + logsPage.limit)}
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'admin' && canManageCredits && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div className="ai-admin-grid">
            <form className="table-card" style={{ padding: '1rem' }} onSubmit={handleAdjustCredits}>
              <h3 style={{ margin: '0 0 0.85rem 0', fontSize: '0.98rem' }}>
                Adjust Workspace AI Credits
              </h3>
              <div className="form-group">
                <label className="form-label">Transaction Type</label>
                <select
                  className="form-control"
                  value={adjType}
                  onChange={(e) => setAdjType(e.target.value)}
                >
                  <option value="PURCHASE">Purchase Allocation</option>
                  <option value="PROMOTIONAL_CREDIT">Promotional Grant</option>
                  <option value="PLAN_ALLOCATION">Monthly Plan Allocation</option>
                  <option value="MANUAL_ADJUSTMENT">Manual Adjustment (+/-)</option>
                  <option value="EXPIRATION">Expire Credits (-)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="ai-adj-amount">
                  Credit Amount <span className="required">*</span>
                </label>
                <input
                  id="ai-adj-amount"
                  type="number"
                  step="0.001"
                  className="form-control"
                  placeholder="e.g. 500"
                  value={adjAmount}
                  onChange={(e) => setAdjAmount(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Audit Reason (required)</label>
                <input
                  type="text"
                  className="form-control"
                  value={adjReason}
                  onChange={(e) => setAdjReason(e.target.value)}
                  placeholder="e.g. Top-up Pack #INV-2045"
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Billing Reference (optional)</label>
                <input
                  type="text"
                  className="form-control"
                  value={adjRef}
                  onChange={(e) => setAdjRef(e.target.value)}
                  placeholder="Invoice or ticket ID"
                />
              </div>
              <button type="submit" className="btn btn-primary" disabled={adjBusy}>
                {adjBusy ? 'Applying...' : 'Apply Credit Adjustment'}
              </button>
            </form>

            <form className="table-card" style={{ padding: '1rem' }} onSubmit={handleSavePolicies}>
              <h3 style={{ margin: '0 0 0.85rem 0', fontSize: '0.98rem' }}>
                Rate Limits, Daily Quotas & AI Access Policy
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.65rem' }}>
                <div className="form-group">
                  <label className="form-label">AI Status</label>
                  <select
                    className="form-control"
                    value={policyForm.status}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, status: e.target.value }))}
                  >
                    <option value="ACTIVE">ACTIVE</option>
                    <option value="SUSPENDED">SUSPENDED</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="ai-plan-tier">Plan Tier</label>
                  <input
                    id="ai-plan-tier"
                    type="text"
                    className="form-control"
                    placeholder="e.g. standard"
                    value={policyForm.plan_tier}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, plan_tier: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="ai-rpm-limit">Requests / Min</label>
                  <input
                    id="ai-rpm-limit"
                    type="number"
                    className="form-control"
                    placeholder="e.g. 20"
                    value={policyForm.rpm_limit}
                    onChange={(e) => setPolicyForm((p) => ({ ...p, rpm_limit: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="ai-daily-req-limit">Daily Requests</label>
                  <input
                    id="ai-daily-req-limit"
                    type="number"
                    className="form-control"
                    placeholder="e.g. 500"
                    value={policyForm.daily_request_limit}
                    onChange={(e) =>
                      setPolicyForm((p) => ({ ...p, daily_request_limit: e.target.value }))
                    }
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="ai-daily-token-limit">Daily Token Limit</label>
                  <input
                    id="ai-daily-token-limit"
                    type="number"
                    className="form-control"
                    placeholder="e.g. 250000"
                    value={policyForm.daily_token_limit}
                    onChange={(e) =>
                      setPolicyForm((p) => ({ ...p, daily_token_limit: e.target.value }))
                    }
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="ai-max-credits-op">Max Credits / Req</label>
                  <input
                    id="ai-max-credits-op"
                    type="number"
                    step="0.5"
                    className="form-control"
                    placeholder="e.g. 50"
                    value={policyForm.max_credits_per_operation}
                    onChange={(e) =>
                      setPolicyForm((p) => ({ ...p, max_credits_per_operation: e.target.value }))
                    }
                  />
                </div>
              </div>
              <div className="form-group">
                <label className="form-label">Policy Update Reason (required)</label>
                <input
                  type="text"
                  className="form-control"
                  value={policyForm.reason}
                  onChange={(e) => setPolicyForm((p) => ({ ...p, reason: e.target.value }))}
                  placeholder="e.g. Increased RPM for peak audit week"
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary" disabled={policyBusy}>
                {policyBusy ? 'Saving...' : 'Save Quota Policies'}
              </button>
            </form>
          </div>

          <div className="table-card" style={{ padding: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ margin: 0, fontSize: '0.98rem' }}>Paused & Failed Document Ingestion Recovery</h3>
              <button
                type="button"
                className="btn-xs btn-secondary"
                onClick={() => navigate('/ai-knowledge')}
              >
                Open Knowledge Base
              </button>
            </div>
            {!adminFailures?.paused_documents?.length ? (
              <div style={{ fontSize: '0.86rem', color: 'var(--erp-text-muted)' }}>
                No paused or failed ingestion jobs in this workspace.
              </div>
            ) : (
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Status / Error Category</th>
                    <th>Indexed Progress</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {adminFailures.paused_documents.map((doc) => (
                    <tr key={doc.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{doc.title}</div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                          {doc.error_message || doc.error_code}
                        </div>
                      </td>
                      <td>
                        <span className="badge badge-warning">{doc.status}</span>
                        {doc.last_error_category && (
                          <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                            Category: {doc.last_error_category}
                          </div>
                        )}
                      </td>
                      <td>
                        {doc.indexed_chunks} / {doc.total_chunks}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                          <button
                            type="button"
                            className="btn-xs btn-primary"
                            disabled={busyRecoverId === doc.id}
                            onClick={() => handleRecoverDoc(doc.id, 'retry')}
                          >
                            <RotateCcw size={12} /> Resume
                          </button>
                          <button
                            type="button"
                            className="btn-xs btn-secondary"
                            disabled={busyRecoverId === doc.id}
                            onClick={() => handleRecoverDoc(doc.id, 'reindex')}
                          >
                            <AlertTriangle size={12} /> Reindex
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
