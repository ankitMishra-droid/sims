export default function PageHeader({ title, subtitle = '', actions = null, badge = null }) {
  return (
    <div className="page-header-bar">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          <h1 className="page-header-title">{title}</h1>
          {badge}
        </div>
        {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  )
}
