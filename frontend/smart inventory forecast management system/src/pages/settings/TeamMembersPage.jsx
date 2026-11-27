import { useCallback, useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Users, UserPlus, Trash2, Copy, XCircle } from 'lucide-react'
import { api } from '../../api'
import { addToast } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'
import Badge from '../../components/Badge'
import { LoadingState, ErrorState } from '../../components/common/StateBlocks'

export default function TeamMembersPage() {
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const { currentWorkspace, user } = useSelector((state) => state.auth)
  const perms = currentWorkspace?.permissions || []
  const canInvite = perms.includes('members.invite')
  const canManageRoles = perms.includes('members.manage_roles')
  const isOwner = currentWorkspace?.role === 'owner'

  const [members, setMembers] = useState([])
  const [invitations, setInvitations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('staff')
  const [submitting, setSubmitting] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const mList = await api.getMembers()
      setMembers(Array.isArray(mList) ? mList : [])
      if (canInvite) {
        const iList = await api.getInvitations()
        setInvitations(Array.isArray(iList) ? iList : [])
      }
    } catch (err) {
      setError(err.message || 'Failed to load workspace members.')
    } finally {
      setLoading(false)
    }
  }, [canInvite])

  useEffect(() => {
    const id = setTimeout(() => {
      loadAll()
    }, 0)
    return () => clearTimeout(id)
  }, [loadAll])

  const handleInvite = async (e) => {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    setSubmitting(true)
    try {
      await api.inviteMember({ email: inviteEmail.trim(), role: inviteRole })
      setInviteEmail('')
      dispatch(addToast({ type: 'success', message: 'Invitation created cleanly.' }))
      await loadAll()
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to send invitation.' }))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRoleChange = async (memberId, role) => {
    try {
      await api.updateMemberRole(memberId, role)
      dispatch(addToast({ type: 'success', message: 'Member role updated.' }))
      await loadAll()
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Role update failed.' }))
    }
  }

  const handleRemove = async (memberId) => {
    try {
      await api.removeMember(memberId)
      dispatch(addToast({ type: 'info', message: 'Member removed from workspace.' }))
      await loadAll()
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to remove member.' }))
    }
  }

  const handleRevokeInvite = async (invId) => {
    try {
      await api.revokeInvitation(invId)
      dispatch(addToast({ type: 'info', message: 'Invitation revoked.' }))
      await loadAll()
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to revoke invitation.' }))
    }
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('workspace.teamTitle')}
        subtitle="Role-based access control enforced on the backend for your active business workspace."
      />

      {error && <ErrorState message={error} onRetry={loadAll} />}

      {loading ? (
        <LoadingState message={t('common.loading')} />
      ) : (
        <div className="dashboard-grid-2">
          <div className="section-card">
            <div className="section-card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Users size={18} color="var(--erp-brand)" />
                <h2 className="section-card-title">Active Members ({members.filter((m) => m.is_active).length})</h2>
              </div>
            </div>
            <div style={{ display: 'grid', gap: '0.7rem' }}>
              {members.map((m) => (
                <div
                  key={m.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '0.75rem',
                    padding: '0.8rem 0.9rem',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--erp-surface-subtle)',
                    border: '1px solid var(--erp-border)',
                    opacity: m.is_active ? 1 : 0.6,
                    flexWrap: 'wrap',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
                      {m.user_name} {m.user_id === user?.id ? '(You)' : ''}
                    </div>
                    <div style={{ fontSize: '0.76rem', color: 'var(--erp-text-muted)' }}>
                      {m.user_email}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    {canManageRoles && m.role !== 'owner' && m.is_active ? (
                      <>
                        <select
                          className="form-control"
                          style={{ width: 'auto', padding: '0.3rem 0.6rem', fontSize: '0.8rem' }}
                          value={m.role}
                          onChange={(e) => handleRoleChange(m.id, e.target.value)}
                          disabled={!isOwner && m.role === 'admin'}
                        >
                          {isOwner && <option value="admin">Admin</option>}
                          <option value="manager">Manager</option>
                          <option value="analyst">Analyst</option>
                          <option value="staff">Staff</option>
                          <option value="supplier">Supplier</option>
                        </select>
                        {m.user_id !== user?.id && (
                          <button
                            type="button"
                            className="btn-action-icon danger"
                            onClick={() => handleRemove(m.id)}
                            title="Deactivate member"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </>
                    ) : (
                      <Badge status={m.is_active ? 'ACTIVE' : 'INACTIVE'} label={m.role.toUpperCase()} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {canInvite && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
              <div className="section-card">
                <div className="section-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <UserPlus size={18} color="var(--erp-brand)" />
                    <h2 className="section-card-title">{t('workspace.inviteMember')}</h2>
                  </div>
                </div>
                <form onSubmit={handleInvite} style={{ display: 'flex', flexDirection: 'column', gap: '0.95rem' }}>
                  <div className="form-group">
                    <label htmlFor="inv-email" className="form-label">
                      Member Email <span className="required">*</span>
                    </label>
                    <input
                      id="inv-email"
                      type="email"
                      className="form-control"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="colleague@company.com"
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="inv-role" className="form-label">Assigned Role</label>
                    <select
                      id="inv-role"
                      className="form-control"
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value)}
                    >
                      {isOwner && <option value="admin">Admin (Operations + Member Admin)</option>}
                      <option value="manager">Manager (Inventory, Products & POs)</option>
                      <option value="analyst">Analyst (Read-only & Forecasting)</option>
                      <option value="staff">Staff (Sales & Stock Receiving)</option>
                      <option value="supplier">Supplier User</option>
                    </select>
                  </div>
                  <div>
                    <button type="submit" className="btn btn-primary" disabled={submitting}>
                      <UserPlus size={15} />
                      <span>{submitting ? 'Inviting...' : t('workspace.inviteMember')}</span>
                    </button>
                  </div>
                </form>
              </div>

              <div className="section-card">
                <div className="section-card-header">
                  <h2 className="section-card-title">{t('workspace.pendingInvites')}</h2>
                </div>
                {invitations.length === 0 ? (
                  <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
                    No invitations issued yet.
                  </p>
                ) : (
                  <div style={{ display: 'grid', gap: '0.6rem' }}>
                    {invitations.map((inv) => (
                      <div
                        key={inv.id}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          gap: '0.5rem',
                          padding: '0.7rem 0.85rem',
                          borderRadius: 'var(--radius-md)',
                          backgroundColor: 'var(--erp-surface-subtle)',
                          border: '1px solid var(--erp-border)',
                          fontSize: '0.8rem',
                        }}
                      >
                        <div>
                          <strong style={{ color: 'var(--erp-text-main)' }}>{inv.email}</strong>
                          <div style={{ color: 'var(--erp-text-muted)' }}>
                            {inv.role.toUpperCase()} • {inv.status}
                          </div>
                        </div>
                        <div style={{ display: 'flex', gap: '0.35rem' }}>
                          {inv.status === 'PENDING' && (
                            <>
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                title="Copy invite token"
                                onClick={() => {
                                  navigator.clipboard?.writeText(inv.token)
                                  dispatch(addToast({ type: 'info', message: 'Invitation token copied.' }))
                                }}
                              >
                                <Copy size={13} />
                              </button>
                              <button
                                type="button"
                                className="btn-action-icon danger"
                                title="Revoke invitation"
                                onClick={() => handleRevokeInvite(inv.id)}
                              >
                                <XCircle size={14} />
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
