import { AlertCircle, FolderOpen, RefreshCw } from 'lucide-react'
import Modal from '../Modal'

export function LoadingState({ message = 'Loading data...' }) {
  return (
    <div className="section-card erp-loading-overlay">
      <div className="erp-spinner" />
      <span style={{ fontSize: '0.85rem', color: 'var(--erp-text-muted)' }}>{message}</span>
    </div>
  )
}

export function EmptyState({
  title = 'No records found',
  description = 'There are no items to display yet.',
  action = null,
  icon: Icon = FolderOpen,
}) {
  return (
    <div className="section-card empty-state">
      <div className="empty-state-icon">
        <Icon size={24} />
      </div>
      <div className="empty-state-title">{title}</div>
      <p className="empty-state-desc">{description}</p>
      {action && <div style={{ marginTop: '1rem' }}>{action}</div>}
    </div>
  )
}

export function ErrorState({ message = 'Something went wrong.', onRetry = null }) {
  return (
    <div
      className="section-card"
      style={{
        borderColor: 'var(--status-danger-border)',
        backgroundColor: 'var(--status-danger-bg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '1rem',
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', color: 'var(--status-danger-text)' }}>
        <AlertCircle size={18} />
        <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>{message}</span>
      </div>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          <RefreshCw size={13} />
          <span>Retry</span>
        </button>
      )}
    </div>
  )
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title = 'Confirm Action',
  message = 'Are you sure you want to proceed?',
  confirmLabel = 'Confirm',
  danger = false,
  loading = false,
}) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="sm">
      <div className="modal-body">
        <p style={{ fontSize: '0.875rem', color: 'var(--erp-text-main)', lineHeight: 1.5 }}>{message}</p>
      </div>
      <div className="modal-footer">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
          Cancel
        </button>
        <button
          type="button"
          className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
          onClick={onConfirm}
          disabled={loading}
        >
          {loading ? 'Processing...' : confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
