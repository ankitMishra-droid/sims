import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Plus, Edit2, Power, ClipboardList, Eye, RefreshCw, AlertTriangle } from 'lucide-react'
import {
  selectAllSuppliers,
  selectSuppliersLoading,
  selectSuppliersError,
  fetchSuppliers,
  createSupplier,
  updateSupplier,
  deactivateSupplier,
} from '../store/suppliersSlice'
import { api } from '../api'
import { addToast } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import FormField from '../components/common/FormField'
import CsvExportButton from '../components/common/CsvExportButton'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import { ErrorState, ConfirmDialog } from '../components/common/StateBlocks'
import { useTranslation } from '../hooks/useTranslation'
import { validateAndBuildSupplierPayload } from '../utils/formHelpers'

export default function SuppliersPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const suppliers = useSelector(selectAllSuppliers)
  const loading = useSelector(selectSuppliersLoading)
  const error = useSelector(selectSuppliersError)

  const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || '')
  const [modalMode, setModalMode] = useState(null) // 'add' | 'edit' | null
  const [selectedSupplier, setSelectedSupplier] = useState(null)
  const [detailSupplier, setDetailSupplier] = useState(null)
  const [linkBizId, setLinkBizId] = useState('')
  const [linkingWs, setLinkingWs] = useState(false)
  const [confirmDeactivate, setConfirmDeactivate] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const [formData, setFormData] = useState({
    name: '',
    contact_person: '',
    email: '',
    phone: '',
    address: '',
    lead_time_days: 7,
  })

  useEffect(() => {
    dispatch(fetchSuppliers())
  }, [dispatch])

  const openAdd = () => {
    setSelectedSupplier(null)
    setFormData({ name: '', contact_person: '', email: '', phone: '', address: '', lead_time_days: '7' })
    setFormError('')
    setModalMode('add')
  }

  const openEdit = (s) => {
    setSelectedSupplier(s)
    setFormData({
      name: s.name || '',
      contact_person: s.contact_person || '',
      email: s.email || '',
      phone: s.phone || '',
      address: s.address || '',
      lead_time_days: String(s.lead_time_days ?? 7),
    })
    setFormError('')
    setModalMode('edit')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setFormError('')
    const { error: validationError, payload } = validateAndBuildSupplierPayload(formData)
    if (validationError || !payload) {
      setFormError(validationError || 'Please review supplier details.')
      return
    }

    setSubmitting(true)
    const action =
      modalMode === 'edit' && selectedSupplier
        ? updateSupplier({ id: selectedSupplier.id, payload })
        : createSupplier(payload)
    const res = await dispatch(action)
    if (res.meta.requestStatus === 'rejected') {
      setFormError(res.payload || 'Operation failed.')
    } else {
      setModalMode(null)
    }
    setSubmitting(false)
  }

  const handleConfirmDeactivate = async () => {
    if (!confirmDeactivate) return
    setSubmitting(true)
    await dispatch(deactivateSupplier(confirmDeactivate))
    setConfirmDeactivate(null)
    setSubmitting(false)
  }

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Supplier Name', sortable: true, render: (s) => <strong>{s.name}</strong> },
      { key: 'contact_person', label: 'Contact', sortable: true, render: (s) => s.contact_person || '—' },
      { key: 'email', label: 'Email', sortable: true, render: (s) => s.email || '—' },
      { key: 'phone', label: 'Phone', render: (s) => s.phone || '—' },
      {
        key: 'lead_time_days',
        label: 'Lead Time',
        numeric: true,
        sortable: true,
        render: (s) => `${s.lead_time_days ?? 7} days`,
      },
      {
        key: 'is_active',
        label: 'Status',
        center: true,
        render: (s) => <Badge status={s.is_active ? 'ACTIVE' : 'INACTIVE'} label={s.is_active ? 'Active' : 'Inactive'} />,
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (s) => (
          <div className="actions-group">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => navigate(`/purchase-orders?supplier_id=${s.id}`)}
            >
              <ClipboardList size={13} />
              <span>New PO</span>
            </button>
            <button type="button" className="btn-action-icon" title="Details" onClick={() => setDetailSupplier(s)}>
              <Eye size={14} />
            </button>
            <button type="button" className="btn-action-icon" title="Edit" onClick={() => openEdit(s)}>
              <Edit2 size={14} />
            </button>
            <button
              type="button"
              className="btn-action-icon danger"
              title="Deactivate"
              onClick={() => setConfirmDeactivate(s)}
            >
              <Power size={14} />
            </button>
          </div>
        ),
      },
    ],
    [navigate]
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Suppliers"
        subtitle={`${suppliers.length} active suppliers`}
        actions={
          <>
            <CsvExportButton data={suppliers} filename="suppliers" />
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => dispatch(fetchSuppliers())} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={openAdd}>
              <Plus size={14} />
              <span>Add Supplier</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={() => dispatch(fetchSuppliers())} />}

      <div className="section-card">
        <input
          type="text"
          className="form-control"
          style={{ maxWidth: '380px' }}
          placeholder={t('placeholders.searchSuppliers', 'Search supplier by name, contact, email, or phone...')}
          aria-label="Search suppliers"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      <DataTable
        columns={columns}
        data={suppliers}
        keyField="id"
        defaultPageSize={10}
        searchQuery={searchQuery}
        searchFields={['name', 'contact_person', 'email', 'phone', 'address']}
        loading={loading}
        emptyTitle="No suppliers registered"
        emptyMessage="Add suppliers to create purchase orders and track lead times."
      />

      <Modal
        isOpen={Boolean(modalMode)}
        onClose={() => setModalMode(null)}
        title={modalMode === 'edit' ? `Edit Supplier: ${selectedSupplier?.name}` : 'Add Supplier'}
        size="lg"
      >
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} />
                <div>{formError}</div>
              </div>
            )}
            <div className="form-grid">
              <FormField label="Supplier Name" htmlFor="sup-name" required>
                <input
                  id="sup-name"
                  type="text"
                  required
                  className="form-control"
                  placeholder={t('placeholders.supplierName', 'e.g. ABC Wholesale Distributors')}
                  value={formData.name}
                  onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
                />
              </FormField>
              <FormField label="Contact Person" htmlFor="sup-contact">
                <input
                  id="sup-contact"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierContact', 'e.g. Rajesh Verma')}
                  value={formData.contact_person}
                  onChange={(e) => setFormData((prev) => ({ ...prev, contact_person: e.target.value }))}
                />
              </FormField>
              <FormField label="Email" htmlFor="sup-email">
                <input
                  id="sup-email"
                  type="email"
                  className="form-control"
                  placeholder={t('placeholders.supplierEmail', 'e.g. orders@example.com')}
                  value={formData.email}
                  onChange={(e) => setFormData((prev) => ({ ...prev, email: e.target.value }))}
                />
              </FormField>
              <FormField label="Phone" htmlFor="sup-phone">
                <input
                  id="sup-phone"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierPhone', 'e.g. +91 98765 43210')}
                  value={formData.phone}
                  onChange={(e) => setFormData((prev) => ({ ...prev, phone: e.target.value }))}
                />
              </FormField>
              <FormField
                label="Lead Time (Days)"
                htmlFor="sup-lead"
                hint="Typical days from PO dispatch to warehouse receipt (0–365)."
              >
                <input
                  id="sup-lead"
                  type="number"
                  min="0"
                  max="365"
                  step="1"
                  className="form-control"
                  placeholder={t('placeholders.supplierLeadDays', 'e.g. 7')}
                  value={formData.lead_time_days}
                  onChange={(e) => setFormData((prev) => ({ ...prev, lead_time_days: e.target.value }))}
                />
              </FormField>
              <FormField label="Address" htmlFor="sup-addr" className="col-span-2">
                <input
                  id="sup-addr"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierAddress', 'e.g. Plot 14, Market Yard, Jaipur')}
                  value={formData.address}
                  onChange={(e) => setFormData((prev) => ({ ...prev, address: e.target.value }))}
                />
              </FormField>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={() => setModalMode(null)}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Saving...' : modalMode === 'edit' ? 'Update Supplier' : 'Save Supplier'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={Boolean(detailSupplier)}
        onClose={() => setDetailSupplier(null)}
        title={detailSupplier?.name || 'Supplier Details'}
      >
        {detailSupplier && (
          <div className="modal-body">
            <div className="form-grid">
              <div><strong>Contact:</strong> {detailSupplier.contact_person || '—'}</div>
              <div><strong>Email:</strong> {detailSupplier.email || '—'}</div>
              <div><strong>Phone:</strong> {detailSupplier.phone || '—'}</div>
              <div><strong>Lead Time:</strong> {detailSupplier.lead_time_days} days</div>
              <div><strong>Linked Workspace:</strong> {detailSupplier.linked_business_id ? `#${detailSupplier.linked_business_id}` : 'Not linked'}</div>
              <div className="col-span-2"><strong>Address:</strong> {detailSupplier.address || '—'}</div>
            </div>
            <div style={{ marginTop: '1rem', paddingTop: '0.85rem', borderTop: '1px solid var(--erp-border)' }}>
              <label className="form-label" htmlFor="sup-link-ws">Link Supplier Business Workspace ID</label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  id="sup-link-ws"
                  type="number"
                  min={1}
                  className="form-control"
                  placeholder={detailSupplier.linked_business_id ? String(detailSupplier.linked_business_id) : 'Supplier workspace ID'}
                  value={linkBizId}
                  onChange={(e) => setLinkBizId(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={linkingWs}
                  onClick={async () => {
                    setLinkingWs(true)
                    try {
                      const val = linkBizId.trim() ? Number(linkBizId) : null
                      const res = await api.linkSupplierWorkspace(detailSupplier.id, val)
                      setDetailSupplier(res.data)
                      setLinkBizId('')
                      dispatch(fetchSuppliers())
                      dispatch(addToast({ type: 'success', message: 'Supplier workspace link saved.' }))
                    } catch (err) {
                      dispatch(addToast({ type: 'error', message: err.message || 'Link failed.' }))
                    } finally {
                      setLinkingWs(false)
                    }
                  }}
                >
                  {linkingWs ? 'Saving...' : 'Save Link'}
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(confirmDeactivate)}
        onClose={() => setConfirmDeactivate(null)}
        onConfirm={handleConfirmDeactivate}
        title="Deactivate Supplier"
        message={`Deactivate "${confirmDeactivate?.name}"? Existing purchase orders remain preserved.`}
        confirmLabel="Deactivate"
        danger
        loading={submitting}
      />
    </div>
  )
}
