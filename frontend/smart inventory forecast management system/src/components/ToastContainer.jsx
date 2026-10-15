import React from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { removeToast } from '../store/uiSlice'

export default function ToastContainer() {
  const dispatch = useDispatch()
  const toasts = useSelector((state) => state.ui.toasts)

  if (!toasts.length) return null

  return (
    <div className="toast-container" role="region" aria-live="polite">
      {toasts.map((toast) => {
        let Icon = Info
        let toastClass = 'toast-info'
        let iconColor = '#714b67'

        if (toast.type === 'success') {
          Icon = CheckCircle2
          toastClass = 'toast-success'
          iconColor = '#10b981'
        } else if (toast.type === 'error') {
          Icon = AlertCircle
          toastClass = 'toast-error'
          iconColor = '#ef4444'
        }

        return (
          <div key={toast.id} className={`toast ${toastClass}`}>
            <Icon size={20} color={iconColor} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              {toast.title && <div className="toast-title">{toast.title}</div>}
              <div className="toast-message">{toast.message}</div>
            </div>
            <button
              onClick={() => dispatch(removeToast(toast.id))}
              style={{ color: '#94a3b8', cursor: 'pointer', padding: '2px' }}
              aria-label="Close"
            >
              <X size={15} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
