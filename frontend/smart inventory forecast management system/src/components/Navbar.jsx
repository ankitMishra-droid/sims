import React, { useState, useRef, useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  AppWindow,
  Package,
  ShoppingCart,
  Boxes,
  Truck,
  ClipboardList,
  Inbox,
  LayoutDashboard,
  Menu,
  X,
  Search,
  Sun,
  Moon,
} from 'lucide-react'
import { setCommandPaletteOpen, toggleTheme } from '../store/uiSlice'
import faviconImg from '../assets/images/favicon.png'

const navItems = [
  { name: 'Apps', path: '/', icon: AppWindow, exact: true },
  { name: 'Products', path: '/products', icon: Package },
  { name: 'Sales', path: '/sales', icon: ShoppingCart },
  { name: 'Inventory', path: '/inventory', icon: Boxes },
  { name: 'Suppliers', path: '/suppliers', icon: Truck },
  { name: 'Purchase Orders', path: '/purchase-orders', icon: ClipboardList },
  { name: 'Receive Order', path: '/receive-order', icon: Inbox },
  { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
]

export default function Navbar() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const theme = useSelector((state) => state.ui.theme)
  const [menuOpen, setMenuOpen] = useState(false)
  const toggleRef = useRef(null)

  // Close menu when clicking outside on desktop
  useEffect(() => {
    function handleClickOutside(event) {
      if (toggleRef.current && !toggleRef.current.contains(event.target)) {
        setMenuOpen(false)
      }
    }
    if (menuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [menuOpen])

  return (
    <nav className="erp-navbar">
      <div className="navbar-container">
        {/* Brand Area */}
        <div
          className="brand-section"
          onClick={() => navigate('/')}
          style={{ cursor: 'pointer' }}
          title="StockSangati - Operations Portal"
        >
          <img
            src={faviconImg}
            alt="StockSangati Logo"
            className="brand-favicon-logo"
          />
          <div className="brand-text-container">
            <div className="brand-main-title">
              <span className="brand-title-stock">Stock</span>
              <span className="brand-title-sangati">Sangati</span>
            </div>
            <div className="brand-slogan">
              <span className="slogan-text">Your stock. Your trade.</span>{' '}
              <span className="slogan-accent">Connected.</span>
            </div>
          </div>
        </div>

        {/* Desktop Nav Items */}
        <div className="nav-tabs">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.exact}
                className={({ isActive }) =>
                  `nav-tab-item ${isActive ? 'active' : ''}`
                }
              >
                <Icon size={16} />
                <span>{item.name}</span>
              </NavLink>
            )
          })}
        </div>

        {/* Right Toggle Button (Houses Search, Theme & Mobile Nav) */}
        <div className="nav-right" ref={toggleRef}>
          <button
            type="button"
            className="nav-menu-toggle"
            onClick={() => setMenuOpen((prev) => !prev)}
            aria-label="Toggle navigation and tools menu"
            title="Search, Theme & Navigation"
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>

          {/* Toggle Menu Panel */}
          {menuOpen && (
            <div className="nav-toggle-panel">
              {/* Quick Search & Theme Mode Section */}
              <div className="toggle-tools-section">
                <button
                  type="button"
                  className="toggle-search-btn"
                  onClick={() => {
                    setMenuOpen(false)
                    dispatch(setCommandPaletteOpen(true))
                  }}
                  title="Search products, orders, suppliers (Ctrl+K)"
                >
                  <div className="toggle-tool-left">
                    <Search size={15} />
                    <span>Quick Search...</span>
                  </div>
                  <kbd className="toggle-kbd">⌘K</kbd>
                </button>

                <button
                  type="button"
                  className="toggle-theme-btn"
                  onClick={() => dispatch(toggleTheme())}
                  title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
                >
                  <div className="toggle-tool-left">
                    {theme === 'dark' ? (
                      <Sun size={15} className="theme-icon sun-icon" />
                    ) : (
                      <Moon size={15} className="theme-icon moon-icon" />
                    )}
                    <span>Theme</span>
                  </div>
                  <span className="toggle-theme-badge">
                    {theme === 'dark' ? '🌙 Dark' : '☀️ Light'}
                  </span>
                </button>
              </div>

              {/* Navigation links (collapses from top bar on screens <= 1180px) */}
              <div className="toggle-nav-section">
                <div className="toggle-nav-header">Navigation</div>
                {navItems.map((item) => {
                  const Icon = item.icon
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.exact}
                      onClick={() => setMenuOpen(false)}
                      className={({ isActive }) =>
                        `toggle-nav-item ${isActive ? 'active' : ''}`
                      }
                    >
                      <Icon size={17} />
                      <span>{item.name}</span>
                    </NavLink>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
