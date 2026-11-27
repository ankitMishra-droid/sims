import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './components/charts/ChartSetup' // Global Chart.js scales and controllers registration
import ErrorBoundary from './components/common/ErrorBoundary'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
