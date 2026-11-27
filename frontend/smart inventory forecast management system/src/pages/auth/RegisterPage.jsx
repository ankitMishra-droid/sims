import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { User, Mail, Lock, Globe, ArrowRight, ShieldCheck, AlertCircle, Languages, Sun, Moon } from 'lucide-react'
import { api } from '../../api'
import { setCredentials, setLoading, setError, setWorkspaces } from '../../store/authSlice'
import { addToast, setLanguage, toggleTheme } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import faviconImg from '../../assets/images/favicon.png'

export default function RegisterPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const { loading, error } = useSelector((state) => state.auth)
  const theme = useSelector((state) => state.ui.theme)

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [preferredLanguage, setPreferredLanguage] = useState(language || 'en')
  const [localError, setLocalError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLocalError('')

    if (!name.trim() || !email.trim() || !password) {
      setLocalError(t('validation.requiredFields'))
      return
    }
    if (password.length < 6) {
      setLocalError(t('validation.passwordLength'))
      return
    }

    try {
      dispatch(setLoading(true))
      await api.register({
        name: name.trim(),
        email: email.trim(),
        password,
        role: 'owner',
        preferred_language: preferredLanguage,
        create_workspace: false,
      })

      const loginRes = await api.login({ email: email.trim(), password })
      dispatch(
        setCredentials({
          token: loginRes.access_token,
          refreshToken: loginRes.refresh_token,
          user: loginRes.user,
        })
      )
      dispatch(setWorkspaces([]))
      dispatch(setLanguage(preferredLanguage))
      dispatch(
        addToast({
          type: 'success',
          message: 'Account created! Next, create or join your business workspace.',
        })
      )
      navigate('/workspaces', { replace: true })
    } catch (err) {
      const msg = err.message || 'Registration failed. Please try again.'
      setLocalError(msg)
      dispatch(setError(msg))
    }
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
          <Link to="/login" className="btn btn-secondary btn-sm">
            {t('common.signIn')}
          </Link>
        </div>
      </header>

      <main className="auth-main">
        <div className="auth-card" style={{ maxWidth: '480px' }}>
          <div className="auth-header-block">
            <div className="auth-brand-icon">
              <ShieldCheck size={24} />
            </div>
            <h1 className="auth-title">{t('auth.registerTitle')}</h1>
            <p className="auth-subtitle">{t('auth.registerSubtitle')}</p>
          </div>

          {(localError || error) && (
            <div className="form-error-banner" style={{ marginBottom: '1.15rem' }}>
              <AlertCircle size={17} />
              <span>{localError || error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="form-group">
              <label htmlFor="reg-name" className="form-label">
                {t('auth.nameLabel')} <span className="required">*</span>
              </label>
              <div className="auth-input-wrap">
                <User size={16} className="auth-input-icon" />
                <input
                  id="reg-name"
                  type="text"
                  required
                  className="form-control"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ramesh Kumar"
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="reg-email" className="form-label">
                {t('auth.emailLabel')} <span className="required">*</span>
              </label>
              <div className="auth-input-wrap">
                <Mail size={16} className="auth-input-icon" />
                <input
                  id="reg-email"
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
              <label htmlFor="reg-pw" className="form-label">
                {t('auth.passwordLabel')} <span className="required">*</span>
              </label>
              <div className="auth-input-wrap">
                <Lock size={16} className="auth-input-icon" />
                <input
                  id="reg-pw"
                  type="password"
                  required
                  minLength={6}
                  className="form-control"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Minimum 6 characters"
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="reg-lang" className="form-label">
                {t('auth.languageLabel')}
              </label>
              <div className="auth-input-wrap">
                <Globe size={16} className="auth-input-icon" />
                <select
                  id="reg-lang"
                  className="form-control"
                  value={preferredLanguage}
                  onChange={(e) => setPreferredLanguage(e.target.value)}
                >
                  <option value="en">English</option>
                  <option value="hi">हिन्दी (Hindi)</option>
                </select>
              </div>
            </div>

            <button type="submit" className="btn btn-primary btn-lg" disabled={loading} style={{ width: '100%', marginTop: '0.25rem' }}>
              <span>{loading ? 'Creating Account...' : t('common.createAccount')}</span>
              <ArrowRight size={16} />
            </button>
          </form>

          <p style={{ textAlign: 'center', fontSize: '0.84rem', color: 'var(--erp-text-muted)', marginTop: '1.25rem' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: 'var(--erp-brand)', fontWeight: 600 }}>
              {t('common.signIn')}
            </Link>
          </p>
        </div>
      </main>
    </div>
  )
}
