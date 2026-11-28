import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Menu, Search, Sun, Moon, LogOut, UserCircle, Languages, Building2, Sparkles } from 'lucide-react'
import {
  setCommandPaletteOpen,
  toggleMobileSidebar,
  toggleTheme,
} from '../../store/uiSlice'
import { toggleAssistantOpen } from '../../store/aiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import { useSessionActions } from '../../hooks/useSessionActions'
import faviconImg from '../../assets/images/favicon.png'

export default function TopHeader() {
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const { getHomePath, switchWorkspace, toggleLanguage, signOut } = useSessionActions()
  const theme = useSelector((state) => state.ui.theme)
  const mobileOpen = useSelector((state) => state.ui.mobileSidebarOpen)
  const { isOpen: aiOpen, isMinimized: aiMinimized } = useSelector((state) => state.ai)
  const { user, workspaces, currentWorkspace, isAuthenticated } = useSelector((state) => state.auth)
  const [switching, setSwitching] = useState(false)
  const canUseAi = Boolean(isAuthenticated && user && currentWorkspace?.business?.id)
  const isAiExpanded = Boolean(canUseAi && aiOpen && !aiMinimized)

  const handleWorkspaceChange = async (e) => {
    setSwitching(true)
    try {
      await switchWorkspace(e.target.value)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <header className="app-header">
      <div className="app-header-left">
        <Link to={getHomePath()} className="mobile-header-brand" aria-label={t('brandName', 'StockSangati')}>
          <img src={faviconImg} alt="StockSangati" className="sidebar-logo" />
          <span className="mobile-header-brand-text">{t('brandName', 'StockSangati')}</span>
        </Link>

        <button
          type="button"
          className="header-chip-btn desktop-only"
          onClick={() => dispatch(setCommandPaletteOpen(true))}
          title="Quick Search (Ctrl+K)"
        >
          <Search size={14} />
          <span>{t('common.quickSearch', 'Quick search...')}</span>
          <kbd className="header-search-kbd" style={{ fontSize: '0.675rem', opacity: 0.7, fontFamily: 'var(--font-mono)' }}>Ctrl+K</kbd>
        </button>

        {workspaces.length > 0 && (
          <div className="desktop-only" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', minWidth: 0 }}>
            <Building2 size={14} style={{ color: 'var(--erp-brand)', flexShrink: 0 }} />
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
          id="mobile-nav-toggle-btn"
          className="mobile-menu-btn"
          onClick={() => dispatch(toggleMobileSidebar())}
          aria-label={mobileOpen ? t('common.closeMenu', 'Close navigation menu') : t('common.openMenu', 'Open navigation menu')}
          aria-expanded={mobileOpen}
          aria-controls="app-navigation-drawer"
        >
          <Menu size={18} />
        </button>

        {canUseAi && (
          <button
            type="button"
            className={`header-chip-btn header-ai-btn desktop-only ${isAiExpanded ? 'active' : ''}`}
            onClick={() => dispatch(toggleAssistantOpen())}
            title={t('ai.assistantTooltip', 'Open AI Assistant')}
            aria-label={t('ai.navButton', 'StockSangati AI')}
            aria-expanded={isAiExpanded}
            aria-controls="stocksangati-ai-dialog"
          >
            <Sparkles size={14} />
            <span>{t('ai.navButton', 'StockSangati AI')}</span>
          </button>
        )}

        <button
          type="button"
          className="header-chip-btn desktop-only"
          onClick={toggleLanguage}
          title="Switch Language (English / Hindi)"
        >
          <Languages size={14} />
          <span>{language === 'hi' ? 'हिन्दी' : language.toUpperCase()}</span>
        </button>

        <button
          type="button"
          className="header-chip-btn desktop-only"
          onClick={() => dispatch(toggleTheme())}
          aria-label="Toggle color theme"
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </button>

        <div className="header-user-chip desktop-only">
          <UserCircle size={15} style={{ color: 'var(--erp-brand)', flexShrink: 0 }} />
          <span style={{ fontWeight: 600, color: 'var(--erp-text-main)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {user?.name || 'User'}
          </span>
          <span style={{ color: 'var(--erp-text-muted)', textTransform: 'uppercase', fontSize: '0.675rem', flexShrink: 0 }}>
            {currentWorkspace?.role || user?.role}
          </span>
        </div>

        <button
          type="button"
          className="header-chip-btn desktop-only"
          onClick={signOut}
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
