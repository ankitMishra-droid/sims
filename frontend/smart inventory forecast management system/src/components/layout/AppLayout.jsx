import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopHeader from './TopHeader'

export default function AppLayout({ children }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main-wrapper">
        <TopHeader />
        <main className="app-main-area">{children || <Outlet />}</main>
      </div>
    </div>
  )
}
