import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Building2, Save } from 'lucide-react'
import { api } from '../../api'
import { setCurrentWorkspace, setWorkspaces } from '../../store/authSlice'
import { addToast } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'
import Badge from '../../components/Badge'
import { LoadingState, ErrorState } from '../../components/common/StateBlocks'
import FormField from '../../components/common/FormField'

export default function BusinessSettingsPage() {
  const dispatch = useDispatch()
  const { t } = useTranslation()
  const { currentWorkspace } = useSelector((state) => state.auth)
  const canEdit = (currentWorkspace?.permissions || []).includes('business.update')

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    name: '',
    business_type: 'retailer',
    default_language: 'en',
    contact_email: '',
    contact_phone: '',
    address: '',
    gstin_or_tax_id: '',
    currency: 'INR',
    low_stock_threshold_default: 10,
    allow_negative_stock: false,
  })

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const ws = await api.getCurrentWorkspace()
        if (!active) return
        dispatch(setCurrentWorkspace(ws))
        const b = ws.business
        setForm({
          name: b.name || '',
          business_type: b.business_type || 'retailer',
          default_language: b.default_language || 'en',
          contact_email: b.contact_email || '',
          contact_phone: b.contact_phone || '',
          address: b.address || '',
          gstin_or_tax_id: b.gstin_or_tax_id || '',
          currency: b.currency || 'INR',
          low_stock_threshold_default: b.low_stock_threshold_default ?? 10,
          allow_negative_stock: !!b.allow_negative_stock,
        })
      } catch (err) {
        if (active) setError(err.message || 'Failed to load workspace settings.')
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [dispatch])

  const handleSave = async (e) => {
    e.preventDefault()
    if (!canEdit) return
    setSaving(true)
    try {
      const updatedBiz = await api.updateCurrentWorkspace({
        ...form,
        contact_email: form.contact_email.trim() || null,
        contact_phone: form.contact_phone.trim() || null,
        address: form.address.trim() || null,
        gstin_or_tax_id: form.gstin_or_tax_id.trim() || null,
        low_stock_threshold_default: Number(form.low_stock_threshold_default || 0),
      })
      const wsList = await api.getWorkspaces()
      dispatch(setWorkspaces(wsList))
      if (currentWorkspace) {
        dispatch(setCurrentWorkspace({ ...currentWorkspace, business: updatedBiz }))
      }
      dispatch(addToast({ type: 'success', message: 'Business settings saved.' }))
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to save business settings.' }))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('workspace.manageTitle')}
        subtitle="Configure active workspace details, defaults, and stock policy."
        badge={currentWorkspace ? <Badge status="SENT" label={`Role: ${currentWorkspace.role}`} /> : null}
      />

      {error && <ErrorState message={error} />}

      {loading ? (
        <LoadingState message={t('common.loading')} />
      ) : (
        <div className="section-card">
          <div className="section-card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Building2 size={18} color="var(--erp-brand)" />
              <h2 className="section-card-title">Workspace Profile (#{currentWorkspace?.business?.id})</h2>
            </div>
          </div>

          <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
            <div className="form-grid">
              <FormField label="Business Name" htmlFor="biz-name" required>
                <input
                  id="biz-name"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.businessName', 'e.g. Sangati Supermart')}
                  value={form.name}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </FormField>
              <FormField label="Business Type" htmlFor="biz-type">
                <select
                  id="biz-type"
                  className="form-control"
                  value={form.business_type}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, business_type: e.target.value })}
                >
                  <option value="retailer">Retailer</option>
                  <option value="wholesaler">Wholesaler</option>
                  <option value="supplier">Supplier</option>
                </select>
              </FormField>
              <FormField label="Default Language" htmlFor="biz-lang">
                <select
                  id="biz-lang"
                  className="form-control"
                  value={form.default_language}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, default_language: e.target.value })}
                >
                  <option value="en">English</option>
                  <option value="hi">Hindi (हिन्दी)</option>
                </select>
              </FormField>
              <FormField label="Contact Email" htmlFor="biz-email">
                <input
                  id="biz-email"
                  type="email"
                  className="form-control"
                  placeholder={t('placeholders.workEmail', 'e.g. name@company.com')}
                  value={form.contact_email}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                />
              </FormField>
              <FormField label="Contact Phone" htmlFor="biz-phone">
                <input
                  id="biz-phone"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierPhone', 'e.g. +91 98765 43210')}
                  value={form.contact_phone}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
                />
              </FormField>
              <FormField label="GSTIN / Tax ID" htmlFor="biz-gstin" hint="Optional 15-character tax registration">
                <input
                  id="biz-gstin"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.gstin', 'e.g. 27AAACS1234F1Z5')}
                  value={form.gstin_or_tax_id}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, gstin_or_tax_id: e.target.value })}
                />
              </FormField>
              <FormField label="Currency" htmlFor="biz-currency">
                <input
                  id="biz-currency"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.currency', 'e.g. INR')}
                  value={form.currency}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, currency: e.target.value })}
                />
              </FormField>
              <FormField
                label="Default Low-Stock Threshold"
                htmlFor="biz-threshold"
                hint="Applied as default reorder alert baseline for new products"
              >
                <input
                  id="biz-threshold"
                  type="number"
                  min={0}
                  className="form-control"
                  placeholder={t('placeholders.thresholdDefault', 'e.g. 20')}
                  value={form.low_stock_threshold_default}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, low_stock_threshold_default: e.target.value })}
                />
              </FormField>
              <FormField label="Address" htmlFor="biz-address" className="col-span-2">
                <input
                  id="biz-address"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierAddress', 'e.g. Plot 14, Market Yard, Jaipur')}
                  value={form.address}
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </FormField>
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.84rem', color: 'var(--erp-text-main)' }}>
              <input
                type="checkbox"
                checked={form.allow_negative_stock}
                disabled={!canEdit}
                onChange={(e) => setForm({ ...form, allow_negative_stock: e.target.checked })}
              />
              <span>Allow negative stock on sales/adjustments</span>
            </label>

            {canEdit && (
              <div>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  <Save size={15} />
                  <span>{saving ? t('common.saving') : t('common.save')}</span>
                </button>
              </div>
            )}
          </form>
        </div>
      )}
    </div>
  )
}
