import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { Lock, Mail, ArrowRight, ShieldCheck, Sparkles, AlertCircle, Languages, Sun, Moon } from 'lucide-react'
import { api } from '../../api'
import { setCredentials, setLoading, setError, setWorkspaces } from '../../store/authSlice'
import { addToast, setLanguage, toggleTheme } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import faviconImg from '../../assets/images/favicon.png'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const { loading, error } = useSelector((state) => state.auth)
  const theme = useSelector((state) => state.ui.theme)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState('')

  const from = location.state?.from?.pathname || '/dashboard'

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLocalError('')
    if (!email || !password) {
      setLocalError(t('validation.requiredFields'))
      return
    }

    try {
      dispatch(setLoading(true))
      const response = await api.login({ email, password })
      dispatch(
        setCredentials({
          token: response.access_token,
          refreshToken: response.refresh_token,
          user: response.user,
        })
      )
      if (response.user?.preferred_language) {
        dispatch(setLanguage(response.user.preferred_language))
      }

      let activeWs = null
      let wsFetchFailed = false
      try {
        const wsList = await api.getWorkspaces()
        dispatch(setWorkspaces(wsList))
        activeWs =
          wsList.find((w) => w.is_active_workspace) ||
          wsList.find((w) => w.business?.id === response.user?.active_business_id) ||
          wsList[0] ||
          null
      } catch (wsErr) {
        if (wsErr?.status === 404) {
          dispatch(setWorkspaces([]))
        } else {
          wsFetchFailed = true
        }
      }

      dispatch(
        addToast({
          type: 'success',
          message: `Welcome back, ${response.user.name}!`,
        })
      )

      if (wsFetchFailed) {
        navigate(response.user.active_business_id ? from : '/workspaces', { replace: true })
      } else if (!activeWs || !response.user.active_business_id) {
        navigate('/workspaces', { replace: true })
      } else if (!activeWs.business?.onboarding_completed) {
        navigate('/onboarding', { replace: true })
      } else if (activeWs.business?.business_type === 'supplier') {
        navigate('/supplier-portal', { replace: true })
      } else {
        navigate(from, { replace: true })
      }
    } catch (err) {
      const msg = err.message || 'Login failed. Please check your credentials.'
      setLocalError(msg)
      dispatch(setError(msg))
    }
  }

  const showDemoQuickFill =
    import.meta.env.DEV &&
    import.meta.env.VITE_ENABLE_DEMO_LOGIN === 'true' &&
    Boolean(import.meta.env.VITE_DEMO_PASSWORD)

  const handleDemoLogin = (demoEmail) => {
    setEmail(demoEmail)
    setPassword(import.meta.env.VITE_DEMO_PASSWORD || '')
  }

  return (
    <div className="auth-shell">
      <header className="auth-topbar">
        <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
          <img src={faviconImg} alt="StockSangati" style={{ width: '32px', height: '32px', borderRadius: '7px' }} />
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-weight-semibold)', fontSize: 'var(--text-lg)', color: 'var(--erp-text-main)', letterSpacing: 'var(--tracking-tight)' }}>
            {t('brandName', 'StockSangati')}
          </span>
        </Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className="header-chip-btn"
            onClick={() => dispatch(setLanguage(language === 'en' ? 'hi' : 'en'))}
          >
            <Languages size={14} />
            <span>{language === 'hi' ? 'हिन्दी' : 'EN'}</span>
          </button>
          <button type="button" className="header-chip-btn" onClick={() => dispatch(toggleTheme())} aria-label="Toggle theme">
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <Link to="/register" className="btn btn-secondary btn-sm">
            {t('common.createAccount')}
          </Link>
        </div>
      </header>

      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-header-block">
            <div className="auth-brand-icon">
              <ShieldCheck size={24} />
            </div>
            <h1 className="auth-title">{t('auth.loginTitle')}</h1>
            <p className="auth-subtitle">{t('auth.loginSubtitle')}</p>
          </div>

          {(localError || error) && (
            <div className="form-error-banner" style={{ marginBottom: '1.15rem' }}>
              <AlertCircle size={17} />
              <span>{localError || error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="form-group">
              <label htmlFor="login-email" className="form-label">
                {t('auth.emailLabel')} <span className="required">*</span>
              </label>
              <div className="auth-input-wrap">
                <Mail size={16} className="auth-input-icon" />
                <input
                  id="login-email"
                  type="email"
                  required
                  className="form-control"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                />
              </div>
            </div>

            <div className="form-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label htmlFor="login-password" className="form-label">
                  {t('auth.passwordLabel')} <span className="required">*</span>
                </label>
                <Link to="/reset-password" style={{ fontSize: '0.78rem', color: 'var(--erp-brand)', fontWeight: 600 }}>
                  {t('auth.forgotPassword')}
                </Link>
              </div>
              <div className="auth-input-wrap">
                <Lock size={16} className="auth-input-icon" />
                <input
                  id="login-password"
                  type="password"
                  required
                  className="form-control"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button type="submit" className="btn btn-primary btn-lg" disabled={loading} style={{ width: '100%', marginTop: '0.25rem' }}>
              <span>{loading ? 'Authenticating...' : t('common.signIn')}</span>
              <ArrowRight size={16} />
            </button>
          </form>

          {showDemoQuickFill && (
            <div style={{ marginTop: '1.35rem', paddingTop: '1.15rem', borderTop: '1px solid var(--erp-border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', color: 'var(--erp-text-muted)', marginBottom: '0.6rem' }}>
                <Sparkles size={14} style={{ color: 'var(--erp-brand)' }} />
                <span>Development Quick Demo Login:</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleDemoLogin('architect@stocksangati.com')}>
                  Admin Demo
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleDemoLogin('direct@stocksangati.com')}>
                  Manager Demo
                </button>
              </div>
            </div>
          )}

          <p style={{ textAlign: 'center', fontSize: '0.84rem', color: 'var(--erp-text-muted)', marginTop: '1.25rem' }}>
            Don&apos;t have an account?{' '}
            <Link to="/register" style={{ color: 'var(--erp-brand)', fontWeight: 600 }}>
              {t('common.createAccount')}
            </Link>
          </p>
        </div>
      </main>
    </div>
  )
}
