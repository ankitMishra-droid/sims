import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
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
  X,
} from 'lucide-react'
import { setMobileSidebarOpen } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
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

export default function Sidebar() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const mobileOpen = useSelector((state) => state.ui.mobileSidebarOpen)
  const { user, currentWorkspace } = useSelector((state) => state.auth)
  const [collapsed, setCollapsed] = useState({})

  const closeMobile = () => dispatch(setMobileSidebarOpen(false))

  const toggleGroup = (id) => {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const businessType = currentWorkspace?.business?.business_type || (user?.role === 'supplier' ? 'supplier' : 'retailer')
  const perms = currentWorkspace?.permissions || []
  const hasWorkspace = !!currentWorkspace?.business?.id
  const setupCompleted = !!currentWorkspace?.business?.onboarding_completed

  const visibleGroups = NAV_GROUPS.map((group) => {
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
  }).filter(Boolean)

  return (
    <>
      <div
        className={`sidebar-backdrop ${mobileOpen ? 'open' : ''}`}
        onClick={closeMobile}
        aria-hidden="true"
      />
      <aside className={`app-sidebar ${mobileOpen ? 'open' : ''}`} aria-label="Primary Navigation">
        <div
          className="sidebar-brand"
          onClick={() => {
            const target = !hasWorkspace
              ? '/workspaces'
              : !setupCompleted
              ? '/onboarding'
              : businessType === 'supplier'
              ? '/supplier-portal'
              : '/dashboard'
            navigate(target)
            closeMobile()
          }}
        >
          <div className="sidebar-brand-left">
            <img src={faviconImg} alt="StockSangati" className="sidebar-logo" />
            <div style={{ minWidth: 0 }}>
              <div className="sidebar-brand-name">{t('brandName', 'StockSangati')}</div>
              <div className="sidebar-brand-tag">{t('brandTagline')}</div>
            </div>
          </div>
          <button
            type="button"
            className="sidebar-close-btn"
            onClick={(e) => {
              e.stopPropagation()
              closeMobile()
            }}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {visibleGroups.map((group) => {
            const isCollapsed = !!collapsed[group.id]
            return (
              <div key={group.id}>
                <button
                  type="button"
                  className="sidebar-group-btn"
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={!isCollapsed}
                >
                  <span>{t(group.labelKey)}</span>
                  {isCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                </button>
                {!isCollapsed && (
                  <div className="sidebar-group-items">
                    {group.items.map((item) => {
                      const Icon = item.icon
                      return (
                        <NavLink
                          key={item.path}
                          to={item.path}
                          end={item.end}
                          onClick={closeMobile}
                          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
                        >
                          <Icon size={16} />
                          <span>{t(item.key)}</span>
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
          <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>
            {currentWorkspace?.business?.name || (user?.active_business_id ? `${t('common.workspace')} #${user.active_business_id}` : 'No Active Workspace')}
          </div>
          <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', marginTop: '2px' }}>
            {businessType} • Role: {currentWorkspace?.role || user?.role || 'staff'}
          </div>
        </div>
      </aside>
    </>
  )
}
