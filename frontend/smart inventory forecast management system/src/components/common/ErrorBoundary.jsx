import React from 'react'
import { AlertCircle, RotateCcw } from 'lucide-react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '80vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '2rem',
          }}
        >
          <div
            style={{
              maxWidth: '520px',
              width: '100%',
              background: 'var(--erp-surface)',
              borderRadius: 'var(--radius-xl)',
              border: '1px solid var(--erp-border)',
              padding: '2.5rem',
              textAlign: 'center',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <div
              style={{
                width: '64px',
                height: '64px',
                borderRadius: '16px',
                background: 'var(--status-danger-bg)',
                color: 'var(--status-danger-text)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '1.25rem',
              }}
            >
              <AlertCircle size={32} />
            </div>
            <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 'var(--font-weight-semibold)', margin: '0 0 0.5rem', color: 'var(--erp-text-main)' }}>
              Something Went Wrong
            </h2>
            <p style={{ fontSize: 'var(--text-base)', color: 'var(--erp-text-muted)', lineHeight: 'var(--leading-normal)', margin: '0 0 1.5rem' }}>
              {this.state.error?.message || 'An unexpected error occurred while rendering this view.'}
            </p>
            <button
              onClick={this.handleReset}
              className="btn btn-primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
            >
              <RotateCcw size={16} />
              <span>Reload Application</span>
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
