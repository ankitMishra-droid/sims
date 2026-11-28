import { useState } from 'react'
import { Upload, CheckCircle2, AlertCircle } from 'lucide-react'
import { useDispatch } from 'react-redux'
import { api } from '../../api'
import { addToast } from '../../store/uiSlice'
import Modal from '../Modal'

export default function ProductCsvImportButton({ onImported }) {
  const dispatch = useDispatch()
  const [isOpen, setIsOpen] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')

  const handleClose = () => {
    setIsOpen(false)
    setSelectedFile(null)
    setResult(null)
    setErrorMsg('')
  }

  const handleUpload = async (e) => {
    e.preventDefault()
    if (!selectedFile) {
      setErrorMsg('Please select a CSV file first.')
      return
    }
    setUploading(true)
    setErrorMsg('')
    try {
      const res = await api.importProductsCsv(selectedFile)
      setResult(res)
      dispatch(
        addToast({
          type: res.created_count > 0 ? 'success' : 'info',
          message: res.message || `Imported ${res.created_count || 0} products.`,
        })
      )
      if (onImported && res.created_count > 0) {
        onImported()
      }
    } catch (err) {
      setErrorMsg(err.message || 'CSV import failed.')
    } finally {
      setUploading(false)
    }
  }

  const handleDownloadSample = () => {
    const sample =
      'sku,name,category,unit,cost_price,selling_price,current_stock,reorder_level\n' +
      'SAMPLE-01,"Sample Basmati 5kg",Grains,bag,320,395,25,8\n'
    const blob = new Blob([sample], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'products_import_template.csv'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => setIsOpen(true)}
        aria-label="Import Products from CSV"
      >
        <Upload size={14} />
        <span>Import CSV</span>
      </button>

      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        title="Import Products via CSV"
        subtitle="Upload a UTF-8 CSV catalog file (required headers: sku, name)."
      >
        <form onSubmit={handleUpload} className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--erp-text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span>Optional columns: category, unit, cost_price, selling_price, current_stock, reorder_level, supplier_name</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={handleDownloadSample}>
              Download Template
            </button>
          </div>

          <div className="form-group">
            <label htmlFor="product-csv-file" className="form-label">
              CSV File <span className="required">*</span>
            </label>
            <input
              id="product-csv-file"
              type="file"
              accept=".csv,text/csv"
              className="form-control"
              onChange={(e) => {
                setSelectedFile(e.target.files?.[0] || null)
                setErrorMsg('')
              }}
            />
          </div>

          {errorMsg && (
            <div className="form-error-banner">
              <AlertCircle size={16} />
              <span>{errorMsg}</span>
            </div>
          )}

          {result && (
            <div
              style={{
                padding: '0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--erp-border)',
                backgroundColor: 'var(--erp-surface-subtle)',
                fontSize: '0.82rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600 }}>
                <CheckCircle2 size={15} color="#059669" />
                <span>{result.message}</span>
              </div>
              {Array.isArray(result.errors) && result.errors.length > 0 && (
                <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.15rem', maxHeight: '140px', overflowY: 'auto' }}>
                  {result.errors.slice(0, 20).map((err, i) => (
                    <li key={i}>
                      Row {err.row} ({err.sku || 'no SKU'}): {err.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
            <button type="button" className="btn btn-secondary" onClick={handleClose}>
              Close
            </button>
            <button type="submit" className="btn btn-primary" disabled={uploading}>
              {uploading ? 'Importing...' : 'Upload & Import'}
            </button>
          </div>
        </form>
      </Modal>
    </>
  )
}
