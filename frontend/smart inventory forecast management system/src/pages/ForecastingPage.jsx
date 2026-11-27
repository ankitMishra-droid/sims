import { useState, useEffect } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import {
  BrainCircuit,
  Award,
  RefreshCw,
  AlertCircle,
} from 'lucide-react'
import { Line } from 'react-chartjs-2'
import { getChartTheme } from '../components/charts/ChartSetup' // Ensure scales and controllers are registered
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { addToast } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'

export default function ForecastingPage() {
  const dispatch = useDispatch()
  const rawProducts = useSelector(selectAllProducts)
  const theme = useSelector((state) => state.ui.theme)
  const chartColors = getChartTheme(theme === 'dark')
  const products = Array.isArray(rawProducts) ? rawProducts : []

  const [selectedProductId, setSelectedProductId] = useState('')
  const [horizonDays, setHorizonDays] = useState(30)
  const [selectedModel, setSelectedModel] = useState('auto')

  const [forecastData, setForecastData] = useState(null)
  const [comparisonData, setComparisonData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState(null)

  // Determine active product ID without triggering setState in effect
  const activeProductId = selectedProductId || (products?.length > 0 ? String(products[0].id) : '')

  // Load products on mount
  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  // Load forecast when active product, horizon, or model changes
  useEffect(() => {
    if (!activeProductId) return
    let active = true
    const fetchForecastData = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await api.getForecast(activeProductId, horizonDays, selectedModel)
        if (active) setForecastData(data)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load forecast.')
      } finally {
        if (active) setLoading(false)
      }
    }
    fetchForecastData()
    return () => {
      active = false
    }
  }, [activeProductId, horizonDays, selectedModel])

  const loadForecast = async (productId, horizon, model) => {
    if (!productId) return
    setLoading(true)
    setError(null)
    try {
      const data = await api.getForecast(productId, horizon, model)
      setForecastData(data)
    } catch (err) {
      setError(err.message || 'Failed to load forecast.')
    } finally {
      setLoading(false)
    }
  }

  const loadComparison = async () => {
    if (!activeProductId) return
    setComparing(true)
    try {
      const data = await api.compareModels(activeProductId, 30)
      setComparisonData(data)
      dispatch(addToast({ type: 'success', message: 'Model evaluation completed!' }))
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to compare models' }))
    } finally {
      setComparing(false)
    }
  }

  // Chart configuration
  const chartData = {
    labels: forecastData?.forecast_series?.map((pt) => pt.date) || [],
    datasets: [
      {
        label: 'Upper Confidence Bound (95%)',
        data: forecastData?.forecast_series?.map((pt) => pt.upper_confidence_bound) || [],
        borderColor: 'rgba(16, 185, 129, 0.25)',
        backgroundColor: 'rgba(16, 185, 129, 0.1)',
        fill: '+1',
        pointRadius: 0,
        borderWidth: 1,
      },
      {
        label: 'Predicted Demand',
        data: forecastData?.forecast_series?.map((pt) => pt.predicted_demand) || [],
        borderColor: '#10b981',
        backgroundColor: '#10b981',
        borderWidth: 2.5,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 6,
      },
      {
        label: 'Lower Confidence Bound (95%)',
        data: forecastData?.forecast_series?.map((pt) => pt.lower_confidence_bound) || [],
        borderColor: 'rgba(16, 185, 129, 0.25)',
        backgroundColor: 'transparent',
        fill: false,
        pointRadius: 0,
        borderWidth: 1,
      },
    ],
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: chartColors.textColor,
          font: { size: 12, weight: '500' },
        },
      },
      tooltip: {
        backgroundColor: chartColors.tooltipBg,
        borderColor: chartColors.tooltipBorder,
        borderWidth: 1,
        titleColor: chartColors.tooltipTitleColor,
        bodyColor: chartColors.tooltipBodyColor,
        callbacks: {
          label: (context) => `${context.dataset.label}: ${context.parsed.y} units`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: chartColors.gridColor },
        ticks: { color: chartColors.textColor, maxRotation: 45, font: { size: 11 } },
      },
      y: {
        grid: { color: chartColors.gridColor },
        ticks: { color: chartColors.textColor, font: { size: 11 } },
        title: {
          display: true,
          text: 'Demand (Units)',
          color: chartColors.textColor,
          font: { size: 12, weight: '500' },
        },
        beginAtZero: true,
      },
    },
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title="AI Demand Forecasting"
        subtitle="Multi-model statistical and deep learning time-series projections"
        actions={
          <button
            type="button"
            className="btn btn-accent"
            onClick={loadComparison}
            disabled={comparing}
          >
            <Award size={16} />
            <span>{comparing ? 'Benchmarking 5 Models...' : 'Compare All 5 Models'}</span>
          </button>
        }
      />

      {/* Control Strip */}
      <div
        className="section-card"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '1rem',
        }}
      >
        <div>
          <label className="form-label" style={{ marginBottom: '0.375rem' }}>
            Select Product
          </label>
          <select
            className="form-control"
            value={activeProductId}
            onChange={(e) => setSelectedProductId(e.target.value)}
          >
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.sku}) – Stock: {p.current_stock}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="form-label" style={{ marginBottom: '0.375rem' }}>
            Forecast Horizon ({horizonDays} Days)
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {[7, 14, 30, 60, 90].map((h) => (
              <button
                key={h}
                type="button"
                className={`btn btn-sm ${horizonDays === h ? 'btn-accent' : 'btn-secondary'}`}
                style={{ flex: 1 }}
                onClick={() => setHorizonDays(h)}
              >
                {h}d
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="form-label" style={{ marginBottom: '0.375rem' }}>
            Forecasting Algorithm
          </label>
          <select
            className="form-control"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
          >
            <option value="auto">🏆 Auto Champion Model (Lowest MAE)</option>
            <option value="arima">ARIMA(1, 1, 1) – Statistical Autoregressive</option>
            <option value="prophet">Prophet – Additive Trend & Seasonality</option>
            <option value="random_forest">Random Forest – Lag Ensemble Regressor</option>
            <option value="xgboost">XGBoost – Gradient Boosted Trees</option>
            <option value="lstm">LSTM Neural Network – Deep Sequence Network</option>
          </select>
        </div>
      </div>

      {/* Error Notice */}
      {error && (
        <div className="form-error-banner">
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      {forecastData && (
        <div className="kpi-grid" style={{ marginBottom: 0 }}>
          <div className="kpi-card emerald">
            <div className="kpi-content">
              <span className="kpi-label">Total Predicted Demand</span>
              <span className="kpi-value">
                {forecastData.summary?.total_predicted_demand}{' '}
                <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-regular)', color: 'var(--erp-text-muted)' }}>units</span>
              </span>
              <span className="kpi-subtitle" style={{ color: '#10b981' }}>Next {horizonDays} days</span>
            </div>
          </div>

          <div className="kpi-card blue">
            <div className="kpi-content">
              <span className="kpi-label">Daily Average Demand</span>
              <span className="kpi-value">
                {forecastData.summary?.daily_average_demand}{' '}
                <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-regular)', color: 'var(--erp-text-muted)' }}>units/day</span>
              </span>
              <span className="kpi-subtitle">Consistent baseline</span>
            </div>
          </div>

          <div className="kpi-card purple">
            <div className="kpi-content">
              <span className="kpi-label">Peak Demand Day</span>
              <span className="kpi-value" style={{ fontSize: 'var(--text-xl)' }}>
                {forecastData.summary?.peak_demand_day || 'N/A'}
              </span>
              <span className="kpi-subtitle" style={{ color: 'var(--erp-brand)' }}>
                {forecastData.summary?.peak_demand_value} units projected
              </span>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-content">
              <span className="kpi-label">Active Algorithm</span>
              <span className="kpi-value" style={{ fontSize: 'var(--text-lg)', color: 'var(--erp-primary)', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                <BrainCircuit size={18} />
                <span>{forecastData.model_used}</span>
              </span>
              <span className="kpi-subtitle tabular-nums">
                MAE: {forecastData.metrics?.mae} | MAPE: {forecastData.metrics?.mape}%
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Chart Section */}
      <div className="section-card" style={{ height: '420px', display: 'flex', flexDirection: 'column' }}>
        <div className="section-card-header">
          <h3 className="section-card-title" style={{ margin: 0 }}>
            Demand Trajectory & Confidence Interval
          </h3>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--erp-text-muted)' }}>
            Shaded region indicates 95% Confidence Interval
          </span>
        </div>
        <div style={{ flex: 1, minHeight: '320px' }}>
          {loading ? (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--erp-text-muted)', gap: '0.75rem' }}>
              <RefreshCw className="spin" size={28} style={{ color: 'var(--erp-primary)' }} />
              <span style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-weight-medium)' }}>Generating AI demand forecast...</span>
            </div>
          ) : error ? (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--status-danger-text)', gap: '0.75rem' }}>
              <AlertCircle size={32} />
              <span style={{ fontSize: 'var(--text-base)' }}>{error}</span>
              <button
                type="button"
                className="btn btn-accent btn-sm"
                onClick={() => loadForecast(activeProductId, horizonDays, selectedModel)}
              >
                Retry Forecast
              </button>
            </div>
          ) : forecastData?.forecast_series?.length > 0 ? (
            <Line data={chartData} options={chartOptions} />
          ) : (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--erp-text-subtle)', fontSize: 'var(--text-base)' }}>
              Select a product above to generate demand trajectory.
            </div>
          )}
        </div>
      </div>

      {/* 5-Model Benchmark Comparison Table */}
      {comparisonData && (
        <div className="section-card">
          <div className="section-card-header" style={{ justifyContent: 'flex-start' }}>
            <Award size={20} style={{ color: 'var(--erp-primary)' }} />
            <h3 className="section-card-title" style={{ margin: 0 }}>
              Algorithm Evaluation Leaderboard (Champion: {comparisonData.champion_model})
            </h3>
          </div>

          <div className="table-responsive">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Algorithm</th>
                  <th className="numeric">MAE</th>
                  <th className="numeric">RMSE</th>
                  <th className="numeric">MAPE (%)</th>
                  <th className="numeric">sMAPE (%)</th>
                  <th className="numeric">WAPE (%)</th>
                  <th className="numeric">Fit Time</th>
                </tr>
              </thead>
              <tbody>
                {comparisonData.models?.map((m) => {
                  const isChamp = m.model_name === comparisonData.champion_model
                  return (
                    <tr
                      key={m.model_name}
                      style={{
                        background: isChamp ? 'var(--status-success-bg)' : undefined,
                      }}
                    >
                      <td style={{ fontWeight: 'var(--font-weight-semibold)' }}>
                        {isChamp ? '🥇 1' : `#${m.rank}`}
                      </td>
                      <td style={{ fontWeight: isChamp ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)', color: isChamp ? 'var(--status-success-text)' : 'var(--erp-text-main)' }}>
                        {m.model_name}{' '}
                        {isChamp && (
                          <span className="badge badge-success" style={{ marginLeft: '0.375rem' }}>
                            CHAMPION
                          </span>
                        )}
                      </td>
                      <td className="numeric" style={{ fontWeight: 'var(--font-weight-semibold)' }}>{m.mae}</td>
                      <td className="numeric">{m.rmse}</td>
                      <td className="numeric">{m.mape}%</td>
                      <td className="numeric">{m.smape}%</td>
                      <td className="numeric">{m.wape}%</td>
                      <td className="numeric" style={{ color: 'var(--erp-text-muted)' }}>{m.training_time_seconds}s</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
