import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Menu, Search, Sun, Moon, LogOut, UserCircle, Languages, Building2 } from 'lucide-react'
import {
  setCommandPaletteOpen,
  toggleMobileSidebar,
  toggleTheme,
  setLanguage,
  addToast,
} from '../../store/uiSlice'
import { logout, switchWorkspaceReset, updateUserProfile, setWorkspaces } from '../../store/authSlice'
import { api } from '../../api'
import { useTranslation } from '../../hooks/useTranslation'

export default function TopHeader() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const theme = useSelector((state) => state.ui.theme)
  const { user, refreshToken, workspaces, currentWorkspace, isAuthenticated } = useSelector((state) => state.auth)
  const [switching, setSwitching] = useState(false)

  const handleLogout = async () => {
    try {
      await api.logout({ refresh_token: refreshToken })
    } catch {
      // proceed clearing local state regardless
    }
    dispatch(logout())
    navigate('/login', { replace: true })
  }

  const handleLanguageToggle = async () => {
    const next = language === 'en' ? 'hi' : 'en'
    dispatch(setLanguage(next))
    if (isAuthenticated) {
      try {
        const updated = await api.updateMe({ preferred_language: next })
        dispatch(updateUserProfile(updated))
      } catch {
        // non-blocking
      }
    }
  }

  const handleWorkspaceChange = async (e) => {
    const val = e.target.value
    if (val === '__manage__') {
      navigate('/workspaces')
      return
    }
    const targetId = Number(val)
    if (!targetId || targetId === currentWorkspace?.business?.id) return
    setSwitching(true)
    try {
      const res = await api.switchWorkspace(targetId)
      dispatch(
        switchWorkspaceReset({
          token: res.access_token,
          refreshToken: res.refresh_token,
          user: res.user,
          workspace: res.workspace,
        })
      )
      const list = await api.getWorkspaces()
      dispatch(setWorkspaces(list))
      dispatch(addToast({ type: 'success', message: `Workspace: ${res.workspace.business.name}` }))
      navigate(res.workspace.business.business_type === 'supplier' ? '/supplier-portal' : '/dashboard')
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Workspace switch failed' }))
    } finally {
      setSwitching(false)
    }
  }

  return (
    <header className="app-header">
      <div className="app-header-left">
        <button
          type="button"
          className="mobile-menu-btn"
          onClick={() => dispatch(toggleMobileSidebar())}
          aria-label="Open navigation menu"
        >
          <Menu size={18} />
        </button>

        <button
          type="button"
          className="header-chip-btn"
          onClick={() => dispatch(setCommandPaletteOpen(true))}
          title="Quick Search (Ctrl+K)"
        >
          <Search size={14} />
          <span>{t('common.quickSearch', 'Quick search...')}</span>
          <kbd style={{ fontSize: '0.675rem', opacity: 0.7, fontFamily: 'var(--font-mono)' }}>Ctrl+K</kbd>
        </button>

        {workspaces.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <Building2 size={14} style={{ color: 'var(--erp-brand)' }} />
            <select
              aria-label="Switch active business workspace"
              disabled={switching}
              value={currentWorkspace?.business?.id || ''}
              onChange={handleWorkspaceChange}
              className="header-workspace-select"
            >
              {workspaces.map((ws) => (
                <option key={ws.business.id} value={ws.business.id}>
                  {ws.business.name} ({ws.business.business_type})
                </option>
              ))}
              <option value="__manage__">+ Manage / Create Workspace</option>
            </select>
          </div>
        )}
      </div>

      <div className="app-header-right">
        <button
          type="button"
          className="header-chip-btn"
          onClick={handleLanguageToggle}
          title="Switch Language (English / Hindi)"
        >
          <Languages size={14} />
          <span>{language === 'hi' ? 'हिन्दी' : language.toUpperCase()}</span>
        </button>

        <button
          type="button"
          className="header-chip-btn"
          onClick={() => dispatch(toggleTheme())}
          aria-label="Toggle color theme"
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </button>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.3rem 0.65rem',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--erp-border)',
            fontSize: '0.775rem',
          }}
        >
          <UserCircle size={15} style={{ color: 'var(--erp-brand)' }} />
          <span style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
            {user?.name || 'User'}
          </span>
          <span style={{ color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontSize: '0.675rem' }}>
            {currentWorkspace?.role || user?.role}
          </span>
        </div>

        <button
          type="button"
          className="header-chip-btn"
          onClick={handleLogout}
          title={t('common.signOut', 'Sign Out')}
          style={{ color: 'var(--status-danger-text)' }}
        >
          <LogOut size={14} />
          <span>{t('common.signOut', 'Sign Out')}</span>
        </button>
      </div>
    </header>
  )
}
