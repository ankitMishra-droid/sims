import { useCallback } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import {
  logout,
  setWorkspaces,
  switchWorkspaceReset,
  updateUserProfile,
} from '../store/authSlice'
import { addToast, setLanguage, setMobileSidebarOpen } from '../store/uiSlice'

/**
 * Shared workspace, language, home-route, and logout actions reused across desktop header and mobile drawer.
 */
export function useSessionActions() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { user, refreshToken, currentWorkspace, isAuthenticated } = useSelector((state) => state.auth)
  const language = useSelector((state) => state.ui.language)

  const getHomePath = useCallback(() => {
    const hasWorkspace = Boolean(currentWorkspace?.business?.id)
    if (!hasWorkspace) return '/workspaces'
    if (!currentWorkspace?.business?.onboarding_completed) return '/onboarding'
    const btype = currentWorkspace?.business?.business_type || (user?.role === 'supplier' ? 'supplier' : 'retailer')
    return btype === 'supplier' ? '/supplier-portal' : '/dashboard'
  }, [currentWorkspace, user])

  const switchWorkspace = useCallback(
    async (val) => {
      if (val === '__manage__') {
        dispatch(setMobileSidebarOpen(false))
        navigate('/workspaces')
        return false
      }
      const targetId = Number(val)
      if (!targetId || targetId === currentWorkspace?.business?.id) return false
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
        dispatch(setMobileSidebarOpen(false))
        dispatch(addToast({ type: 'success', message: `Workspace: ${res.workspace.business.name}` }))
        navigate(
          !res.workspace.business.onboarding_completed
            ? '/onboarding'
            : res.workspace.business.business_type === 'supplier'
            ? '/supplier-portal'
            : '/dashboard'
        )
        return true
      } catch (err) {
        dispatch(addToast({ type: 'error', message: err.message || 'Workspace switch failed' }))
        return false
      }
    },
    [currentWorkspace?.business?.id, dispatch, navigate]
  )

  const toggleLanguage = useCallback(async () => {
    const next = language === 'en' ? 'hi' : 'en'
    dispatch(setLanguage(next))
    if (isAuthenticated) {
      try {
        const updated = await api.updateMe({ preferred_language: next })
        dispatch(updateUserProfile(updated))
      } catch {
        // non-blocking preference sync
      }
    }
  }, [language, isAuthenticated, dispatch])

  const signOut = useCallback(async () => {
    try {
      await api.logout({ refresh_token: refreshToken })
    } catch {
      // proceed clearing local state regardless
    }
    dispatch(setMobileSidebarOpen(false))
    dispatch(logout())
    navigate('/login', { replace: true })
  }, [refreshToken, dispatch, navigate])

  return {
    getHomePath,
    switchWorkspace,
    toggleLanguage,
    signOut,
  }
}
