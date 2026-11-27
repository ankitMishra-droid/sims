import { useCallback, useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { Building2, Plus, ArrowRightLeft, MailCheck, CheckCircle2 } from 'lucide-react'
import { api } from '../../api'
import {
  setWorkspaces,
  switchWorkspaceReset,
  setCurrentWorkspace,
} from '../../store/authSlice'
import { addToast, setLanguage } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'
import Badge from '../../components/Badge'
import { LoadingState, EmptyState } from '../../components/common/StateBlocks'

export default function WorkspaceSetupPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t, language } = useTranslation()
  const { workspaces } = useSelector((state) => state.auth)

  const [loading, setLoading] = useState(true)
  const [invitations, setInvitations] = useState([])
  const [switchingId, setSwitchingId] = useState(null)
  const [creating, setCreating] = useState(false)
  const [acceptingToken, setAcceptingToken] = useState(null)

  const [name, setName] = useState('')
  const [businessType, setBusinessType] = useState('retailer')
  const [defaultLanguage, setDefaultLanguage] = useState(language || 'en')
  const [contactEmail, setContactEmail] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [address, setAddress] = useState('')

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [wsList, invList] = await Promise.all([
        api.getWorkspaces(),
        api.getMyInvitations(),
      ])
      dispatch(setWorkspaces(wsList))
      setInvitations(Array.isArray(invList) ? invList : [])
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to load workspaces.' }))
    } finally {
      setLoading(false)
    }
  }, [dispatch])

  useEffect(() => {
    const id = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(id)
  }, [loadData])

  const handleSwitch = async (bizId) => {
    setSwitchingId(bizId)
    try {
      const res = await api.switchWorkspace(bizId)
      dispatch(
        switchWorkspaceReset({
          token: res.access_token,
          refreshToken: res.refresh_token,
          user: res.user,
          workspace: res.workspace,
        })
      )
      await loadData()
      dispatch(addToast({ type: 'success', message: `Switched to ${res.workspace.business.name}` }))
      if (!res.workspace.business.onboarding_completed) {
        navigate('/onboarding')
      } else if (res.workspace.business.business_type === 'supplier') {
        navigate('/supplier-portal')
      } else {
        navigate('/dashboard')
      }
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Workspace switch failed.' }))
    } finally {
      setSwitchingId(null)
    }
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (name.trim().length < 2) {
      dispatch(addToast({ type: 'error', message: t('validation.workspaceNameLength') }))
      return
    }
    setCreating(true)
    try {
      const ws = await api.createWorkspace({
        name: name.trim(),
        business_type: businessType,
        default_language: defaultLanguage,
        contact_email: contactEmail.trim() || null,
        contact_phone: contactPhone.trim() || null,
        address: address.trim() || null,
      })
      const refreshedUser = await api.getMe()
      dispatch(
        switchWorkspaceReset({
          user: refreshedUser,
          workspace: ws,
        })
      )
      dispatch(setLanguage(defaultLanguage))
      dispatch(setCurrentWorkspace(ws))
      dispatch(addToast({ type: 'success', message: `Workspace "${ws.business.name}" created!` }))
      navigate('/onboarding')
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to create workspace.' }))
    } finally {
      setCreating(false)
    }
  }

  const handleAcceptInvite = async (token) => {
    setAcceptingToken(token)
    try {
      const ws = await api.acceptInvitation(token)
      const refreshedUser = await api.getMe()
      dispatch(switchWorkspaceReset({ user: refreshedUser, workspace: ws }))
      dispatch(addToast({ type: 'success', message: `Joined ${ws.business.name}!` }))
      await loadData()
      navigate(
        !ws.business.onboarding_completed
          ? '/onboarding'
          : ws.business.business_type === 'supplier'
          ? '/supplier-portal'
          : '/dashboard'
      )
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to accept invitation.' }))
    } finally {
      setAcceptingToken(null)
    }
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('workspace.switchTitle')}
        subtitle={t('workspace.createSubtitle')}
      />

      {loading ? (
        <LoadingState message={t('common.loading')} />
      ) : (
        <div className="dashboard-grid-2">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
            <div className="section-card">
              <div className="section-card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Building2 size={18} color="var(--erp-brand)" />
                  <h2 className="section-card-title">Authorized Workspaces ({workspaces.length})</h2>
                </div>
              </div>

              {workspaces.length === 0 ? (
                <EmptyState
                  title="No Business Workspace Yet"
                  description={t('workspace.noWorkspaces')}
                  icon={Building2}
                />
              ) : (
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                  {workspaces.map((ws) => (
                    <div
                      key={ws.business.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '0.9rem 1rem',
                        borderRadius: 'var(--radius-lg)',
                        border: ws.is_active_workspace ? '2px solid var(--erp-brand)' : '1px solid var(--erp-border)',
                        backgroundColor: ws.is_active_workspace ? 'var(--erp-brand-subtle)' : 'var(--erp-surface-subtle)',
                        flexWrap: 'wrap',
                      }}
                    >
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                          <strong style={{ color: 'var(--erp-text-main)' }}>{ws.business.name}</strong>
                          <Badge status="SENT" label={ws.business.business_type.toUpperCase()} />
                          <Badge status="ACTIVE" label={ws.role.toUpperCase()} />
                        </div>
                        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--erp-text-muted)', marginTop: '0.25rem' }}>
                          {ws.business.onboarding_completed ? 'Setup Complete' : 'Onboarding In Progress'} • ID #{ws.business.id}
                        </div>
                      </div>

                      {ws.is_active_workspace ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-brand)', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)' }}>
                          <CheckCircle2 size={15} />
                          Active
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={switchingId === ws.business.id}
                          onClick={() => handleSwitch(ws.business.id)}
                        >
                          <ArrowRightLeft size={14} />
                          <span>{switchingId === ws.business.id ? 'Switching...' : 'Switch'}</span>
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {invitations.length > 0 && (
              <div className="section-card">
                <div className="section-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <MailCheck size={18} color="var(--erp-brand)" />
                    <h2 className="section-card-title">{t('workspace.pendingInvites')}</h2>
                  </div>
                </div>
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                  {invitations.map((inv) => (
                    <div
                      key={inv.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '0.85rem 1rem',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--erp-surface-subtle)',
                        border: '1px solid var(--erp-border)',
                        gap: '0.75rem',
                        flexWrap: 'wrap',
                      }}
                    >
                      <div>
                        <strong style={{ color: 'var(--erp-text-main)' }}>{inv.business_name}</strong>
                        <div style={{ fontSize: '0.76rem', color: 'var(--erp-text-muted)' }}>
                          Role: {inv.role.toUpperCase()} • Type: {inv.business_type}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={acceptingToken === inv.token}
                        onClick={() => handleAcceptInvite(inv.token)}
                      >
                        {acceptingToken === inv.token ? 'Joining...' : 'Accept & Join'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="section-card">
            <div className="section-card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Plus size={18} color="var(--erp-brand)" />
                <h2 className="section-card-title">{t('workspace.createTitle')}</h2>
              </div>
            </div>
            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="form-group">
                <label htmlFor="ws-name" className="form-label">
                  Business Name <span className="required">*</span>
                </label>
                <input
                  id="ws-name"
                  type="text"
                  className="form-control"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Sangati Supermart"
                  required
                />
              </div>

              <div className="form-grid">
                <div className="form-group">
                  <label htmlFor="ws-type" className="form-label">
                    Business Type <span className="required">*</span>
                  </label>
                  <select
                    id="ws-type"
                    className="form-control"
                    value={businessType}
                    onChange={(e) => setBusinessType(e.target.value)}
                  >
                    <option value="retailer">{t('workspace.types.retailer')}</option>
                    <option value="wholesaler">{t('workspace.types.wholesaler')}</option>
                    <option value="supplier">{t('workspace.types.supplier')}</option>
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="ws-lang" className="form-label">Default Language</label>
                  <select
                    id="ws-lang"
                    className="form-control"
                    value={defaultLanguage}
                    onChange={(e) => setDefaultLanguage(e.target.value)}
                  >
                    <option value="en">English</option>
                    <option value="hi">हिन्दी (Hindi)</option>
                  </select>
                </div>
              </div>

              <div className="form-grid">
                <div className="form-group">
                  <label htmlFor="ws-email" className="form-label">Business Email</label>
                  <input
                    id="ws-email"
                    type="email"
                    className="form-control"
                    value={contactEmail}
                    onChange={(e) => setContactEmail(e.target.value)}
                    placeholder="contact@business.com"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="ws-phone" className="form-label">Phone</label>
                  <input
                    id="ws-phone"
                    type="text"
                    className="form-control"
                    value={contactPhone}
                    onChange={(e) => setContactPhone(e.target.value)}
                    placeholder="+91 98765 43210"
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="ws-address" className="form-label">Address</label>
                <input
                  id="ws-address"
                  type="text"
                  className="form-control"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="Street, City, State"
                />
              </div>

              <div>
                <button type="submit" className="btn btn-primary" disabled={creating}>
                  <Plus size={15} />
                  <span>{creating ? t('common.saving') : t('workspace.createTitle')}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
