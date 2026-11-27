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
import CsvExportButton from '../components/common/CsvExportButton'
import Modal from '../components/Modal'
import Badge from '../components/Badge'
import { ErrorState, ConfirmDialog } from '../components/common/StateBlocks'

export default function SuppliersPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
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
    setFormData({ name: '', contact_person: '', email: '', phone: '', address: '', lead_time_days: 7 })
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
      lead_time_days: s.lead_time_days ?? 7,
    })
    setFormError('')
    setModalMode('edit')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setFormError('')
    if (!formData.name.trim()) {
      setFormError('Supplier name is required.')
      return
    }
    const leadDays = parseInt(formData.lead_time_days, 10)
    if (isNaN(leadDays) || leadDays < 0 || leadDays > 365) {
      setFormError('Lead time days must be between 0 and 365.')
      return
    }

    setSubmitting(true)
    const payload = {
      name: formData.name.trim(),
      contact_person: formData.contact_person.trim() || null,
      email: formData.email.trim() || null,
      phone: formData.phone.trim() || null,
      address: formData.address.trim() || null,
      lead_time_days: leadDays,
    }
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
          placeholder="Search supplier by name, contact, email, or phone..."
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
              <div className="form-group">
                <label className="form-label" htmlFor="sup-name">
                  Supplier Name <span className="required">*</span>
                </label>
                <input
                  id="sup-name"
                  type="text"
                  required
                  className="form-control"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="sup-contact">Contact Person</label>
                <input
                  id="sup-contact"
                  type="text"
                  className="form-control"
                  value={formData.contact_person}
                  onChange={(e) => setFormData({ ...formData, contact_person: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="sup-email">Email</label>
                <input
                  id="sup-email"
                  type="email"
                  className="form-control"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="sup-phone">Phone</label>
                <input
                  id="sup-phone"
                  type="text"
                  className="form-control"
                  value={formData.phone}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="sup-lead">Lead Time (Days)</label>
                <input
                  id="sup-lead"
                  type="number"
                  min="0"
                  max="365"
                  className="form-control"
                  value={formData.lead_time_days}
                  onChange={(e) => setFormData({ ...formData, lead_time_days: e.target.value })}
                />
              </div>
              <div className="form-group col-span-2">
                <label className="form-label" htmlFor="sup-addr">Address</label>
                <input
                  id="sup-addr"
                  type="text"
                  className="form-control"
                  value={formData.address}
                  onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                />
              </div>
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
