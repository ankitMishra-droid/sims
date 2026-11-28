import { useState, useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  BrainCircuit,
  Award,
  RefreshCw,
  AlertCircle,
  Info,
  ShieldCheck,
  Database,
  Calendar,
} from 'lucide-react'
import { Line, Bar } from 'react-chartjs-2'
import { getChartTheme } from '../components/charts/ChartSetup'
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { addToast } from '../store/uiSlice'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import { LoadingState, ErrorState } from '../components/common/StateBlocks'

const PRIMARY_DISPLAY_NAMES = ['ARIMA', 'XGBoost', 'Random Forest', 'LSTM']

const INTERNAL_TO_PRIMARY_DISPLAY = {
  'ARIMA(1, 1, 1)': 'ARIMA',
  XGBoost: 'XGBoost',
  RandomForest: 'Random Forest',
  LSTMSequenceNetwork: 'LSTM',
}

const HISTORY_PRESETS = [
  { key: '30', label: '30D', days: 30 },
  { key: '90', label: '90D', days: 90 },
  { key: '180', label: '6M', days: 180 },
  { key: '365', label: '1Y', days: 365 },
  { key: '730', label: '2Y', days: 730 },
  { key: '1095', label: '3Y', days: 1095 },
  { key: '1825', label: '5Y', days: 1825 },
  { key: '2555', label: '7Y', days: 2555 },
  { key: '3650', label: '10Y', days: 3650 },
  { key: '0', label: 'All', days: 0 },
  { key: 'custom', label: 'Custom', days: null },
]

function formatMetric(value, suffix = '', digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  return `${num.toFixed(digits)}${suffix}`
}

function formatBias(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(2)}`
}

export default function ForecastingPage() {
  const dispatch = useDispatch()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const rawProducts = useSelector(selectAllProducts)
  const theme = useSelector((state) => state.ui.theme)
  const chartColors = getChartTheme(theme === 'dark')
  const products = useMemo(() => (Array.isArray(rawProducts) ? rawProducts : []), [rawProducts])

  const queryProductId = searchParams.get('product_id') || ''
  const [selectedProductId, setSelectedProductId] = useState(queryProductId)
  const [horizonDays, setHorizonDays] = useState(30)
  const [selectedModel, setSelectedModel] = useState('auto')

  const [historyPreset, setHistoryPreset] = useState('180')
  const [customStartDate, setCustomStartDate] = useState('')
  const [customEndDate, setCustomEndDate] = useState('')
  const [historyResolution, setHistoryResolution] = useState('auto')

  const [forecastData, setForecastData] = useState(null)
  const [evaluationData, setEvaluationData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState(null)
  const [modelEligibilityError, setModelEligibilityError] = useState(null)

  const prevProductRef = useRef('')
  const forecastProductIdRef = useRef(null)
  const activeProductId = selectedProductId || queryProductId || (products[0] ? String(products[0].id) : '')
  const activeProductObj = useMemo(
    () => products.find((p) => String(p.id) === String(activeProductId)) || null,
    [products, activeProductId]
  )

  const customDateInvalid =
    historyPreset === 'custom' &&
    Boolean(customStartDate) &&
    Boolean(customEndDate) &&
    customStartDate > customEndDate

  const historyRequestOpts = useMemo(() => {
    if (historyPreset === 'custom') {
      return {
        historyDays: 0,
        historyStartDate: customStartDate || null,
        historyEndDate: customEndDate || null,
        historyResolution,
      }
    }
    const presetObj = HISTORY_PRESETS.find((p) => p.key === historyPreset)
    return {
      historyDays: presetObj ? presetObj.days : 180,
      historyResolution,
    }
  }, [historyPreset, customStartDate, customEndDate, historyResolution])

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  // Load persisted or fresh leaderboard strictly when selected product changes
  useEffect(() => {
    if (!activeProductId) return
    let active = true
    const switchedProduct = prevProductRef.current !== activeProductId
    if (switchedProduct) {
      prevProductRef.current = activeProductId
      setModelEligibilityError(null)
    }
    api
      .getProductEvaluations(activeProductId, 14, false)
      .then((eData) => {
        if (active) setEvaluationData(eData)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [activeProductId])

  // Load forecast & custom chart window whenever product, horizon, model, or graph range changes
  useEffect(() => {
    if (!activeProductId || customDateInvalid) return
    let active = true
    const loadForecast = async () => {
      setLoading(true)
      setError(null)
      setModelEligibilityError(null)
      try {
        const fData = await api.getIntelligenceProductForecast(
          activeProductId,
          horizonDays,
          selectedModel,
          false,
          historyRequestOpts
        )
        if (active) {
          forecastProductIdRef.current = String(fData?.product_id ?? activeProductId)
          setForecastData(fData)
          const minAvail = fData?.history_window_meta?.available_min_date
          const maxAvail = fData?.history_window_meta?.available_max_date
          if (!customStartDate && minAvail) setCustomStartDate(minAvail)
          if (!customEndDate && maxAvail) setCustomEndDate(maxAvail)
        }
      } catch (err) {
        if (!active) return
        const msg = err.message || 'Failed to load forecast.'
        if (selectedModel !== 'auto' && forecastProductIdRef.current === String(activeProductId)) {
          setModelEligibilityError(msg)
        } else {
          forecastProductIdRef.current = null
          setError(msg)
          setForecastData(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    loadForecast()
    return () => {
      active = false
    }
  }, [activeProductId, horizonDays, selectedModel, historyRequestOpts, customDateInvalid, customStartDate, customEndDate])

  const handleRefreshModel = async () => {
    if (!activeProductId || customDateInvalid) return
    setComparing(true)
    setError(null)
    setModelEligibilityError(null)
    try {
      const [forecastOutcome, evalOutcome] = await Promise.allSettled([
        api.getIntelligenceProductForecast(
          activeProductId,
          horizonDays,
          selectedModel,
          true,
          historyRequestOpts
        ),
        api.getProductEvaluations(activeProductId, 14, true),
      ])

      if (evalOutcome.status === 'fulfilled') {
        setEvaluationData(evalOutcome.value)
      }

      if (forecastOutcome.status === 'fulfilled') {
        const fData = forecastOutcome.value
        forecastProductIdRef.current = String(fData?.product_id ?? activeProductId)
        setForecastData(fData)
        dispatch(addToast({ type: 'success', message: 'Rolling-origin evaluation & forecast updated.' }))
      } else {
        const msg = forecastOutcome.reason?.message || 'Failed to refresh forecast.'
        if (selectedModel !== 'auto' && forecastProductIdRef.current === String(activeProductId)) {
          setModelEligibilityError(msg)
        } else {
          setError(msg)
        }
        dispatch(addToast({ type: 'error', message: msg }))
      }
    } catch (err) {
      const msg = err.message || 'Failed to refresh evaluation.'
      setError(msg)
      dispatch(addToast({ type: 'error', message: msg }))
    } finally {
      setComparing(false)
    }
  }

  const handleProductChange = (newProdId) => {
    setSelectedProductId(newProdId)
    setCustomStartDate('')
    setCustomEndDate('')
    setModelEligibilityError(null)
    setError(null)
  }

  const primaryLeaderboard = useMemo(() => {
    const rawPrimary = Array.isArray(evaluationData?.primary_leaderboard)
      ? evaluationData.primary_leaderboard
      : Array.isArray(forecastData?.primary_leaderboard)
      ? forecastData.primary_leaderboard
      : []

    if (rawPrimary.length > 0) {
      const byDisplay = {}
      for (const row of rawPrimary) {
        const disp = row.display_name || INTERNAL_TO_PRIMARY_DISPLAY[row.model_name]
        if (disp) byDisplay[disp] = { ...row, display_name: disp }
      }
      return PRIMARY_DISPLAY_NAMES.map((name) => byDisplay[name]).filter(Boolean)
    }

    const full = Array.isArray(evaluationData?.leaderboard) ? evaluationData.leaderboard : []
    const byDisplay = {}
    for (const row of full) {
      const disp = row.display_name || INTERNAL_TO_PRIMARY_DISPLAY[row.model_name]
      if (disp && PRIMARY_DISPLAY_NAMES.includes(disp)) {
        byDisplay[disp] = { ...row, display_name: disp }
      }
    }
    return PRIMARY_DISPLAY_NAMES.map((name) => byDisplay[name]).filter(Boolean)
  }, [evaluationData, forecastData])

  const evaluatedPrimaryRows = useMemo(
    () => primaryLeaderboard.filter((r) => r.status === 'EVALUATED'),
    [primaryLeaderboard]
  )

  const combinedChart = useMemo(() => {
    const histPts = Array.isArray(forecastData?.historical_series) ? forecastData.historical_series : []
    const futPts = Array.isArray(forecastData?.forecast_series) ? forecastData.forecast_series : []
    const dense = histPts.length > 180
    const resMode = forecastData?.history_window_meta?.resolution_used || 'daily'
    const histLabel =
      resMode === 'monthly'
        ? 'Historical Avg Daily Demand (Monthly)'
        : resMode === 'weekly'
        ? 'Historical Avg Daily Demand (Weekly)'
        : 'Historical Daily Demand'

    const labels = [...histPts.map((p) => p.date), ...futPts.map((p) => p.date)]
    const actualData = [...histPts.map((p) => p.actual_demand), ...futPts.map(() => null)]
    const bridgeIdx = histPts.length > 0 ? histPts[histPts.length - 1].actual_demand : null
    const forecastLine = [
      ...histPts.map((_, idx) => (idx === histPts.length - 1 ? bridgeIdx : null)),
      ...futPts.map((p) => p.predicted_demand),
    ]
    const upperLine = [...histPts.map(() => null), ...futPts.map((p) => p.upper_bound ?? null)]
    const lowerLine = [...histPts.map(() => null), ...futPts.map((p) => p.lower_bound ?? null)]

    return {
      labels,
      datasets: [
        {
          label: histLabel,
          data: actualData,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          borderWidth: dense ? 1.75 : 2,
          pointRadius: dense ? 0 : 1.5,
          tension: 0.25,
        },
        {
          label: 'Upper 95% Interval',
          data: upperLine,
          borderColor: 'rgba(16, 185, 129, 0.25)',
          backgroundColor: 'rgba(16, 185, 129, 0.08)',
          borderWidth: 1,
          pointRadius: 0,
          fill: '+2',
          tension: 0.25,
        },
        {
          label: `Forecast (${forecastData?.model_display_name || forecastData?.model_used || 'Auto'})`,
          data: forecastLine,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.2)',
          borderWidth: 2.5,
          borderDash: [6, 4],
          pointRadius: 2,
          tension: 0.25,
        },
        {
          label: 'Lower 95% Interval',
          data: lowerLine,
          borderColor: 'rgba(16, 185, 129, 0.25)',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.25,
        },
      ],
    }
  }, [forecastData])

  const backtestPoints = useMemo(() => {
    const ePts = evaluationData?.backtest_comparison
    if (Array.isArray(ePts) && ePts.length > 0) return ePts
    const fPts = forecastData?.backtest_comparison
    return Array.isArray(fPts) ? fPts : []
  }, [evaluationData, forecastData])

  const backtestChart = useMemo(() => {
    return {
      labels: backtestPoints.map((p) => p.date),
      datasets: [
        {
          label: 'Actual (Held-Out Fold)',
          data: backtestPoints.map((p) => p.actual),
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37, 99, 235, 0.12)',
          borderWidth: 2,
          pointRadius: 2.5,
          tension: 0.2,
        },
        {
          label: 'Predicted (Held-Out Fold)',
          data: backtestPoints.map((p) => p.predicted),
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          borderWidth: 2,
          borderDash: [5, 4],
          pointRadius: 2.5,
          tension: 0.2,
        },
      ],
    }
  }, [backtestPoints])

  const errorComparisonChart = useMemo(() => {
    return {
      labels: evaluatedPrimaryRows.map((r) => r.display_name || r.model_name),
      datasets: [
        {
          label: 'MAE (units/day)',
          data: evaluatedPrimaryRows.map((r) => Number(r.mae ?? 0)),
          backgroundColor: 'rgba(59, 130, 246, 0.78)',
          borderRadius: 4,
        },
        {
          label: 'RMSE (units/day)',
          data: evaluatedPrimaryRows.map((r) => Number(r.rmse ?? 0)),
          backgroundColor: 'rgba(139, 92, 246, 0.78)',
          borderRadius: 4,
        },
      ],
    }
  }, [evaluatedPrimaryRows])

  const biasComparisonChart = useMemo(() => {
    return {
      labels: evaluatedPrimaryRows.map((r) => r.display_name || r.model_name),
      datasets: [
        {
          label: 'Forecast Bias (Predicted − Actual)',
          data: evaluatedPrimaryRows.map((r) => Number(r.bias ?? 0)),
          backgroundColor: evaluatedPrimaryRows.map((r) =>
            Number(r.bias ?? 0) > 0 ? 'rgba(245, 158, 11, 0.8)' : 'rgba(16, 185, 129, 0.8)'
          ),
          borderRadius: 4,
        },
      ],
    }
  }, [evaluatedPrimaryRows])

  const chartOptions = useMemo(() => {
    const histPts = Array.isArray(forecastData?.historical_series) ? forecastData.historical_series : []
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: chartColors.textColor } },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              if (!items || !items.length) return ''
              const idx = items[0].dataIndex
              const pt = histPts[idx]
              if (!pt) return ''
              const parts = []
              if (pt.bucket_days > 1) {
                parts.push(`Bucket Total: ${pt.total_demand} units (${pt.bucket_days} days)`)
              }
              if (pt.stockout_days > 0) {
                parts.push(`Stockout days in period: ${pt.stockout_days}`)
              }
              return parts
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: chartColors.textColor, maxTicksLimit: 12 },
          grid: { color: chartColors.gridColor },
        },
        y: {
          beginAtZero: true,
          ticks: { color: chartColors.textColor },
          grid: { color: chartColors.gridColor },
        },
      },
    }
  }, [chartColors, forecastData])

  const barChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: chartColors.textColor } },
    },
    scales: {
      x: {
        ticks: { color: chartColors.textColor },
        grid: { color: chartColors.gridColor },
      },
      y: {
        ticks: { color: chartColors.textColor },
        grid: { color: chartColors.gridColor },
      },
    },
  }

  const histSummary = forecastData?.historical_summary || {}
  const evalSummary = forecastData?.evaluation_metrics || {}
  const dataQuality = forecastData?.data_quality || evaluationData?.data_quality || {}
  const historyWindowMeta = forecastData?.history_window_meta || {}
  const hasSyntheticData = Boolean(
    forecastData?.has_synthetic_data || dataQuality?.has_synthetic_data || activeProductObj?.is_synthetic
  )
  const fallbackUsed = Boolean(forecastData?.fallback_used || forecastData?.is_cold_start)
  const championDisplay =
    forecastData?.model_display_name ||
    INTERNAL_TO_PRIMARY_DISPLAY[forecastData?.model_used] ||
    forecastData?.model_used ||
    '—'

  const observedDays = Number(histSummary.total_historical_days ?? 0)
  const nonZeroDays = Number(histSummary.non_zero_demand_days ?? 0)
  const arimaInsufficient = forecastData && (observedDays < 24 || nonZeroDays < 10)
  const treeInsufficient = forecastData && (observedDays < 36 || nonZeroDays < 12)
  const lstmInsufficient = forecastData && (observedDays < 60 || nonZeroDays < 25)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <PageHeader
        title={t('nav.demandForecasts')}
        subtitle="Multi-horizon demand forecasting across ARIMA, XGBoost, Random Forest, and LSTM with customizable historical viewing up to 10 years."
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleRefreshModel}
            disabled={comparing || !activeProductId || customDateInvalid}
          >
            <RefreshCw size={15} className={comparing ? 'spin-icon' : ''} />
            <span>{comparing ? 'Evaluating...' : t('intelligence.refreshModels')}</span>
          </button>
        }
      />

      {/* Filter Controls */}
      <section className="section-card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0.875rem' }}>
          <div className="form-group">
            <label className="form-label" htmlFor="forecast-product-select">Product</label>
            <select
              id="forecast-product-select"
              className="form-control"
              value={activeProductId}
              onChange={(e) => handleProductChange(e.target.value)}
            >
              {products.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.sku} — {p.name}{p.is_synthetic ? ' [Synthetic Demo]' : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="forecast-horizon-select">Forecast Horizon</label>
            <select
              id="forecast-horizon-select"
              className="form-control"
              value={horizonDays}
              onChange={(e) => setHorizonDays(Number(e.target.value))}
            >
              <option value={7}>7 Days</option>
              <option value={14}>14 Days</option>
              <option value={30}>30 Days</option>
              <option value={60}>60 Days</option>
              <option value={90}>90 Days</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="forecast-model-select">Forecast Algorithm</label>
            <select
              id="forecast-model-select"
              className="form-control"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              <option value="auto">Auto (Champion Selection)</option>
              <option value="arima">
                ARIMA{arimaInsufficient ? ' (Needs >=24d / 10 sales)' : ''}
              </option>
              <option value="xgboost">
                XGBoost{treeInsufficient ? ' (Needs >=36d / 12 sales)' : ''}
              </option>
              <option value="random_forest">
                Random Forest{treeInsufficient ? ' (Needs >=36d / 12 sales)' : ''}
              </option>
              <option value="lstm">
                LSTM{lstmInsufficient ? ' (Needs >=60d / 25 sales)' : ''}
              </option>
            </select>
          </div>
        </div>
      </section>

      {modelEligibilityError && (
        <div
          className="section-card"
          style={{
            borderLeft: '4px solid #ef4444',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '0.75rem',
            flexWrap: 'wrap',
            background: 'var(--erp-surface-subtle)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.875rem' }}>
            <AlertCircle size={18} style={{ color: '#dc2626', flexShrink: 0 }} />
            <span>
              <strong>Model Eligibility Notice:</strong> {modelEligibilityError}
            </span>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setSelectedModel('auto')}
          >
            Switch to Auto (Champion Selection)
          </button>
        </div>
      )}

      {error && <ErrorState message={error} onRetry={handleRefreshModel} />}
      {loading && !forecastData ? (
        <LoadingState message="Computing historical demand profile and forecast..." />
      ) : forecastData ? (
        <>
          {hasSyntheticData && (
            <div
              className="section-card"
              style={{
                borderLeft: '4px solid #6366f1',
                display: 'flex',
                gap: '0.75rem',
                alignItems: 'center',
                background: 'var(--erp-surface-subtle)',
              }}
            >
              <Database size={18} style={{ color: '#4f46e5', flexShrink: 0 }} />
              <div style={{ fontSize: '0.85rem' }}>
                <strong>{t('intelligence.syntheticDatasetNotice', 'Includes Synthetic / Demo Historical Data')}</strong>
                <span style={{ color: 'var(--erp-text-secondary)', marginLeft: '0.5rem' }}>
                  ({dataQuality.synthetic_records_count ?? 0} synthetic record(s), {dataQuality.genuine_records_count ?? 0} genuine record(s) — marked explicitly as demo history).
                </span>
              </div>
            </div>
          )}

          {fallbackUsed && (
            <div
              className="section-card"
              style={{
                borderLeft: '4px solid #f59e0b',
                display: 'flex',
                gap: '0.75rem',
                alignItems: 'flex-start',
                background: 'var(--erp-surface-subtle)',
              }}
            >
              <Info size={18} style={{ color: '#d97706', marginTop: '2px', flexShrink: 0 }} />
              <div style={{ fontSize: '0.875rem' }}>
                <strong>
                  {t('intelligence.baselineFallbackBanner', 'Baseline Fallback Active')} ({forecastData.data_sufficiency} • {championDisplay})
                </strong>
                <div style={{ color: 'var(--erp-text-secondary)', marginTop: '0.25rem' }}>
                  {forecastData.selection_reason} Primary ML models promote automatically once minimum sample thresholds and out-of-sample error reduction targets are satisfied ({histSummary.total_historical_days || 0} calendar days observed, {histSummary.non_zero_demand_days || 0} non-zero sales days).
                </div>
              </div>
            </div>
          )}

          <div className="kpi-grid">
            <KpiCard
              label="Selected Champion Model"
              value={championDisplay}
              subtitle={`${forecastData.champion_is_ml ? 'ML Champion' : 'Statistical Baseline'} • Tier: ${forecastData.data_sufficiency}`}
              icon={Award}
              variant="blue"
            />
            <KpiCard
              label={`Expected Demand (${horizonDays}d)`}
              value={`${forecastData.expected_total_demand} ${forecastData.unit || 'units'}`}
              subtitle={`${forecastData.avg_predicted_daily_demand}/day predicted`}
              icon={BrainCircuit}
              variant="emerald"
            />
            <KpiCard
              label="Out-of-Sample Error & Bias"
              value={
                evalSummary.wape != null
                  ? `${evalSummary.wape}% WAPE`
                  : evalSummary.mae != null
                  ? `${evalSummary.mae} MAE`
                  : 'Baseline Only'
              }
              subtitle={
                evalSummary.folds_evaluated > 0
                  ? `${evalSummary.folds_evaluated} fold(s) • MAE: ${evalSummary.mae ?? '—'} • Bias: ${formatBias(evalSummary.bias)}`
                  : 'Insufficient samples for rolling backtest'
              }
              icon={AlertCircle}
              variant="purple"
            />
            <KpiCard
              label="History Span & Stockouts"
              value={`${Number(histSummary.avg_daily_demand || 0).toFixed(2)}/day`}
              subtitle={`${histSummary.available_history_years ?? 0} yrs (${histSummary.total_historical_days || 0}d) • ${histSummary.stockout_days_count || 0} stockout day(s)`}
              icon={Info}
              variant={(histSummary.stockout_days_count || 0) > 0 ? 'amber' : 'default'}
            />
          </div>

          <section className="section-card">
            <div className="section-card-header" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
              <div>
                <h2 className="section-card-title">{t('intelligence.historicalVsForecast')}</h2>
                <p style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)', marginTop: '0.2rem' }}>
                  {historyWindowMeta.displayed_start_date && historyWindowMeta.displayed_end_date
                    ? `Viewing ${historyWindowMeta.displayed_start_date} to ${historyWindowMeta.displayed_end_date} (${historyWindowMeta.points_returned ?? 0} ${historyWindowMeta.resolution_used || 'daily'} pts • ${historyWindowMeta.available_total_days ?? observedDays}d total available)`
                    : forecastData.selection_reason}
                </p>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                <label
                  htmlFor="forecast-history-resolution"
                  style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)', fontWeight: 600 }}
                >
                  {t('intelligence.graphResolutionLabel', 'Granularity')}:
                </label>
                <select
                  id="forecast-history-resolution"
                  className="form-control"
                  style={{ width: 'auto', minWidth: '115px', padding: '0.28rem 0.55rem', fontSize: '0.8rem' }}
                  value={historyResolution}
                  onChange={(e) => setHistoryResolution(e.target.value)}
                >
                  <option value="auto">Auto</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
            </div>

            {/* Interactive Historical Range Selector (30D .. 10Y / All / Custom) */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                flexWrap: 'wrap',
                marginBottom: '0.85rem',
                padding: '0.55rem 0.7rem',
                borderRadius: 'var(--radius-md)',
                background: 'var(--erp-surface-subtle)',
              }}
            >
              <Calendar size={14} style={{ color: 'var(--erp-text-muted)', marginRight: '0.2rem' }} />
              <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--erp-text-muted)', marginRight: '0.25rem' }}>
                {t('intelligence.graphRangeLabel', 'Historical Chart Range')}:
              </span>
              {HISTORY_PRESETS.map((preset) => {
                const isActive = historyPreset === preset.key
                return (
                  <button
                    key={preset.key}
                    type="button"
                    data-history-preset={preset.key}
                    onClick={() => setHistoryPreset(preset.key)}
                    className={`btn btn-sm ${isActive ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '0.2rem 0.55rem', fontSize: '0.76rem' }}
                  >
                    {preset.label}
                  </button>
                )
              })}

              {historyPreset === 'custom' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap', marginLeft: '0.4rem' }}>
                  <input
                    id="forecast-history-start"
                    type="date"
                    className="form-control"
                    style={{ width: 'auto', padding: '0.22rem 0.45rem', fontSize: '0.78rem' }}
                    value={customStartDate}
                    min={historyWindowMeta.available_min_date || undefined}
                    max={customEndDate || historyWindowMeta.available_max_date || undefined}
                    onChange={(e) => setCustomStartDate(e.target.value)}
                    aria-label="Custom history start date"
                  />
                  <span style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>to</span>
                  <input
                    id="forecast-history-end"
                    type="date"
                    className="form-control"
                    style={{ width: 'auto', padding: '0.22rem 0.45rem', fontSize: '0.78rem' }}
                    value={customEndDate}
                    min={customStartDate || historyWindowMeta.available_min_date || undefined}
                    max={historyWindowMeta.available_max_date || undefined}
                    onChange={(e) => setCustomEndDate(e.target.value)}
                    aria-label="Custom history end date"
                  />
                </div>
              )}
            </div>

            {customDateInvalid && (
              <div style={{ color: '#dc2626', fontSize: '0.82rem', marginBottom: '0.6rem' }}>
                Start date must be earlier than or equal to end date.
              </div>
            )}

            <div style={{ height: '340px', width: '100%' }}>
              <Line data={combinedChart} options={chartOptions} />
            </div>
          </section>

          {/* 4-Algorithm Primary Performance Table */}
          <section className="section-card">
            <div className="section-card-header" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
              <div>
                <h2 className="section-card-title">
                  {t('intelligence.primaryLeaderboardTitle', 'Primary Model Performance Comparison (ARIMA, XGBoost, Random Forest, LSTM)')}
                </h2>
                <p style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)', marginTop: '0.2rem' }}>
                  Bias Convention: {t('intelligence.biasConvention', 'Predicted − Actual (+ over-forecast, − under-forecast)')}.
                  {evalSummary.mape_limitation_note ? ` Note: ${evalSummary.mape_limitation_note}` : ''}
                </p>
              </div>
            </div>
            <div className="table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Algorithm</th>
                    <th>Status</th>
                    <th className="numeric">Folds</th>
                    <th className="numeric">MAE</th>
                    <th className="numeric">MSE</th>
                    <th className="numeric">RMSE</th>
                    <th className="numeric">MAPE (%)</th>
                    <th className="numeric">WAPE (%)</th>
                    <th className="numeric">Bias</th>
                    <th>Eligibility / Evaluation Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {primaryLeaderboard.length === 0 ? (
                    <tr>
                      <td colSpan={10} style={{ textAlign: 'center', color: 'var(--erp-text-muted)' }}>
                        Run evaluation to compare ARIMA, XGBoost, Random Forest, and LSTM.
                      </td>
                    </tr>
                  ) : (
                    primaryLeaderboard.map((row) => (
                      <tr key={row.display_name} style={row.is_champion ? { background: 'rgba(16, 185, 129, 0.08)' } : {}}>
                        <td style={{ fontWeight: row.is_champion ? 700 : 600 }}>
                          {row.display_name}
                          {row.is_champion && (
                            <span className="badge badge-received" style={{ marginLeft: '0.4rem' }}>
                              Champion
                            </span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${row.status === 'EVALUATED' ? 'badge-received' : 'badge-draft'}`}>
                            {row.status}
                          </span>
                        </td>
                        <td className="numeric">{row.folds_evaluated ?? 0}</td>
                        <td className="numeric">{formatMetric(row.mae)}</td>
                        <td className="numeric">{formatMetric(row.mse)}</td>
                        <td className="numeric">{formatMetric(row.rmse)}</td>
                        <td className="numeric">{formatMetric(row.mape, '%', 1)}</td>
                        <td className="numeric">{formatMetric(row.wape, '%', 1)}</td>
                        <td
                          className="numeric"
                          style={{
                            color:
                              row.bias == null
                                ? 'inherit'
                                : Number(row.bias) > 0
                                ? '#b45309'
                                : Number(row.bias) < 0
                                ? '#2563eb'
                                : '#059669',
                            fontWeight: 600,
                          }}
                        >
                          {formatBias(row.bias)}
                        </td>
                        <td style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                          {row.status === 'EVALUATED' ? row.notes : row.eligibility_reason || row.notes}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Backtest & Model Metric Charts */}
          {(evaluatedPrimaryRows.length > 0 || backtestPoints.length > 0) && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.25rem' }}>
              {evaluatedPrimaryRows.length > 0 && (
                <section className="section-card">
                  <h2 className="section-card-title" style={{ marginBottom: '0.75rem' }}>
                    {t('intelligence.errorComparisonTitle', 'Model Error Comparison (MAE & RMSE)')}
                  </h2>
                  <div style={{ height: '240px', width: '100%' }}>
                    <Bar data={errorComparisonChart} options={barChartOptions} />
                  </div>
                </section>
              )}

              {evaluatedPrimaryRows.length > 0 && (
                <section className="section-card">
                  <h2 className="section-card-title" style={{ marginBottom: '0.75rem' }}>
                    {t('intelligence.biasComparisonTitle', 'Directional Forecast Bias (Predicted − Actual)')}
                  </h2>
                  <div style={{ height: '240px', width: '100%' }}>
                    <Bar data={biasComparisonChart} options={barChartOptions} />
                  </div>
                </section>
              )}

              {backtestPoints.length > 0 && (
                <section className="section-card" style={{ gridColumn: evaluatedPrimaryRows.length > 0 ? '1 / -1' : undefined }}>
                  <h2 className="section-card-title" style={{ marginBottom: '0.75rem' }}>
                    Latest Rolling Backtest Fold: Actual vs. Predicted
                  </h2>
                  <div style={{ height: '250px', width: '100%' }}>
                    <Line data={backtestChart} options={chartOptions} />
                  </div>
                </section>
              )}
            </div>
          )}

          {/* Model Governance, Provenance & Data Quality */}
          <section className="section-card">
            <div className="section-card-header">
              <h2 className="section-card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <ShieldCheck size={17} />
                <span>{t('intelligence.modelGovernanceTitle', 'Champion Selection & Training Provenance')}</span>
              </h2>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
              {[
                [t('intelligence.currentChampion', 'Current Champion'), championDisplay],
                [
                  t('intelligence.previousChampion', 'Previous Champion'),
                  forecastData.previous_champion_model || evaluationData?.previous_champion_model || 'None (initial run)',
                ],
                [t('intelligence.modelVersion', 'Model Version'), forecastData.model_version || evaluationData?.model_version || '—'],
                [t('intelligence.datasetVersion', 'Dataset Version'), forecastData.dataset_version || evaluationData?.dataset_version || '—'],
                [
                  t('intelligence.trainingWindow', 'Training Date Range'),
                  `${forecastData.training_start_date || evalSummary.training_start_date || '—'} → ${
                    forecastData.training_end_date || evalSummary.training_end_date || '—'
                  }`,
                ],
                [
                  t('intelligence.backtestWindow', 'Backtest Date Range'),
                  `${forecastData.backtest_start_date || evalSummary.backtest_start_date || '—'} → ${
                    forecastData.backtest_end_date || evalSummary.backtest_end_date || '—'
                  }`,
                ],
                ['Hierarchy Scope', forecastData.hierarchical_level || 'LEVEL_1_TENANT_PRODUCT'],
                ['Data Completeness', `${dataQuality.data_completeness_pct ?? '—'}% (${dataQuality.stockout_uncertainty || 'N/A'})`],
              ].map(([lbl, val]) => (
                <div
                  key={lbl}
                  style={{
                    padding: '0.65rem 0.75rem',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--erp-surface-subtle)',
                  }}
                >
                  <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>{lbl}</div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 700, marginTop: '0.15rem', wordBreak: 'break-word' }}>{val}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Demand Characteristics */}
          <section className="section-card">
            <h2 className="section-card-title" style={{ marginBottom: '0.75rem' }}>Demand & Data Quality Diagnostics</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.75rem' }}>
              {[
                ['Observed Calendar Days', histSummary.total_historical_days ?? 0],
                ['Sales Days (Non-Zero)', histSummary.non_zero_demand_days ?? 0],
                ['Confirmed Zero Days', dataQuality.actual_zero_demand_days ?? histSummary.zero_demand_days ?? 0],
                ['Unrecorded Gap Days', dataQuality.no_recorded_transaction_days ?? 0],
                ['Total Units Sold', histSummary.total_units_sold ?? 0],
                ['Std Deviation (σ)', histSummary.demand_std_dev ?? 0],
                ['Coeff. of Variation (CV)', histSummary.cv ?? '—'],
                ['Inter-Demand (ADI)', histSummary.adi ?? '—'],
                [
                  'Trend Direction',
                  `${histSummary.trend_direction || '—'}${
                    histSummary.trend_pct_change != null
                      ? ` (${Number(histSummary.trend_pct_change) >= 0 ? '+' : ''}${Number(histSummary.trend_pct_change).toFixed(1)}%)`
                      : ''
                  }`,
                ],
              ].map(([lbl, val]) => (
                <div
                  key={lbl}
                  style={{
                    padding: '0.65rem 0.75rem',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--erp-surface-subtle)',
                  }}
                >
                  <div style={{ fontSize: '0.73rem', color: 'var(--erp-text-muted)' }}>{lbl}</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 700, marginTop: '0.15rem' }}>{val}</div>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
