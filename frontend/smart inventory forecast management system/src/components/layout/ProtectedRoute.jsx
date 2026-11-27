import { useSelector } from 'react-redux'
import { Navigate, useLocation } from 'react-router-dom'
import { LoadingState } from '../common/StateBlocks'

const NO_WORKSPACE_ALLOWED_PATHS = new Set([
  '/workspaces',
  '/settings/security',
  '/settings/language',
])

const ONBOARDING_ALLOWED_PATHS = new Set([
  '/onboarding',
  '/workspaces',
  '/settings/security',
  '/settings/language',
])

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, workspacesLoaded, currentWorkspace } = useSelector((state) => state.auth)
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (!workspacesLoaded) {
    return (
      <div style={{ padding: '2rem', maxWidth: '520px', margin: '3rem auto' }}>
        <LoadingState message="Loading workspace context..." />
      </div>
    )
  }

  const hasWorkspace = Boolean(currentWorkspace?.business?.id)
  const setupCompleted = Boolean(currentWorkspace?.business?.onboarding_completed)

  if (!hasWorkspace && !NO_WORKSPACE_ALLOWED_PATHS.has(location.pathname)) {
    return <Navigate to="/workspaces" replace />
  }

  if (hasWorkspace && !setupCompleted && !ONBOARDING_ALLOWED_PATHS.has(location.pathname)) {
    return <Navigate to="/onboarding" replace />
  }

  return children
}
