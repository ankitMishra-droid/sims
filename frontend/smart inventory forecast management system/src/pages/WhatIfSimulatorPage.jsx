import { useState, useEffect, useCallback } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import {
  Sliders,
  Play,
  AlertTriangle,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react'
import { Line } from 'react-chartjs-2'
import { getChartTheme } from '../components/charts/ChartSetup' // Ensure scales and controllers are registered
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { addToast } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'

export default function WhatIfSimulatorPage() {
  const dispatch = useDispatch()
  const rawProducts = useSelector(selectAllProducts)
  const theme = useSelector((state) => state.ui.theme)
  const chartColors = getChartTheme(theme === 'dark')
  const products = Array.isArray(rawProducts) ? rawProducts : []

  const [selectedProductId, setSelectedProductId] = useState('')
  const [demandMultiplier, setDemandMultiplier] = useState(1.25) // +25%
  const [leadTimeDelay, setLeadTimeDelay] = useState(5) // +5 days
  const [serviceLevel] = useState(0.95)
  const [plannedRestockQty, setPlannedRestockQty] = useState(0)
  const [restockDay, setRestockDay] = useState(14)

  const [simulationResult, setSimulationResult] = useState(null)
  const [loading, setLoading] = useState(false)

  // Derive active product ID without effect-driven setState
  const activeProductId = selectedProductId || (products?.length > 0 ? String(products[0].id) : '')

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  const runSimulation = useCallback(async (prodId) => {
    const targetId = prodId || activeProductId
    if (!targetId) return
    setLoading(true)
    try {
      const payload = {
        product_id: parseInt(targetId, 10),
        simulation_horizon_days: 60,
        demand_multiplier: parseFloat(demandMultiplier),
        lead_time_delay_days: parseInt(leadTimeDelay, 10),
        service_level: parseFloat(serviceLevel),
        planned_restock_qty: parseInt(plannedRestockQty, 10),
        restock_day: parseInt(restockDay, 10),
      }
      const data = await api.runWhatIfSimulation(payload)
      setSimulationResult(data)
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Simulation failed' }))
    } finally {
      setLoading(false)
    }
  }, [activeProductId, demandMultiplier, leadTimeDelay, serviceLevel, plannedRestockQty, restockDay, dispatch])

  // Run simulation automatically when activeProductId or parameters change
  useEffect(() => {
    if (!activeProductId) return
    let active = true
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const payload = {
          product_id: parseInt(activeProductId, 10),
          simulation_horizon_days: 60,
          demand_multiplier: parseFloat(demandMultiplier),
          lead_time_delay_days: parseInt(leadTimeDelay, 10),
          service_level: parseFloat(serviceLevel),
          planned_restock_qty: parseInt(plannedRestockQty, 10),
          restock_day: parseInt(restockDay, 10),
        }
        const data = await api.runWhatIfSimulation(payload)
        if (active) setSimulationResult(data)
      } catch (err) {
        if (active) {
          dispatch(addToast({ type: 'error', message: err.message || 'Simulation failed' }))
        }
      } finally {
        if (active) setLoading(false)
      }
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [activeProductId, demandMultiplier, leadTimeDelay, serviceLevel, plannedRestockQty, restockDay, dispatch])

  // Chart configuration
  const trajectory = simulationResult?.trajectory || []
  const chartData = {
    labels: trajectory.map((pt) => `Day ${pt.day} (${pt.date.slice(5)})`),
    datasets: [
      {
        label: 'Projected Stock Level',
        data: trajectory.map((pt) => pt.projected_stock),
        borderColor: simulationResult?.simulation_result?.stockout_projected ? '#ef4444' : '#10b981',
        backgroundColor: simulationResult?.simulation_result?.stockout_projected
          ? 'rgba(239, 68, 68, 0.1)'
          : 'rgba(16, 185, 129, 0.1)',
        fill: true,
        tension: 0.2,
        pointRadius: 2,
        pointHoverRadius: 5,
        borderWidth: 2,
      },
      {
        label: 'Zero Stock Threshold (Stockout)',
        data: trajectory.map(() => 0),
        borderColor: 'rgba(239, 68, 68, 0.4)',
        borderDash: [5, 5],
        pointRadius: 0,
        borderWidth: 1.5,
      },
    ],
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'top', labels: { color: chartColors.textColor, font: { size: 12, weight: '500' } } },
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
          text: 'Inventory Stock (Units)',
          color: chartColors.textColor,
          font: { size: 12, weight: '500' },
        },
      },
    },
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title="What-If Scenario Stress Simulator"
        subtitle="Simulate stockout vulnerabilities, supply chain delays, demand shocks, and financial exposure"
      />

      {/* Main Grid: Left Controls, Right Results */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.25rem' }}>
        {/* Scenario Parameters Card */}
        <div className="section-card">
          <div className="section-card-header" style={{ justifyContent: 'flex-start' }}>
            <Sliders size={18} style={{ color: 'var(--erp-primary)' }} />
            <h3 className="section-card-title" style={{ margin: 0 }}>
              Scenario Stress Parameters
            </h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Product Selector */}
            <div>
              <label className="form-label" style={{ marginBottom: '0.375rem' }}>
                Select Target Product
              </label>
              <select
                className="form-control"
                value={activeProductId}
                onChange={(e) => setSelectedProductId(e.target.value)}
              >
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} (Stock: {p.current_stock})
                  </option>
                ))}
              </select>
            </div>

            {/* Demand Multiplier Slider */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                <label className="form-label">
                  Demand Multiplier
                </label>
                <strong className="tabular-nums" style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-weight-semibold)', color: '#10b981' }}>
                  {demandMultiplier}x ({demandMultiplier >= 1.0 ? `+${Math.round((demandMultiplier - 1) * 100)}%` : `${Math.round((demandMultiplier - 1) * 100)}%`})
                </strong>
              </div>
              <input
                type="range"
                min="0.5"
                max="2.5"
                step="0.05"
                value={demandMultiplier}
                onChange={(e) => setDemandMultiplier(e.target.value)}
                style={{ width: '100%', accentColor: '#10b981' }}
              />
              <span className="form-hint">
                Simulate festive promos, advertising spikes, or market downturns
              </span>
            </div>

            {/* Lead Time Delay Slider */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                <label className="form-label">
                  Supplier Lead Time Delay
                </label>
                <strong className="tabular-nums" style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-weight-semibold)', color: leadTimeDelay > 0 ? '#ef4444' : '#10b981' }}>
                  +{leadTimeDelay} Days
                </strong>
              </div>
              <input
                type="range"
                min="0"
                max="25"
                step="1"
                value={leadTimeDelay}
                onChange={(e) => setLeadTimeDelay(e.target.value)}
                style={{ width: '100%', accentColor: '#ef4444' }}
              />
              <span className="form-hint">
                Simulate port strikes, shipping bottlenecks, or customs holds
              </span>
            </div>

            {/* Planned Restock Orders */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                <label className="form-label">
                  Planned Inbound Restock
                </label>
                <strong className="tabular-nums" style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--erp-brand)' }}>
                  +{plannedRestockQty} units (Arrival: Day {restockDay})
                </strong>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem' }}>
                <input
                  type="number"
                  min="0"
                  max="500"
                  className="form-control"
                  value={plannedRestockQty}
                  onChange={(e) => setPlannedRestockQty(e.target.value)}
                  placeholder="Quantity"
                  style={{ flex: 1 }}
                />
                <input
                  type="number"
                  min="1"
                  max="60"
                  className="form-control"
                  value={restockDay}
                  onChange={(e) => setRestockDay(e.target.value)}
                  placeholder="Day"
                  style={{ width: '100px' }}
                />
              </div>
            </div>

            <button
              type="button"
              className="btn btn-accent btn-lg"
              onClick={() => runSimulation(activeProductId)}
              disabled={loading}
              style={{ width: '100%', marginTop: '0.25rem' }}
            >
              <Play size={16} />
              <span>{loading ? 'Simulating...' : 'Run What-If Simulation'}</span>
            </button>
          </div>
        </div>

        {/* Outcome Cards */}
        {simulationResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Vulnerability Verdict Banner */}
            <div
              className="section-card"
              style={{
                background: simulationResult.simulation_result.stockout_projected
                  ? 'var(--status-danger-bg)'
                  : 'var(--status-success-bg)',
                borderColor: simulationResult.simulation_result.stockout_projected
                  ? 'var(--status-danger-border)'
                  : 'var(--status-success-border)',
                display: 'flex',
                gap: '0.75rem',
                alignItems: 'center',
              }}
            >
              {simulationResult.simulation_result.stockout_projected ? (
                <AlertTriangle size={26} style={{ color: 'var(--status-danger-text)', flexShrink: 0 }} />
              ) : (
                <ShieldCheck size={26} style={{ color: 'var(--status-success-text)', flexShrink: 0 }} />
              )}
              <div>
                <h4
                  style={{
                    margin: '0 0 0.25rem',
                    fontSize: 'var(--text-md)',
                    fontWeight: 'var(--font-weight-semibold)',
                    color: simulationResult.simulation_result.stockout_projected ? 'var(--status-danger-text)' : 'var(--status-success-text)',
                  }}
                >
                  {simulationResult.simulation_result.stockout_projected
                    ? `Critical Stockout Detected on Day ${simulationResult.simulation_result.stockout_day}`
                    : 'Inventory Remains Resilient Under Scenario'}
                </h4>
                <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--erp-text-muted)', lineHeight: 'var(--leading-snug)' }}>
                  {simulationResult.simulation_result.stockout_projected
                    ? `Inventory depletes to zero on ${simulationResult.simulation_result.stockout_date}. Stockout persists for ${simulationResult.simulation_result.stockout_duration_days} days.`
                    : 'Current inventory buffers absorb this demand increase and supplier delay safely.'}
                </p>
              </div>
            </div>

            {/* Metrics Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '1rem' }}>
              <div className="kpi-card rose">
                <div className="kpi-content">
                  <span className="kpi-label">Unmet Demand</span>
                  <span className="kpi-value" style={{ color: '#ef4444' }}>
                    {simulationResult.simulation_result.total_lost_units}{' '}
                    <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-regular)', color: 'var(--erp-text-muted)' }}>units</span>
                  </span>
                </div>
              </div>

              <div className="kpi-card rose">
                <div className="kpi-content">
                  <span className="kpi-label">Lost Revenue Exposure</span>
                  <span className="kpi-value" style={{ color: '#ef4444' }}>
                    ₹{simulationResult.simulation_result.estimated_lost_revenue?.toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="kpi-card emerald">
                <div className="kpi-content">
                  <span className="kpi-label">Revised Safety Stock Needed</span>
                  <span className="kpi-value" style={{ color: '#10b981' }}>
                    {simulationResult.simulation_result.revised_safety_stock_needed}{' '}
                    <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-regular)', color: 'var(--erp-text-muted)' }}>units</span>
                  </span>
                  <span className="kpi-subtitle tabular-nums">
                    Baseline: {simulationResult.baseline.safety_stock} units
                  </span>
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-content">
                  <span className="kpi-label">Revised Reorder Point (ROP)</span>
                  <span className="kpi-value">
                    {simulationResult.simulation_result.revised_reorder_point}{' '}
                    <span style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-regular)', color: 'var(--erp-text-muted)' }}>units</span>
                  </span>
                  <span className="kpi-subtitle tabular-nums">
                    Baseline: {simulationResult.baseline.reorder_point} units
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Trajectory Graph */}
      <div className="section-card" style={{ height: '400px', display: 'flex', flexDirection: 'column' }}>
        <div className="section-card-header">
          <h3 className="section-card-title" style={{ margin: 0 }}>
            Simulated Inventory Depletion Trajectory (60-Day Horizon)
          </h3>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--erp-text-muted)' }}>
            Red curve indicates inventory depletion below zero
          </span>
        </div>
        <div style={{ flex: 1, minHeight: '300px' }}>
          {loading ? (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--erp-text-muted)', gap: '0.75rem' }}>
              <RefreshCw className="spin" size={28} style={{ color: 'var(--erp-primary)' }} />
              <span style={{ fontSize: 'var(--text-base)', fontWeight: 'var(--font-weight-medium)' }}>Running scenario simulation...</span>
            </div>
          ) : trajectory.length > 0 ? (
            <Line data={chartData} options={chartOptions} />
          ) : (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--erp-text-subtle)', fontSize: 'var(--text-base)' }}>
              Configure parameters and click &apos;Run What-If Simulation&apos; to view trajectory.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
