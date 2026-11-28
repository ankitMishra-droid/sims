import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  LayoutDashboard,
  Package,
  Boxes,
  History,
  SlidersHorizontal,
  ShoppingCart,
  Receipt,
  Truck,
  ClipboardList,
  Inbox,
  CheckCircle2,
  BrainCircuit,
  Sliders,
  AlertTriangle,
  BookOpen,
  Coins,
  FileBarChart2,
  TrendingUp,
  ClipboardCheck,
  Languages,
  Building2,
  Sparkles,
  Users,
  Shield,
  PackageCheck,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Bell,
  Sun,
  Moon,
  LogOut,
  UserCircle,
  Settings,
  X,
} from 'lucide-react'
import {
  findActiveNavGroupId,
  setAlertsUnreadCount,
  setCommandPaletteOpen,
  setExpandedNavGroup,
  setMobileSidebarOpen,
  toggleNavGroup,
  toggleSidebarCollapsed,
  toggleTheme,
} from '../../store/uiSlice'
import { toggleAssistantOpen } from '../../store/aiSlice'
import { api } from '../../api'
import { useTranslation } from '../../hooks/useTranslation'
import { useSessionActions } from '../../hooks/useSessionActions'
import faviconImg from '../../assets/images/favicon.png'

const NAV_GROUPS = [
  {
    id: 'overview',
    labelKey: 'groups.overview',
    businessTypes: ['retailer', 'wholesaler'],
    items: [
      { key: 'nav.dashboard', path: '/dashboard', icon: LayoutDashboard },
    ],
  },
  {
    id: 'supplierPortal',
    labelKey: 'groups.supplierPortal',
    businessTypes: ['supplier'],
    items: [
      { key: 'nav.supplierOrders', path: '/supplier-portal', icon: PackageCheck },
    ],
  },
  {
    id: 'inventory',
    labelKey: 'groups.inventory',
    businessTypes: ['retailer', 'wholesaler'],
    items: [
      { key: 'nav.products', path: '/products', icon: Package },
      { key: 'nav.stockManagement', path: '/inventory', icon: Boxes, end: true },
      { key: 'nav.stockHistory', path: '/inventory/history', icon: History },
      { key: 'nav.stockAdjustments', path: '/inventory/adjustments', icon: SlidersHorizontal, permission: 'inventory.write' },
    ],
  },
  {
    id: 'sales',
    labelKey: 'groups.sales',
    businessTypes: ['retailer', 'wholesaler'],
    items: [
      { key: 'nav.recordSale', path: '/sales/new', icon: ShoppingCart, permission: 'sales.create' },
      { key: 'nav.salesHistory', path: '/sales', icon: Receipt, end: true },
    ],
  },
  {
    id: 'procurement',
    labelKey: 'groups.procurement',
    businessTypes: ['retailer', 'wholesaler'],
    items: [
      { key: 'nav.suppliers', path: '/suppliers', icon: Truck },
      { key: 'nav.purchaseOrders', path: '/purchase-orders', icon: ClipboardList },
      { key: 'nav.receiveOrders', path: '/receive-order', icon: Inbox, permission: 'po.receive' },
    ],
  },
  {
    id: 'intelligence',
    labelKey: 'groups.intelligence',
    businessTypes: ['retailer', 'wholesaler'],
    items: [
      { key: 'nav.intelligenceOverview', path: '/intelligence', icon: TrendingUp },
      { key: 'nav.reorderSuggestions', path: '/reorder-planner', icon: CheckCircle2 },
      { key: 'nav.demandForecasts', path: '/forecasting', icon: BrainCircuit },
      { key: 'nav.whatIfSimulator', path: '/simulator', icon: Sliders },
      { key: 'nav.stockAlerts', path: '/stock-alerts', icon: AlertTriangle },
    ],
  },
  {
    id: 'reports',
    labelKey: 'groups.reports',
    businessTypes: ['retailer', 'wholesaler'],
    permission: 'reports.read',
    items: [
      { key: 'nav.inventoryReports', path: '/reports/inventory', icon: FileBarChart2 },
      { key: 'nav.salesReports', path: '/reports/sales', icon: TrendingUp },
      { key: 'nav.procurementReports', path: '/reports/procurement', icon: ClipboardCheck },
    ],
  },
  {
    id: 'assistant',
    labelKey: 'groups.assistant',
    businessTypes: ['retailer', 'wholesaler', 'supplier'],
    items: [
      { key: 'nav.aiKnowledge', path: '/ai-knowledge', icon: BookOpen, permission: 'ai.documents.read' },
      { key: 'nav.aiUsage', path: '/ai-usage', icon: Coins, permission: 'ai.credits.read' },
    ],
  },
  {
    id: 'settings',
    labelKey: 'groups.settings',
    items: [
      { key: 'nav.workspaces', path: '/workspaces', icon: Building2 },
      { key: 'nav.onboarding', path: '/onboarding', icon: Sparkles, permission: 'onboarding.manage' },
      { key: 'nav.businessProfile', path: '/settings/business', icon: Building2, permission: 'business.read' },
      { key: 'nav.members', path: '/settings/team', icon: Users, permission: 'members.read' },
      { key: 'nav.accountSecurity', path: '/settings/security', icon: Shield },
      { key: 'nav.language', path: '/settings/language', icon: Languages },
    ],
  },
]

function isItemActiveForPath(item, pathname) {
  if (pathname === item.path) return true
  return !item.end && pathname.startsWith(`${item.path}/`)
}

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const dispatch = useDispatch()
  const { t, language } = useTranslation()
  const { getHomePath, switchWorkspace, toggleLanguage, signOut } = useSessionActions()

  const {
    mobileSidebarOpen: mobileOpen,
    sidebarCollapsed,
    expandedNavGroup,
    theme,
    alertsUnreadCount,
  } = useSelector((state) => state.ui)
  const { user, workspaces, currentWorkspace, isAuthenticated } = useSelector((state) => state.auth)

  const [switchingWs, setSwitchingWs] = useState(false)
  const closeBtnRef = useRef(null)
  const prevPathRef = useRef(null)
  const wasMobileOpenRef = useRef(false)

  const businessType = currentWorkspace?.business?.business_type || (user?.role === 'supplier' ? 'supplier' : 'retailer')
  const perms = useMemo(
    () => currentWorkspace?.permissions || [],
    [currentWorkspace?.permissions]
  )
  const hasWorkspace = Boolean(currentWorkspace?.business?.id)
  const setupCompleted = Boolean(currentWorkspace?.business?.onboarding_completed)
  const canUseAi = Boolean(isAuthenticated && user && hasWorkspace)
  const canSeeAlerts = Boolean(hasWorkspace && setupCompleted && businessType !== 'supplier')

  const visibleGroups = useMemo(
    () =>
      NAV_GROUPS.map((group) => {
        if ((!hasWorkspace || !setupCompleted) && group.id !== 'settings') return null
        if (group.businessTypes && !group.businessTypes.includes(businessType)) return null
        if (group.permission && perms.length > 0 && !perms.includes(group.permission)) return null
        const items = group.items.filter((item) => {
          if (!hasWorkspace && !['/workspaces', '/settings/security', '/settings/language'].includes(item.path)) {
            return false
          }
          if (
            hasWorkspace &&
            !setupCompleted &&
            !['/onboarding', '/workspaces', '/settings/security', '/settings/language'].includes(item.path)
          ) {
            return false
          }
          if (item.permission && perms.length > 0 && !perms.includes(item.permission)) return false
          return true
        })
        if (items.length === 0) return null
        return { ...group, items }
      }).filter(Boolean),
    [hasWorkspace, setupCompleted, businessType, perms]
  )

  const activeRouteGroupId = useMemo(
    () => findActiveNavGroupId(visibleGroups, location.pathname),
    [visibleGroups, location.pathname]
  )

  // Expand only the active route group when route changes; never expand all groups automatically
  useEffect(() => {
    const pathKey = `${location.pathname}|${hasWorkspace}|${setupCompleted}|${businessType}`
    if (prevPathRef.current !== pathKey) {
      prevPathRef.current = pathKey
      if (activeRouteGroupId) {
        dispatch(setExpandedNavGroup(activeRouteGroupId))
      } else if (visibleGroups.length > 0 && !expandedNavGroup) {
        dispatch(setExpandedNavGroup(visibleGroups[0].id))
      }
    }
  }, [
    location.pathname,
    hasWorkspace,
    setupCompleted,
    businessType,
    activeRouteGroupId,
    visibleGroups,
    expandedNavGroup,
    dispatch,
  ])

  // Fetch alert unread count when mobile drawer opens for notification badge
  useEffect(() => {
    if (!mobileOpen || !canSeeAlerts) return undefined
    let active = true
    api
      .getStockAlerts(false)
      .then((res) => {
        if (active) dispatch(setAlertsUnreadCount(Number(res?.unread_count || 0)))
      })
      .catch(() => {
        // non-blocking
      })
    return () => {
      active = false
    }
  }, [mobileOpen, canSeeAlerts, dispatch])

  // Close mobile drawer automatically on route change and lock background scroll on mobile open
  useEffect(() => {
    if (!mobileOpen) {
      if (wasMobileOpenRef.current) {
        wasMobileOpenRef.current = false
        document.getElementById('mobile-nav-toggle-btn')?.focus()
      }
      return undefined
    }

    wasMobileOpenRef.current = true
    const isMobileViewport =
      typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 960px)').matches
    const prevOverflow = document.body.style.overflow
    if (isMobileViewport) {
      document.body.style.overflow = 'hidden'
    }

    const focusTimer = window.setTimeout(() => {
      closeBtnRef.current?.focus()
    }, 10)

    const onKeyDown = (e) => {
      if (e.key === 'Escape' && !e.defaultPrevented) {
        e.preventDefault()
        dispatch(setMobileSidebarOpen(false))
      }
    }
    window.addEventListener('keydown', onKeyDown)

    return () => {
      window.clearTimeout(focusTimer)
      window.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [mobileOpen, dispatch])

  const closeMobile = () => dispatch(setMobileSidebarOpen(false))

  const handleMobileNavAction = (actionFn) => {
    actionFn()
    closeMobile()
  }

  const handleMobileWorkspaceChange = async (e) => {
    setSwitchingWs(true)
    try {
      await switchWorkspace(e.target.value)
    } finally {
      setSwitchingWs(false)
    }
  }

  const effectiveExpandedGroupId = expandedNavGroup

  return (
    <>
      <div
        className={`sidebar-backdrop ${mobileOpen ? 'open' : ''}`}
        onClick={closeMobile}
        aria-hidden="true"
      />
      <aside
        id="app-navigation-drawer"
        className={`app-sidebar ${mobileOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}`}
        aria-label="Primary Navigation"
      >
        <div
          className="sidebar-brand"
          onClick={() => {
            navigate(getHomePath())
            closeMobile()
          }}
        >
          <div className="sidebar-brand-left">
            <img src={faviconImg} alt="StockSangati" className="sidebar-logo" />
            {!sidebarCollapsed && (
              <div className="sidebar-brand-meta" style={{ minWidth: 0 }}>
                <div className="sidebar-brand-name">{t('brandName', 'StockSangati')}</div>
                <div className="sidebar-brand-tag">{t('brandTagline')}</div>
              </div>
            )}
          </div>
          <div className="sidebar-brand-actions" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="sidebar-collapse-btn"
              onClick={() => dispatch(toggleSidebarCollapsed())}
              title={
                sidebarCollapsed
                  ? t('common.expandSidebar', 'Expand sidebar')
                  : t('common.collapseSidebar', 'Collapse sidebar')
              }
              aria-label={
                sidebarCollapsed
                  ? t('common.expandSidebar', 'Expand sidebar')
                  : t('common.collapseSidebar', 'Collapse sidebar')
              }
              aria-pressed={sidebarCollapsed}
            >
              {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
            <button
              ref={closeBtnRef}
              type="button"
              className="sidebar-close-btn"
              onClick={closeMobile}
              aria-label="Close navigation menu"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Mobile-only controls unified inside accessible drawer */}
        <div className="sidebar-mobile-panel">
          <div className="sidebar-mobile-user-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
              <UserCircle size={20} style={{ color: 'var(--erp-brand)', flexShrink: 0 }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: '0.84rem', color: 'var(--erp-text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user?.name || 'User'}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--erp-text-muted)', textTransform: 'uppercase' }}>
                  {currentWorkspace?.role || user?.role || 'staff'}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => handleMobileNavAction(() => navigate('/settings/security'))}
              title={t('common.accountSettings', 'Account Settings')}
            >
              <Settings size={13} />
              <span>{t('common.accountSettings', 'Account Settings')}</span>
            </button>
          </div>

          {workspaces.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Building2 size={14} style={{ color: 'var(--erp-brand)', flexShrink: 0 }} />
              <select
                aria-label="Switch active business workspace"
                disabled={switchingWs}
                value={currentWorkspace?.business?.id || ''}
                onChange={handleMobileWorkspaceChange}
                className="form-control"
                style={{ padding: '0.4rem 0.6rem', fontSize: '0.8rem' }}
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

          <div className="sidebar-mobile-quick-actions">
            {canUseAi && (
              <button
                type="button"
                className="header-chip-btn header-ai-btn"
                onClick={() => handleMobileNavAction(() => dispatch(toggleAssistantOpen()))}
              >
                <Sparkles size={14} />
                <span>{t('ai.navButton', 'StockSangati AI')}</span>
              </button>
            )}

            {canSeeAlerts && (
              <button
                type="button"
                className="header-chip-btn"
                onClick={() => handleMobileNavAction(() => navigate('/stock-alerts'))}
              >
                <Bell size={14} />
                <span>{t('common.notifications', 'Alerts')}</span>
                {alertsUnreadCount > 0 && (
                  <span className="mobile-alert-pill">{alertsUnreadCount}</span>
                )}
              </button>
            )}

            <button
              type="button"
              className="header-chip-btn"
              onClick={() => handleMobileNavAction(() => dispatch(setCommandPaletteOpen(true)))}
            >
              <Search size={14} />
              <span>{t('common.search', 'Search')}</span>
            </button>
          </div>
        </div>

        <nav className="sidebar-nav">
          {visibleGroups.map((group) => {
            const isExpanded = effectiveExpandedGroupId === group.id
            const groupContainsActive = group.id === activeRouteGroupId
            const itemsToRender = sidebarCollapsed
              ? isExpanded || groupContainsActive
                ? group.items
                : [group.items[0]]
              : isExpanded
                ? group.items
                : []

            return (
              <div key={group.id} className="sidebar-group-block">
                {!sidebarCollapsed ? (
                  <button
                    type="button"
                    className={`sidebar-group-btn ${groupContainsActive ? 'has-active' : ''}`}
                    onClick={() => dispatch(toggleNavGroup(group.id))}
                    aria-expanded={isExpanded}
                  >
                    <span>{t(group.labelKey)}</span>
                    {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  </button>
                ) : (
                  <div className="sidebar-rail-divider" title={t(group.labelKey)} />
                )}

                {itemsToRender.length > 0 && (
                  <div className="sidebar-group-items">
                    {itemsToRender.map((item) => {
                      const Icon = item.icon
                      const label = t(item.key)
                      const isActiveMatch = isItemActiveForPath(item, location.pathname)
                      return (
                        <NavLink
                          key={item.path}
                          to={item.path}
                          end={item.end}
                          onClick={closeMobile}
                          title={sidebarCollapsed ? label : undefined}
                          aria-label={label}
                          className={({ isActive }) =>
                            `sidebar-link ${isActive || isActiveMatch ? 'active' : ''}`
                          }
                        >
                          <Icon size={16} style={{ flexShrink: 0 }} />
                          {!sidebarCollapsed && <span>{label}</span>}
                        </NavLink>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          {!sidebarCollapsed && (
            <div style={{ marginBottom: '0.35rem' }}>
              <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
                {currentWorkspace?.business?.name ||
                  (user?.active_business_id ? `${t('common.workspace')} #${user.active_business_id}` : 'No Active Workspace')}
              </div>
              <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', marginTop: '2px' }}>
                {businessType} • Role: {currentWorkspace?.role || user?.role || 'staff'}
              </div>
            </div>
          )}

          {/* Mobile utility footer: Theme, Language, Sign Out */}
          <div className="sidebar-mobile-footer-actions">
            <button
              type="button"
              className="header-chip-btn"
              onClick={() => dispatch(toggleTheme())}
              aria-label="Toggle color theme"
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
              <span>{theme === 'dark' ? t('common.lightTheme', 'Light') : t('common.darkTheme', 'Dark')}</span>
            </button>
            <button
              type="button"
              className="header-chip-btn"
              onClick={toggleLanguage}
            >
              <Languages size={14} />
              <span>{language === 'hi' ? 'हिन्दी' : 'EN'}</span>
            </button>
            <button
              type="button"
              className="header-chip-btn"
              onClick={signOut}
              style={{ color: 'var(--status-danger-text)' }}
            >
              <LogOut size={14} />
              <span>{t('common.signOut', 'Sign Out')}</span>
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}
