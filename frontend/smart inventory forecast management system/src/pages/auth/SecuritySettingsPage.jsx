import { useEffect, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { Shield, Lock, LogOut, UserCheck } from 'lucide-react'
import { api } from '../../api'
import { setCredentials, updateUserProfile, logout } from '../../store/authSlice'
import { addToast } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'

export default function SecuritySettingsPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { user, refreshToken } = useSelector((state) => state.auth)

  const [profileName, setProfileName] = useState(user?.name || '')
  const nameDirtyRef = useRef(false)
  const [savingProfile, setSavingProfile] = useState(false)

  useEffect(() => {
    if (!nameDirtyRef.current && user?.name) {
      setProfileName(user.name)
    }
  }, [user?.name])

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPw, setChangingPw] = useState(false)

  const handleSaveProfile = async (e) => {
    e.preventDefault()
    if (profileName.trim().length < 2) {
      dispatch(addToast({ type: 'error', message: 'Name must be at least 2 characters.' }))
      return
    }
    setSavingProfile(true)
    try {
      const updated = await api.updateMe({ name: profileName.trim() })
      nameDirtyRef.current = false
      dispatch(updateUserProfile(updated))
      dispatch(addToast({ type: 'success', message: 'Profile updated successfully.' }))
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to update profile.' }))
    } finally {
      setSavingProfile(false)
    }
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    if (newPassword.length < 6) {
      dispatch(addToast({ type: 'error', message: t('validation.passwordLength') }))
      return
    }
    if (newPassword !== confirmPassword) {
      dispatch(addToast({ type: 'error', message: t('validation.passwordMismatch') }))
      return
    }
    setChangingPw(true)
    try {
      const res = await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      dispatch(
        setCredentials({
          token: res.access_token,
          refreshToken: res.refresh_token,
          user: res.user,
        })
      )
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      dispatch(addToast({ type: 'success', message: 'Password updated and prior sessions invalidated.' }))
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Password change failed.' }))
    } finally {
      setChangingPw(false)
    }
  }

  const handleLogoutAll = async () => {
    try {
      await api.logout({ refresh_token: refreshToken, revoke_all: true })
    } catch {
      // still clear local session
    }
    dispatch(logout())
    navigate('/login', { replace: true })
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('auth.changePasswordTitle')}
        subtitle="Manage your profile identity, rotate password hashes, and revoke active sessions."
      />

      <div className="dashboard-grid-2">
        <div className="section-card">
          <div className="section-card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <UserCheck size={18} color="var(--erp-brand)" />
              <h2 className="section-card-title">User Profile</h2>
            </div>
          </div>
          <form onSubmit={handleSaveProfile} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="form-group">
              <label htmlFor="sec-name" className="form-label">
                {t('auth.nameLabel')} <span className="required">*</span>
              </label>
              <input
                id="sec-name"
                type="text"
                className="form-control"
                placeholder={t('placeholders.personName', 'e.g. Priya Sharma')}
                value={profileName}
                onChange={(e) => {
                  nameDirtyRef.current = true
                  setProfileName(e.target.value)
                }}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="sec-email" className="form-label">{t('auth.emailLabel')}</label>
              <input
                id="sec-email"
                type="email"
                className="form-control"
                value={user?.email || ''}
                disabled
              />
            </div>
            <div>
              <button type="submit" className="btn btn-primary" disabled={savingProfile}>
                {savingProfile ? t('common.saving') : t('common.save')}
              </button>
            </div>
          </form>
        </div>

        <div className="section-card">
          <div className="section-card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Lock size={18} color="var(--erp-brand)" />
              <h2 className="section-card-title">{t('auth.updatePassword')}</h2>
            </div>
          </div>
          <form onSubmit={handleChangePassword} style={{ display: 'flex', flexDirection: 'column', gap: '0.95rem' }}>
            <div className="form-group">
              <label htmlFor="curr-pw" className="form-label">
                {t('auth.currentPassword')} <span className="required">*</span>
              </label>
              <input
                id="curr-pw"
                type="password"
                className="form-control"
                placeholder={t('placeholders.currentPassword', 'Your current account password')}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-pw" className="form-label">
                {t('auth.newPassword')} <span className="required">*</span>
              </label>
              <input
                id="new-pw"
                type="password"
                className="form-control"
                placeholder={t('placeholders.newPassword', 'Minimum 6 characters')}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={6}
                required
              />
              <span className="form-hint">{t('placeholders.newPassword', 'Minimum 6 characters')}</span>
            </div>
            <div className="form-group">
              <label htmlFor="conf-pw" className="form-label">
                {t('auth.confirmPassword')} <span className="required">*</span>
              </label>
              <input
                id="conf-pw"
                type="password"
                className="form-control"
                placeholder={t('placeholders.confirmPassword', 'Re-enter new password')}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                minLength={6}
                required
              />
            </div>
            <div>
              <button type="submit" className="btn btn-primary" disabled={changingPw}>
                <Shield size={15} />
                <span>{changingPw ? t('common.saving') : t('auth.updatePassword')}</span>
              </button>
            </div>
          </form>
        </div>
      </div>

      <div className="section-card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: '0 0 0.25rem', fontSize: '0.95rem', color: 'var(--erp-text-main)' }}>
            {t('auth.logoutAllSessions')}
          </h3>
          <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
            Increments your security token version so every previously issued session is immediately rejected.
          </p>
        </div>
        <button type="button" className="btn btn-danger btn-sm" onClick={handleLogoutAll}>
          <LogOut size={15} />
          <span>{t('auth.logoutAllSessions')}</span>
        </button>
      </div>
    </div>
  )
}
