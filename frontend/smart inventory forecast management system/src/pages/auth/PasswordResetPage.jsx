import { useState } from 'react'
import { Link } from 'react-router-dom'
import { KeyRound, Mail, Lock, ArrowLeft, CheckCircle2, AlertCircle, Languages, Sun, Moon } from 'lucide-react'
import { useDispatch, useSelector } from 'react-redux'
import { api } from '../../api'
import { setLanguage, toggleTheme } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import faviconImg from '../../assets/images/favicon.png'

export default function PasswordResetPage() {
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const theme = useSelector((state) => state.ui.theme)
  const [mode, setMode] = useState('request')
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  const handleRequest = async (e) => {
    e.preventDefault()
    setError('')
    setSuccessMsg('')
    if (!email.trim()) {
      setError(t('validation.invalidEmail'))
      return
    }
    setSubmitting(true)
    try {
      const res = await api.requestPasswordReset(email.trim())
      setSuccessMsg(
        res.message ||
          'If an active account exists for that email, a verified reset token has been dispatched.'
      )
      setMode('confirm')
    } catch (err) {
      setError(err.message || 'Unable to process password reset request.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleConfirm = async (e) => {
    e.preventDefault()
    setError('')
    setSuccessMsg('')
    if (!token.trim()) {
      setError('Verification token is required.')
      return
    }
    if (newPassword.length < 6) {
      setError(t('validation.passwordLength'))
      return
    }
    if (newPassword !== confirmPassword) {
      setError(t('validation.passwordMismatch'))
      return
    }
    setSubmitting(true)
    try {
      const res = await api.confirmPasswordReset({
        token: token.trim(),
        new_password: newPassword,
      })
      setSuccessMsg(res.message || 'Password updated! You can now sign in with your new password.')
      setToken('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setError(err.message || 'Failed to confirm password reset.')
    } finally {
      setSubmitting(false)
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
        <div className="auth-card">
          <div className="auth-header-block">
            <div className="auth-brand-icon">
              <KeyRound size={24} />
            </div>
            <h1 className="auth-title">{t('auth.resetTitle')}</h1>
            <p className="auth-subtitle">{t('auth.resetSubtitle')}</p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '1.25rem' }}>
            <button
              type="button"
              className={`btn ${mode === 'request' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setMode('request')
                setError('')
              }}
            >
              Request Token
            </button>
            <button
              type="button"
              className={`btn ${mode === 'confirm' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setMode('confirm')
                setError('')
              }}
            >
              Confirm Reset
            </button>
          </div>

          {error && (
            <div className="form-error-banner" style={{ marginBottom: '1rem' }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {successMsg && (
            <div
              className="section-card"
              style={{
                borderColor: 'var(--status-success-border)',
                backgroundColor: 'var(--status-success-bg)',
                color: 'var(--status-success-text)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.75rem 1rem',
                marginBottom: '1rem',
                fontSize: '0.84rem',
              }}
            >
              <CheckCircle2 size={16} />
              <span>{successMsg}</span>
            </div>
          )}

          {mode === 'request' ? (
            <form onSubmit={handleRequest} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="form-group">
                <label htmlFor="reset-email" className="form-label">
                  {t('auth.emailLabel')} <span className="required">*</span>
                </label>
                <div className="auth-input-wrap">
                  <Mail size={16} className="auth-input-icon" />
                  <input
                    id="reset-email"
                    type="email"
                    required
                    className="form-control"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={t('placeholders.workEmail', 'e.g. name@company.com')}
                  />
                </div>
              </div>
              <button type="submit" className="btn btn-primary btn-lg" disabled={submitting} style={{ width: '100%' }}>
                {submitting ? 'Sending...' : 'Request Reset Token'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleConfirm} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="form-group">
                <label htmlFor="reset-token" className="form-label">
                  Verification Token <span className="required">*</span>
                </label>
                <input
                  id="reset-token"
                  type="text"
                  required
                  className="form-control"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste reset token dispatched to email / dev outbox"
                />
              </div>
              <div className="form-group">
                <label htmlFor="reset-new-pw" className="form-label">
                  {t('auth.newPassword')} <span className="required">*</span>
                </label>
                <div className="auth-input-wrap">
                  <Lock size={16} className="auth-input-icon" />
                  <input
                    id="reset-new-pw"
                    type="password"
                    required
                    minLength={6}
                    className="form-control"
                    placeholder={t('placeholders.newPassword', 'Minimum 6 characters')}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </div>
                <span className="form-hint">{t('placeholders.newPassword', 'Minimum 6 characters')}</span>
              </div>
              <div className="form-group">
                <label htmlFor="reset-confirm-pw" className="form-label">
                  {t('auth.confirmPassword')} <span className="required">*</span>
                </label>
                <input
                  id="reset-confirm-pw"
                  type="password"
                  required
                  minLength={6}
                  className="form-control"
                  placeholder={t('placeholders.confirmPassword', 'Re-enter new password')}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </div>
              <button type="submit" className="btn btn-primary btn-lg" disabled={submitting} style={{ width: '100%' }}>
                {submitting ? 'Updating...' : t('auth.updatePassword')}
              </button>
            </form>
          )}

          <div style={{ marginTop: '1.25rem', textAlign: 'center', fontSize: '0.84rem' }}>
            <Link to="/login" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-brand)', fontWeight: 600 }}>
              <ArrowLeft size={14} />
              <span>Back to {t('common.signIn')}</span>
            </Link>
          </div>
        </div>
      </main>
    </div>
  )
}
