import { Navigate, Link } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { ArrowRight, Boxes, ClipboardCheck, TrendingUp, ShieldCheck } from 'lucide-react'
import faviconImg from '../assets/images/favicon.png'

export default function LandingPage() {
  const { isAuthenticated, workspacesLoaded, currentWorkspace } = useSelector((state) => state.auth)

  if (isAuthenticated) {
    if (!workspacesLoaded || !currentWorkspace?.business?.id) {
      return <Navigate to="/workspaces" replace />
    }
    if (!currentWorkspace.business.onboarding_completed) {
      return <Navigate to="/onboarding" replace />
    }
    if (currentWorkspace.business.business_type === 'supplier') {
      return <Navigate to="/supplier-portal" replace />
    }
    return <Navigate to="/dashboard" replace />
  }

  const pillars = [
    {
      icon: ClipboardCheck,
      title: 'Procurement to Goods Receipt',
      desc: 'Track purchase orders from draft and supplier dispatch through partial and full goods receipts.',
    },
    {
      icon: Boxes,
      title: 'Traceable Stock Ledger',
      desc: 'Every sale, receipt, opening balance, and stock adjustment writes an auditable inventory movement.',
    },
    {
      icon: TrendingUp,
      title: 'Explainable Replenishment',
      desc: 'Combine on-hand stock, incoming purchase orders, lead times, and historical demand signals.',
    },
  ]

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--erp-bg)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <header
        style={{
          height: '64px',
          backgroundColor: 'var(--erp-surface)',
          borderBottom: '1px solid var(--erp-border)',
          padding: '0 1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
          <img src={faviconImg} alt="StockSangati" style={{ width: '32px', height: '32px', borderRadius: '7px' }} />
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-weight-semibold)', fontSize: 'var(--text-lg)', color: 'var(--erp-text-main)', letterSpacing: 'var(--tracking-tight)' }}>
            StockSangati
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
          <Link to="/login" className="btn btn-secondary">
            Sign In
          </Link>
          <Link to="/register" className="btn btn-primary">
            Create Account
          </Link>
        </div>
      </header>

      <main
        style={{
          flex: 1,
          maxWidth: '1020px',
          width: '100%',
          margin: '0 auto',
          padding: '4rem 1.5rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '3rem',
        }}
      >
        <section style={{ maxWidth: '680px', display: 'flex', flexDirection: 'column', gap: '1.125rem' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              width: 'fit-content',
              padding: '0.25rem 0.65rem',
              borderRadius: 'var(--radius-full)',
              backgroundColor: 'var(--erp-brand-subtle)',
              color: 'var(--erp-brand)',
              fontSize: '0.75rem',
              fontWeight: 700,
            }}
          >
            <ShieldCheck size={14} />
            <span>Smart Inventory Management System</span>
          </div>

          <h1 style={{ fontSize: '2.25rem', lineHeight: 1.2, color: 'var(--erp-text-main)' }}>
            Connected inventory, procurement, and sales operations.
          </h1>

          <p style={{ fontSize: '1rem', color: 'var(--erp-text-muted)', lineHeight: 1.6 }}>
            Manage suppliers, purchase orders, partial goods receipts, stock movements, and sales
            from one workspace designed for retailers and wholesalers.
          </p>

          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
            <Link to="/login" className="btn btn-primary">
              <span>Sign In to Workspace</span>
              <ArrowRight size={16} />
            </Link>
            <Link to="/register" className="btn btn-secondary">
              Create New Account
            </Link>
          </div>
        </section>

        <section
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: '1rem',
          }}
        >
          {pillars.map((item) => {
            const Icon = item.icon
            return (
              <div key={item.title} className="section-card">
                <div
                  style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '8px',
                    backgroundColor: 'var(--erp-brand-subtle)',
                    color: 'var(--erp-brand)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: '0.75rem',
                  }}
                >
                  <Icon size={18} />
                </div>
                <h2 style={{ fontSize: '1rem', marginBottom: '0.35rem' }}>{item.title}</h2>
                <p style={{ fontSize: '0.84rem', color: 'var(--erp-text-muted)', lineHeight: 1.5 }}>
                  {item.desc}
                </p>
              </div>
            )
          })}
        </section>
      </main>
    </div>
  )
}
