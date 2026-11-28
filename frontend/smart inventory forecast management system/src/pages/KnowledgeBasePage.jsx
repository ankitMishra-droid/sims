import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  UploadCloud,
  RefreshCw,
  Trash2,
  Eye,
  RotateCcw,
  XCircle,
  Search,
  AlertTriangle,
  FileText,
  CheckCircle2,
  Clock,
  Cpu,
  Coins,
} from 'lucide-react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import { addToast } from '../store/uiSlice'
import { setAiHealth, setCreditAccount, setDocuments, setDocumentsLoading } from '../store/aiSlice'
import PageHeader from '../components/common/PageHeader'
import Modal from '../components/Modal'
import { LoadingState, EmptyState } from '../components/common/StateBlocks'

const IN_PROGRESS_STATUSES = new Set([
  'UPLOADED',
  'PENDING',
  'VALIDATING',
  'EXTRACTING',
  'NORMALIZING',
  'CHUNKING',
  'EMBEDDING',
  'INDEXING',
])

const STATUS_BADGE_MAP = {
  COMPLETED: 'badge-success',
  PARTIALLY_COMPLETED: 'badge-warning',
  QUOTA_PAUSED: 'badge-warning',
  PAUSED_QUOTA: 'badge-warning',
  PAUSED_RETRYABLE: 'badge-warning',
  FAILED: 'badge-danger',
  CANCELLED: 'badge-neutral',
}

export default function KnowledgeBasePage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()

  const { currentWorkspace } = useSelector((state) => state.auth)
  const { documents, documentsLoading, aiHealth, creditAccount } = useSelector((state) => state.ai)

  const permissions = currentWorkspace?.permissions || []
  const role = String(currentWorkspace?.role || '').toLowerCase()
  const canWriteDocs =
    permissions.includes('ai.documents.write') ||
    (permissions.length === 0 && ['owner', 'admin', 'manager', 'analyst', 'supplier'].includes(role))

  const [selectedFile, setSelectedFile] = useState(null)
  const [docTitle, setDocTitle] = useState('')
  const [docCategory, setDocCategory] = useState('general')
  const [uploading, setUploading] = useState(false)

  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [langFilter, setLangFilter] = useState('')
  const [searchTerm, setSearchTerm] = useState('')

  const [detailModalDoc, setDetailModalDoc] = useState(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [busyDocId, setBusyDocId] = useState(null)

  const loadDocuments = useCallback(async () => {
    dispatch(setDocumentsLoading(true))
    try {
      const list = await api.getAiDocuments({
        status: statusFilter,
        fileType: typeFilter,
        language: langFilter,
        search: searchTerm,
      })
      dispatch(setDocuments(list))
    } catch (err) {
      dispatch(addToast({ title: 'Error', message: err.message, type: 'error' }))
    } finally {
      dispatch(setDocumentsLoading(false))
    }
  }, [dispatch, statusFilter, typeFilter, langFilter, searchTerm])

  const loadHealth = useCallback(async () => {
    try {
      const [healthRes, balRes] = await Promise.allSettled([
        api.getAiHealth(),
        api.getAiCreditBalance(),
      ])
      if (healthRes.status === 'fulfilled') dispatch(setAiHealth(healthRes.value))
      if (balRes.status === 'fulfilled') dispatch(setCreditAccount(balRes.value))
    } catch {
      // keep silent if status check not available
    }
  }, [dispatch])

  useEffect(() => {
    loadDocuments()
    loadHealth()
  }, [loadDocuments, loadHealth])

  const openDocumentDetails = useCallback(
    async (docId) => {
      try {
        const detail = await api.getAiDocumentDetail(docId)
        setDetailModalDoc(detail)
      } catch (err) {
        dispatch(addToast({ title: 'Error', message: err.message, type: 'error' }))
      }
    },
    [dispatch]
  )

  useEffect(() => {
    const docParam = searchParams.get('doc')
    if (!docParam) return undefined
    const parsed = Number(docParam)
    if (!Number.isFinite(parsed) || parsed <= 0) return undefined
    let active = true
    api
      .getAiDocumentDetail(parsed)
      .then((detail) => {
        if (active) setDetailModalDoc(detail)
      })
      .catch((err) => {
        if (active) {
          dispatch(addToast({ title: 'Error', message: err.message, type: 'error' }))
        }
      })
    return () => {
      active = false
    }
  }, [searchParams, dispatch])

  // Poll cleanly only while active ingestion jobs are running
  useEffect(() => {
    const hasActive = documents.some((d) => IN_PROGRESS_STATUSES.has(d.status))
    if (!hasActive) return undefined
    const timer = setInterval(() => {
      loadDocuments()
    }, 3000)
    return () => clearInterval(timer)
  }, [documents, loadDocuments])

  const handleUpload = async (e) => {
    e.preventDefault()
    if (!selectedFile || uploading) return
    setUploading(true)
    try {
      const res = await api.uploadAiDocument(selectedFile, {
        title: docTitle.trim(),
        docCategory,
        asyncProcess: true,
      })
      dispatch(
        addToast({
          title: res.duplicate_detected ? 'Duplicate Detected' : 'Document Uploaded',
          message: res.message,
          type: res.duplicate_detected ? 'info' : 'success',
        })
      )
      setSelectedFile(null)
      setDocTitle('')
      await Promise.all([loadDocuments(), loadHealth()])
    } catch (err) {
      dispatch(addToast({ title: 'Upload Failed', message: err.message, type: 'error' }))
    } finally {
      setUploading(false)
    }
  }

  const handleDocAction = async (docId, action) => {
    setBusyDocId(docId)
    try {
      if (action === 'retry') await api.retryAiDocument(docId)
      else if (action === 'reindex') await api.reindexAiDocument(docId)
      else if (action === 'cancel') await api.cancelAiDocument(docId)
      else if (action === 'delete') {
        await api.deleteAiDocument(docId)
        setConfirmDeleteId(null)
      }
      await Promise.all([loadDocuments(), loadHealth()])
    } catch (err) {
      dispatch(addToast({ title: 'Document Action Failed', message: err.message, type: 'error' }))
    } finally {
      setBusyDocId(null)
    }
  }

  return (
    <div className="page-container">
      <PageHeader
        title={t('ai.knowledgeTitle')}
        subtitle={t('ai.knowledgeSubtitle')}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            {creditAccount && (
              <button
                type="button"
                className={`ai-credit-chip ${
                  creditAccount.available_credits <= 0 ? 'empty' : creditAccount.available_credits <= 10 ? 'low' : ''
                }`}
                onClick={() => navigate('/ai-usage')}
              >
                <Coins size={13} />
                <span>{Number(creditAccount.available_credits || 0).toFixed(2)} cr</span>
              </button>
            )}
            {aiHealth && (
              <span className="badge badge-neutral" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                <Cpu size={13} />
                {t('ai.aiStatusBadge')}: <strong>{aiHealth.overall_status}</strong>
              </span>
            )}
            <button type="button" className="btn btn-secondary" onClick={loadDocuments}>
              <RefreshCw size={15} /> {t('common.refresh')}
            </button>
          </div>
        }
      />

      {canWriteDocs && (
        <section className="card" style={{ marginBottom: '1.25rem' }}>
          <div className="card-header">
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <UploadCloud size={18} />
              {t('ai.uploadTitle')}
            </h3>
          </div>
          <form onSubmit={handleUpload} className="ai-upload-grid">
            <div>
              <label className="form-label">{t('ai.chooseFile')}</label>
              <input
                type="file"
                className="form-control"
                accept=".pdf,.docx,.txt,.csv,.xlsx"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              />
            </div>
            <div>
              <label className="form-label">{t('ai.docTitleOptional')}</label>
              <input
                type="text"
                className="form-control"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                placeholder={t('ai.docTitleOptional')}
              />
            </div>
            <div>
              <label className="form-label">{t('ai.docCategory')}</label>
              <select
                className="form-control"
                value={docCategory}
                onChange={(e) => setDocCategory(e.target.value)}
              >
                <option value="general">{t('ai.catGeneral')}</option>
                <option value="faq">{t('ai.catFaq')}</option>
                <option value="table">{t('ai.catTable')}</option>
                <option value="catalog">{t('ai.catCatalog')}</option>
                <option value="manual">{t('ai.catManual')}</option>
                <option value="policy">{t('ai.catPolicy')}</option>
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!selectedFile || uploading}
                style={{ width: '100%' }}
              >
                {uploading ? t('ai.uploading') : t('ai.uploadButton')}
              </button>
            </div>
          </form>
        </section>
      )}

      <section className="card">
        <div className="ai-filter-bar">
          <div style={{ position: 'relative', flex: '1 1 220px' }}>
            <Search
              size={15}
              style={{
                position: 'absolute',
                left: '0.7rem',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--erp-text-subtle)',
              }}
            />
            <input
              type="text"
              className="form-control"
              style={{ paddingLeft: '2.1rem' }}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={t('ai.searchDocsPlaceholder')}
            />
          </div>
          <select
            className="form-control"
            style={{ width: '165px' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">{t('ai.filterStatus')}</option>
            <option value="COMPLETED">COMPLETED</option>
            <option value="QUOTA_PAUSED">QUOTA_PAUSED</option>
            <option value="PARTIALLY_COMPLETED">PARTIALLY_COMPLETED</option>
            <option value="FAILED">FAILED</option>
            <option value="PENDING">PENDING</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <select
            className="form-control"
            style={{ width: '140px' }}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="">{t('ai.filterType')}</option>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
            <option value="txt">TXT</option>
            <option value="csv">CSV</option>
            <option value="xlsx">XLSX</option>
          </select>
          <select
            className="form-control"
            style={{ width: '140px' }}
            value={langFilter}
            onChange={(e) => setLangFilter(e.target.value)}
          >
            <option value="">{t('ai.filterLang')}</option>
            <option value="en">English (en)</option>
            <option value="hi">Hindi (hi)</option>
            <option value="mixed">Mixed</option>
          </select>
        </div>

        {documentsLoading && documents.length === 0 ? (
          <LoadingState message={t('common.loading')} />
        ) : documents.length === 0 ? (
          <EmptyState icon={FileText} title={t('ai.noDocs')} />
        ) : (
          <div className="table-responsive">
            <table className="erp-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Format / Lang</th>
                  <th>Status & Stage</th>
                  <th>{t('ai.chunksCount')}</th>
                  <th>{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const pct =
                    doc.status === 'COMPLETED'
                      ? 100
                      : doc.total_chunks > 0
                      ? Math.round((doc.indexed_chunks / doc.total_chunks) * 100)
                      : 0
                  const badgeCls = STATUS_BADGE_MAP[doc.status] || 'badge-info'
                  const canRetry = ['FAILED', 'QUOTA_PAUSED', 'PAUSED_QUOTA', 'PAUSED_RETRYABLE', 'PARTIALLY_COMPLETED', 'CANCELLED'].includes(doc.status) && !doc.ocr_required
                  const canCancel = IN_PROGRESS_STATUSES.has(doc.status)

                  return (
                    <tr key={doc.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{doc.title}</div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                          {doc.filename} • {doc.version_label} • {(doc.file_size_bytes / 1024).toFixed(1)} KB
                          {doc.credits_consumed > 0 ? ` • ${Number(doc.credits_consumed).toFixed(3)} cr` : ''}
                        </div>
                        {doc.ocr_required && (
                          <div className="ai-doc-warning">
                            <AlertTriangle size={12} /> {t('ai.ocrWarning')}
                          </div>
                        )}
                        {doc.error_message && !doc.ocr_required && (
                          <div className="ai-doc-warning">
                            <AlertTriangle size={12} /> {doc.error_message}
                            {doc.next_retry_at ? ` (Next retry: ${new Date(doc.next_retry_at).toLocaleTimeString()})` : ''}
                          </div>
                        )}
                      </td>
                      <td>
                        <span className="badge badge-neutral" style={{ textTransform: 'uppercase' }}>
                          {doc.file_type}
                        </span>{' '}
                        <span className="badge badge-info">{doc.detected_language}</span>
                      </td>
                      <td>
                        <span className={`badge ${badgeCls}`}>
                          {doc.status === 'COMPLETED' ? <CheckCircle2 size={12} /> : <Clock size={12} />}{' '}
                          {doc.status}
                        </span>
                        <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)', marginTop: '0.2rem' }}>
                          {doc.last_checkpoint_stage || doc.current_stage}
                        </div>
                      </td>
                      <td style={{ minWidth: '140px' }}>
                        <div style={{ fontSize: '0.8rem', marginBottom: '0.25rem' }}>
                          {doc.indexed_chunks} / {doc.total_chunks || 0} ({pct}%)
                        </div>
                        <div className="ai-progress-track">
                          <div className="ai-progress-fill" style={{ width: `${pct}%` }} />
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn-xs btn-secondary"
                            onClick={() => openDocumentDetails(doc.id)}
                          >
                            <Eye size={12} /> {t('ai.viewDetails')}
                          </button>

                          {canWriteDocs && canRetry && (
                            <button
                              type="button"
                              className="btn-xs btn-primary"
                              disabled={busyDocId === doc.id}
                              onClick={() => handleDocAction(doc.id, 'retry')}
                            >
                              <RotateCcw size={12} /> {t('ai.retryIngest')}
                            </button>
                          )}

                          {canWriteDocs && doc.status === 'COMPLETED' && (
                            <button
                              type="button"
                              className="btn-xs btn-secondary"
                              disabled={busyDocId === doc.id}
                              onClick={() => handleDocAction(doc.id, 'reindex')}
                            >
                              <RefreshCw size={12} /> {t('ai.reindexDoc')}
                            </button>
                          )}

                          {canWriteDocs && canCancel && (
                            <button
                              type="button"
                              className="btn-xs btn-secondary"
                              disabled={busyDocId === doc.id}
                              onClick={() => handleDocAction(doc.id, 'cancel')}
                            >
                              <XCircle size={12} /> {t('ai.cancelIngest')}
                            </button>
                          )}

                          {canWriteDocs &&
                            (confirmDeleteId === doc.id ? (
                              <>
                                <button
                                  type="button"
                                  className="btn-xs btn-danger"
                                  disabled={busyDocId === doc.id}
                                  onClick={() => handleDocAction(doc.id, 'delete')}
                                >
                                  {t('common.confirm')}
                                </button>
                                <button
                                  type="button"
                                  className="btn-xs btn-secondary"
                                  onClick={() => setConfirmDeleteId(null)}
                                >
                                  {t('common.cancel')}
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="btn-xs btn-secondary"
                                disabled={busyDocId === doc.id}
                                onClick={() => setConfirmDeleteId(doc.id)}
                              >
                                <Trash2 size={12} /> {t('ai.deleteDoc')}
                              </button>
                            ))}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detailModalDoc && (
        <Modal
          isOpen={!!detailModalDoc}
          onClose={() => setDetailModalDoc(null)}
          title={detailModalDoc.document.title}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '65vh', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
              {detailModalDoc.document.filename} • {detailModalDoc.document.version_label} •{' '}
              {detailModalDoc.document.detected_language} • {detailModalDoc.document.embedding_model} (
              {detailModalDoc.document.embedding_dimensions}d)
            </div>
            {(detailModalDoc.chunks || []).map((chunk) => (
              <div
                key={chunk.id}
                style={{
                  padding: '0.65rem',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--erp-border)',
                  background: 'var(--erp-surface-subtle)',
                }}
              >
                <div style={{ fontSize: '0.75rem', fontWeight: 600, marginBottom: '0.3rem', display: 'flex', justifyContent: 'space-between' }}>
                  <span>
                    #{chunk.chunk_index + 1}
                    {chunk.page_number ? ` • p.${chunk.page_number}` : ''}
                    {chunk.section_heading ? ` • ${chunk.section_heading}` : ''}
                  </span>
                  <span className="badge badge-neutral">{chunk.embedding_status}</span>
                </div>
                <div style={{ fontSize: '0.84rem', whiteSpace: 'pre-wrap' }}>{chunk.text}</div>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  )
}
