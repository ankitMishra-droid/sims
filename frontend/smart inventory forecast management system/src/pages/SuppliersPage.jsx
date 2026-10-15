import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import {
  Truck,
  Plus,
  Mail,
  Phone,
  MapPin,
  Clock,
  Edit2,
  Power,
  ClipboardList,
  AlertTriangle,
  User,
} from 'lucide-react'
import {
  selectAllSuppliers,
  selectSuppliersLoading,
  fetchSuppliers,
  createSupplier,
  updateSupplier,
  deactivateSupplier,
} from '../store/suppliersSlice'
import ErpControlPanel from '../components/common/ErpControlPanel'
import DataTable from '../components/common/DataTable'
import Modal from '../components/Modal'
import Badge from '../components/Badge'

export default function SuppliersPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const suppliers = useSelector(selectAllSuppliers)
  const loading = useSelector(selectSuppliersLoading)

  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState('table') // 'table' | 'cards'

  // Modals state
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [selectedSupplier, setSelectedSupplier] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  // Form State
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

  // Open Add Modal
  const openAddModal = useCallback(() => {
    setFormData({
      name: '',
      contact_person: '',
      email: '',
      phone: '',
      address: '',
      lead_time_days: 7,
    })
    setFormError('')
    setIsAddOpen(true)
  }, [])

  // Open Edit Modal
  const openEdit = useCallback((supplier) => {
    setSelectedSupplier(supplier)
    setFormData({
      name: supplier.name || '',
      contact_person: supplier.contact_person || '',
      email: supplier.email || '',
      phone: supplier.phone || '',
      address: supplier.address || '',
      lead_time_days: supplier.lead_time_days || 7,
    })
    setFormError('')
    setIsEditOpen(true)
  }, [])

  // Submit Add
  const handleAddSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setFormError('')

    const payload = {
      name: formData.name.trim(),
      contact_person: formData.contact_person.trim() || null,
      email: formData.email.trim() || null,
      phone: formData.phone.trim() || null,
      address: formData.address.trim() || null,
      lead_time_days: parseInt(formData.lead_time_days, 10) || 7,
    }

    const res = await dispatch(createSupplier(payload))
    if (createSupplier.rejected.match(res)) {
      setFormError(res.payload || 'Failed to create supplier.')
    } else {
      setIsAddOpen(false)
    }
    setSubmitting(false)
  }

  // Submit Edit
  const handleEditSubmit = async (e) => {
    e.preventDefault()
    if (!selectedSupplier) return
    setSubmitting(true)
    setFormError('')

    const payload = {
      name: formData.name.trim(),
      contact_person: formData.contact_person.trim() || null,
      email: formData.email.trim() || null,
      phone: formData.phone.trim() || null,
      address: formData.address.trim() || null,
      lead_time_days: parseInt(formData.lead_time_days, 10) || 7,
    }

    const res = await dispatch(updateSupplier({ id: selectedSupplier.id, payload }))
    if (updateSupplier.rejected.match(res)) {
      setFormError(res.payload || 'Failed to update supplier.')
    } else {
      setIsEditOpen(false)
    }
    setSubmitting(false)
  }

  // Columns definition
  const columns = useMemo(
    () => [
      {
        key: 'name',
        label: 'Vendor Name',
        sortable: true,
        render: (s) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '6px',
                background: 'var(--erp-brand-subtle)',
                color: 'var(--erp-brand)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                fontSize: '0.85rem',
              }}
            >
              {s.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <div style={{ fontWeight: 600, color: 'var(--erp-text-main)' }}>{s.name}</div>
              <div style={{ fontSize: '0.725rem', color: 'var(--erp-text-muted)' }}>ID #{s.id}</div>
            </div>
          </div>
        ),
      },
      {
        key: 'contact_person',
        label: 'Contact Person',
        sortable: true,
        render: (s) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-text-main)' }}>
            <User size={13} color="var(--erp-text-subtle)" />
            <span>{s.contact_person || '—'}</span>
          </div>
        ),
      },
      {
        key: 'email',
        label: 'Email',
        sortable: true,
        render: (s) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-text-main)' }}>
            <Mail size={13} color="var(--erp-text-subtle)" />
            <span>{s.email || '—'}</span>
          </div>
        ),
      },
      {
        key: 'phone',
        label: 'Phone',
        sortable: false,
        render: (s) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-text-main)' }}>
            <Phone size={13} color="var(--erp-text-subtle)" />
            <span>{s.phone || '—'}</span>
          </div>
        ),
      },
      {
        key: 'address',
        label: 'Address',
        sortable: false,
        render: (s) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--erp-text-muted)', fontSize: '0.8rem', maxWidth: '180px' }}>
            <MapPin size={13} color="var(--erp-text-subtle)" style={{ flexShrink: 0 }} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {s.address || '—'}
            </span>
          </div>
        ),
      },
      {
        key: 'lead_time_days',
        label: 'Lead Time',
        numeric: true,
        sortable: true,
        render: (s) => (
          <span
            style={{
              backgroundColor: 'var(--erp-surface-subtle)',
              color: 'var(--erp-text-main)',
              border: '1px solid var(--erp-border)',
              padding: '3px 8px',
              borderRadius: '4px',
              fontWeight: 600,
              fontSize: '0.775rem',
            }}
          >
            {s.lead_time_days || 7} days
          </span>
        ),
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        sortable: false,
        render: (s) => (
          <Badge
            status={s.is_active ? 'ACTIVE' : 'INACTIVE'}
            label={s.is_active ? 'Active' : 'Inactive'}
          />
        ),
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (s) => (
          <div className="actions-group">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => navigate(`/purchase-orders?supplier_id=${s.id}`)}
              title="Create PO"
            >
              <ClipboardList size={13} />
              <span>New PO</span>
            </button>
            <button
              className="btn-action-icon"
              onClick={() => openEdit(s)}
              title="Edit Vendor"
            >
              <Edit2 size={13} />
            </button>
            <button
              className="btn-action-icon danger"
              onClick={() => dispatch(deactivateSupplier(s))}
              title="Deactivate Vendor"
            >
              <Power size={13} />
            </button>
          </div>
        ),
      },
    ],
    [navigate, openEdit, dispatch]
  )

  return (
    <div className="suppliers-page">
      {/* Action Control Panel */}
      <ErpControlPanel
        moduleName="Purchases"
        activePage="Vendor Network"
        itemCount={suppliers.length}
        primaryAction={{
          label: 'New Supplier',
          icon: Plus,
          onClick: openAddModal,
          id: 'btn-add-supplier',
        }}
        onRefresh={() => dispatch(fetchSuppliers())}
        loading={loading}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchPlaceholder="Search vendor by name, email, phone, contact..."
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        exportData={suppliers}
        exportFilename="vendor_suppliers"
      />

      {/* Table with Pagination OR Cards */}
      {viewMode === 'table' ? (
        <DataTable
          columns={columns}
          data={suppliers}
          keyField="id"
          defaultPageSize={10}
          searchQuery={searchQuery}
          searchFields={['name', 'contact_person', 'email', 'phone', 'address']}
          loading={loading}
          emptyTitle="No vendors registered"
          emptyMessage="Add supplier contacts to issue purchase orders and track shipments."
          emptyIcon={Truck}
        />
      ) : (
        <div className="kanban-grid">
          {suppliers.map((s) => (
            <div key={s.id} className="kanban-card">
              <div className="kanban-header">
                <div>
                  <div className="kanban-title" style={{ fontSize: '1.05rem' }}>{s.name}</div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Vendor ID #{s.id}</div>
                </div>
                <Badge status={s.is_active ? 'ACTIVE' : 'INACTIVE'} />
              </div>

              <div className="kanban-body">
                <div className="kanban-row">
                  <span>Contact:</span>
                  <strong>{s.contact_person || '—'}</strong>
                </div>
                <div className="kanban-row">
                  <span>Email:</span>
                  <span style={{ fontSize: '0.8rem' }}>{s.email || '—'}</span>
                </div>
                <div className="kanban-row">
                  <span>Phone:</span>
                  <span style={{ fontSize: '0.8rem' }}>{s.phone || '—'}</span>
                </div>
                <div className="kanban-row">
                  <span>Standard Lead Time:</span>
                  <strong>{s.lead_time_days || 7} days</strong>
                </div>
                {s.address && (
                  <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
                    <MapPin size={12} style={{ display: 'inline', marginRight: '3px' }} />
                    {s.address}
                  </div>
                )}
              </div>

              <div className="kanban-footer">
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => navigate(`/purchase-orders?supplier_id=${s.id}`)}
                >
                  <ClipboardList size={13} />
                  <span>Create PO</span>
                </button>
                <div style={{ display: 'flex', gap: '4px' }}>
                  <button
                    className="btn btn-subtle btn-sm"
                    onClick={() => openEdit(s)}
                    title="Edit"
                  >
                    <Edit2 size={13} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal: Add Supplier */}
      <Modal
        isOpen={isAddOpen}
        onClose={() => setIsAddOpen(false)}
        title="Add Vendor / Supplier"
        subtitle="Backend strictly validates that supplier name and email are unique."
        size="md"
      >
        <form onSubmit={handleAddSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>
                  <strong>Backend Validation Rule:</strong> {formError}
                </div>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">
                Company / Vendor Name <span className="required">*</span>
              </label>
              <input
                type="text"
                required
                className="form-control"
                placeholder="e.g. Apex Industrial Supplies"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
              <span className="form-hint">Must be unique across active vendors.</span>
            </div>

            <div className="form-group">
              <label className="form-label">Contact Person Name</label>
              <input
                type="text"
                className="form-control"
                placeholder="e.g. Sarah Jenkins"
                value={formData.contact_person}
                onChange={(e) => setFormData({ ...formData, contact_person: e.target.value })}
              />
            </div>

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Email Address</label>
                <input
                  type="email"
                  className="form-control"
                  placeholder="vendor@company.com"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Phone Number</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="+1 (555) 000-0000"
                  value={formData.phone}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Average Fulfillment Lead Time (Days)</label>
              <input
                type="number"
                min="1"
                className="form-control"
                value={formData.lead_time_days}
                onChange={(e) => setFormData({ ...formData, lead_time_days: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Warehouse / Office Address</label>
              <textarea
                rows="2"
                className="form-control"
                placeholder="Street address, City, Country..."
                value={formData.address}
                onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsAddOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              id="btn-save-supplier"
            >
              {submitting ? 'Creating Supplier...' : 'Save Supplier'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: Edit Supplier */}
      <Modal
        isOpen={isEditOpen}
        onClose={() => setIsEditOpen(false)}
        title={`Edit Supplier: ${selectedSupplier?.name}`}
        size="md"
      >
        <form onSubmit={handleEditSubmit}>
          <div className="modal-body">
            {formError && (
              <div className="form-error-banner">
                <AlertTriangle size={18} style={{ flexShrink: 0 }} />
                <div>{formError}</div>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Company Name</label>
              <input
                type="text"
                required
                className="form-control"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Contact Person</label>
              <input
                type="text"
                className="form-control"
                value={formData.contact_person}
                onChange={(e) => setFormData({ ...formData, contact_person: e.target.value })}
              />
            </div>

            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Email Address</label>
                <input
                  type="email"
                  className="form-control"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                />
              </div>

              <div className="form-group">
                <label className="form-label">Phone</label>
                <input
                  type="text"
                  className="form-control"
                  value={formData.phone}
                  onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Lead Time (Days)</label>
              <input
                type="number"
                min="1"
                className="form-control"
                value={formData.lead_time_days}
                onChange={(e) => setFormData({ ...formData, lead_time_days: e.target.value })}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Address</label>
              <textarea
                rows="2"
                className="form-control"
                value={formData.address}
                onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsEditOpen(false)}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Saving...' : 'Update Supplier'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
