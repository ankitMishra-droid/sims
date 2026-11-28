import { useCallback, useEffect, useRef } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react'
import { createToastTimerController, removeToast } from '../store/uiSlice'

const TOAST_VARIANTS = {
  success: { icon: CheckCircle2, className: 'toast-success', color: '#10b981' },
  error: { icon: AlertCircle, className: 'toast-error', color: '#ef4444' },
  warning: { icon: AlertTriangle, className: 'toast-warning', color: '#f59e0b' },
  info: { icon: Info, className: 'toast-info', color: 'var(--erp-brand)' },
}

export default function ToastContainer() {
  const dispatch = useDispatch()
  const toasts = useSelector((state) => state.ui.toasts)
  const onExpireRef = useRef((id) => dispatch(removeToast(id)))
  const controllerRef = useRef(null)

  useEffect(() => {
    onExpireRef.current = (id) => dispatch(removeToast(id))
  }, [dispatch])

  const getController = useCallback(() => {
    if (!controllerRef.current) {
      controllerRef.current = createToastTimerController({
        onExpire: (id) => onExpireRef.current(id),
        setTimeoutFn: (fn, ms) => window.setTimeout(fn, ms),
        clearTimeoutFn: (timerId) => window.clearTimeout(timerId),
      })
    }
    return controllerRef.current
  }, [])

  useEffect(() => {
    getController().sync(toasts)
  }, [toasts, getController])

  useEffect(() => {
    return () => {
      controllerRef.current?.clearAll()
    }
  }, [])

  const handleDismiss = (id) => {
    controllerRef.current?.clear(id)
    dispatch(removeToast(id))
  }

  if (!toasts.length) return null

  return (
    <div className="toast-container" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((toast) => {
        const variant = TOAST_VARIANTS[toast.type] || TOAST_VARIANTS.info
        const Icon = variant.icon
        const role = toast.type === 'error' || toast.type === 'warning' ? 'alert' : 'status'

        return (
          <div
            key={toast.id}
            className={`toast ${variant.className}`}
            role={role}
            data-toast-type={toast.type}
            onMouseEnter={() => controllerRef.current?.pause(toast.id)}
            onMouseLeave={() => controllerRef.current?.resume(toast.id)}
          >
            <Icon size={20} color={variant.color} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              {toast.title && <div className="toast-title">{toast.title}</div>}
              {toast.message && <div className="toast-message">{toast.message}</div>}
            </div>
            <button
              type="button"
              className="toast-close-btn"
              onClick={() => handleDismiss(toast.id)}
              aria-label="Close notification"
            >
              <X size={15} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
