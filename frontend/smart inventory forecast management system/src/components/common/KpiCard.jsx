import React from 'react'

export default function KpiCard({
  label,
  value,
  subtitle,
  icon: Icon,
  variant = 'default', // 'emerald' | 'amber' | 'rose' | 'blue'
  onClick = null,
}) {
  return (
    <div
      className={`kpi-card ${variant}`}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : {}}
    >
      <div className="kpi-content">
        <span className="kpi-label">{label}</span>
        <span className="kpi-value">{value}</span>
        {subtitle && <span className="kpi-subtitle">{subtitle}</span>}
      </div>
      {Icon && (
        <div className="kpi-icon-box">
          <Icon size={22} />
        </div>
      )}
    </div>
  )
}
