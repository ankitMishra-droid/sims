import { useCallback, useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import {
  CheckCircle2,
  ArrowLeft,
  ArrowRight,
  SkipForward,
  Plus,
  Trash2,
  Sparkles,
  HelpCircle,
  Upload,
} from 'lucide-react'
import { api } from '../../api'
import { setCurrentWorkspace, setOnboardingProgress, updateUserProfile } from '../../store/authSlice'
import { addToast, setLanguage } from '../../store/uiSlice'
import { useTranslation } from '../../hooks/useTranslation'
import PageHeader from '../../components/common/PageHeader'
import Badge from '../../components/Badge'
import { LoadingState, ErrorState } from '../../components/common/StateBlocks'
import { createStableRowKey } from '../../utils/formHelpers'

const OPTIONAL_STEPS = new Set([6, 7, 8, 9])

export default function OnboardingWizardPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const { t, language } = useTranslation()
  const { currentWorkspace, user } = useSelector((state) => state.auth)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(null)
  const [workspaceProducts, setWorkspaceProducts] = useState([])

  const [businessType, setBusinessType] = useState('retailer')
  const [selectedLang, setSelectedLang] = useState(language || 'en')
  const [profile, setProfile] = useState({
    name: '',
    contact_email: '',
    contact_phone: '',
    address: '',
    gstin_or_tax_id: '',
  })
  const [prefs, setPrefs] = useState({
    currency: 'INR',
    low_stock_threshold_default: 10,
    allow_negative_stock: false,
  })
  const [draftProducts, setDraftProducts] = useState(() => [
    { _key: createStableRowKey('onb-prod'), sku: '', name: '', category: 'General', unit: 'piece', cost_price: '', selling_price: '', reorder_level: '10' },
  ])
  const [csvPreviewRows, setCsvPreviewRows] = useState([])
  const [csvResultMsg, setCsvResultMsg] = useState('')
  const [draftSuppliers, setDraftSuppliers] = useState(() => [
    { _key: createStableRowKey('onb-sup'), name: '', contact_person: '', email: '', phone: '', lead_time_days: '7' },
  ])
  const [openingEntries, setOpeningEntries] = useState({})

  const hydrateFromProgress = useCallback((prog, ws) => {
    setProgress(prog)
    dispatch(setOnboardingProgress(prog))
    const biz = ws?.business
    if (biz) {
      setBusinessType(biz.business_type || 'retailer')
      setSelectedLang(biz.default_language || user?.preferred_language || 'en')
      setProfile({
        name: biz.name || '',
        contact_email: biz.contact_email || '',
        contact_phone: biz.contact_phone || '',
        address: biz.address || '',
        gstin_or_tax_id: biz.gstin_or_tax_id || '',
      })
      setPrefs({
        currency: biz.currency || 'INR',
        low_stock_threshold_default: biz.low_stock_threshold_default ?? 10,
        allow_negative_stock: !!biz.allow_negative_stock,
      })
    }
  }, [dispatch, user?.preferred_language])

  const loadWizard = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [ws, prog] = await Promise.all([
        api.getCurrentWorkspace(),
        api.getOnboardingProgress(),
      ])
      dispatch(setCurrentWorkspace(ws))
      hydrateFromProgress(prog, ws)
      if (ws?.business?.business_type !== 'supplier') {
        const prods = await api.getProducts()
        setWorkspaceProducts(Array.isArray(prods) ? prods : [])
      }
    } catch (err) {
      setError(err.message || 'Failed to load onboarding progress.')
    } finally {
      setLoading(false)
    }
  }, [dispatch, hydrateFromProgress])

  useEffect(() => {
    const id = setTimeout(() => {
      loadWizard()
    }, 0)
    return () => clearTimeout(id)
  }, [loadWizard])

  const applicableSteps = progress?.applicable_steps || [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
  const currentStep = progress?.current_step || 1
  const currentStepIdx = Math.max(0, applicableSteps.indexOf(currentStep))
  const completedSteps = new Set(progress?.completed_steps || [])

  const submitStepAction = async (action, data = {}) => {
    setSaving(true)
    try {
      const updatedProg = await api.saveOnboardingStep({
        step: currentStep,
        action,
        data,
      })
      const ws = await api.getCurrentWorkspace()
      dispatch(setCurrentWorkspace(ws))
      if (currentStep === 3 && action === 'complete' && data.language) {
        dispatch(setLanguage(data.language))
        if (user) dispatch(updateUserProfile({ ...user, preferred_language: data.language }))
      }
      hydrateFromProgress(updatedProg, ws)

      if (ws?.business?.business_type !== 'supplier' && (currentStep === 6 || updatedProg.current_step === 8)) {
        const prods = await api.getProducts()
        setWorkspaceProducts(Array.isArray(prods) ? prods : [])
      }

      if (currentStep === 10 && action === 'complete') {
        dispatch(addToast({ type: 'success', message: 'Workspace setup complete!' }))
        navigate(ws?.business?.business_type === 'supplier' ? '/supplier-portal' : '/dashboard', { replace: true })
      }
    } catch (err) {
      dispatch(addToast({ type: 'error', message: err.message || 'Failed to save step.' }))
    } finally {
      setSaving(false)
    }
  }

  const handleNext = () => {
    if (currentStep === 2) return submitStepAction('complete', { business_type: businessType })
    if (currentStep === 3) return submitStepAction('complete', { language: selectedLang })
    if (currentStep === 4) {
      if (profile.name.trim().length < 2) {
        dispatch(addToast({ type: 'error', message: t('validation.workspaceNameLength') }))
        return
      }
      return submitStepAction('complete', profile)
    }
    if (currentStep === 5) {
      return submitStepAction('complete', {
        ...prefs,
        low_stock_threshold_default: Number(prefs.low_stock_threshold_default || 0),
      })
    }
    if (currentStep === 6) {
      const validProducts = draftProducts
        .filter((p) => p.sku.trim() && p.name.trim())
        .map((p) => ({
          ...p,
          cost_price: Number(p.cost_price || 0),
          selling_price: Number(p.selling_price || 0),
          reorder_level: Number(p.reorder_level || prefs.low_stock_threshold_default || 10),
        }))
      return submitStepAction('complete', { products: validProducts })
    }
    if (currentStep === 7) {
      const validSuppliers = draftSuppliers
        .filter((s) => s.name.trim())
        .map((s) => ({
          ...s,
          email: s.email.trim() || null,
          lead_time_days: Number(s.lead_time_days || 7),
        }))
      return submitStepAction('complete', { suppliers: validSuppliers })
    }
    if (currentStep === 8) {
      const entries = Object.entries(openingEntries)
        .map(([prodId, qty]) => ({ product_id: Number(prodId), quantity: Number(qty || 0) }))
        .filter((e) => e.quantity > 0)
      return submitStepAction('complete', { opening_stocks: entries })
    }
    return submitStepAction('complete', {})
  }

  const stepTitle = t(`onboarding.steps.${currentStep}.title`, `Step ${currentStep}`)
  const stepDesc = t(`onboarding.steps.${currentStep}.desc`, '')
  const progressPct = Math.round(((currentStepIdx + 1) / applicableSteps.length) * 100)

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('onboarding.title')}
        subtitle={t('onboarding.subtitle')}
        badge={currentWorkspace ? <Badge status="SENT" label={`${currentWorkspace.business.name} • ${businessType.toUpperCase()}`} /> : null}
      />

      {error && <ErrorState message={error} onRetry={loadWizard} />}

      {loading ? (
        <LoadingState message={t('common.loading')} />
      ) : (
        <div className="section-card" style={{ maxWidth: '940px' }}>
          <div style={{ marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem', fontSize: '0.82rem' }}>
              <strong>
                {t('onboarding.stepOf')} {currentStepIdx + 1} / {applicableSteps.length}: {stepTitle}
              </strong>
              <span style={{ color: 'var(--erp-text-muted)' }}>{progressPct}%</span>
            </div>
            <div style={{ height: '7px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--erp-border)', overflow: 'hidden' }}>
              <div style={{ width: `${progressPct}%`, height: '100%', backgroundColor: 'var(--erp-brand)', transition: 'width 0.2s' }} />
            </div>
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
              {applicableSteps.map((st, idx) => (
                <span
                  key={st}
                  style={{
                    fontSize: 'var(--text-xs)',
                    padding: '0.2rem 0.6rem',
                    borderRadius: 'var(--radius-full)',
                    border: st === currentStep ? '1px solid var(--erp-brand)' : '1px solid var(--erp-border)',
                    backgroundColor: completedSteps.has(st)
                      ? 'var(--status-success-bg)'
                      : st === currentStep
                        ? 'var(--erp-brand-subtle)'
                        : 'transparent',
                    color: completedSteps.has(st)
                      ? 'var(--status-success-text)'
                      : st === currentStep
                        ? 'var(--erp-brand)'
                        : 'var(--erp-text-muted)',
                    fontWeight: st === currentStep ? 'var(--font-weight-semibold)' : 'var(--font-weight-medium)',
                  }}
                >
                  {idx + 1}. {t(`onboarding.steps.${st}.title`)}
                </span>
              ))}
            </div>
          </div>

          <p style={{ margin: '0 0 1.25rem', fontSize: 'var(--text-base)', color: 'var(--erp-text-muted)', lineHeight: 'var(--leading-normal)' }}>
            {stepDesc}
          </p>

          {currentStep === 1 && (
            <div style={{ padding: '1rem 1.15rem', borderRadius: 'var(--radius-lg)', backgroundColor: 'var(--erp-brand-subtle)', border: '1px solid var(--erp-border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
                <Sparkles size={18} color="var(--erp-brand)" />
                <strong>{currentWorkspace?.business?.name}</strong>
              </div>
              <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--erp-text-muted)' }}>
                Your progress is saved after every step so you can pause or resume anytime across sessions.
              </p>
            </div>
          )}

          {currentStep === 2 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
              {['retailer', 'wholesaler', 'supplier'].map((bt) => (
                <button
                  key={bt}
                  type="button"
                  onClick={() => setBusinessType(bt)}
                  className={`choice-tile ${businessType === bt ? 'selected' : ''}`}
                >
                  <strong style={{ textTransform: 'capitalize' }}>{bt}</strong>
                  <span style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                    {t(`workspace.types.${bt}`)}
                  </span>
                </button>
              ))}
            </div>
          )}

          {currentStep === 3 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
              {[
                { code: 'en', label: 'English', sub: 'Standard business English' },
                { code: 'hi', label: 'हिन्दी (Hindi)', sub: 'सरल व्यावसायिक हिंदी और अंग्रेजी (SKU, PO) के साथ' },
              ].map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setSelectedLang(l.code)}
                  className={`choice-tile ${selectedLang === l.code ? 'selected' : ''}`}
                >
                  <strong>{l.label}</strong>
                  <span style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>{l.sub}</span>
                </button>
              ))}
            </div>
          )}

          {currentStep === 4 && (
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="onb-biz-name">
                  Business Name <span className="required">*</span>
                </label>
                <input
                  id="onb-biz-name"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.businessName', 'e.g. Sangati Supermart')}
                  value={profile.name}
                  onChange={(e) => setProfile((prev) => ({ ...prev, name: e.target.value }))}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="onb-biz-phone">Contact Phone</label>
                <input
                  id="onb-biz-phone"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierPhone', 'e.g. +91 98765 43210')}
                  value={profile.contact_phone}
                  onChange={(e) => setProfile((prev) => ({ ...prev, contact_phone: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="onb-biz-email">Contact Email</label>
                <input
                  id="onb-biz-email"
                  type="email"
                  className="form-control"
                  placeholder={t('placeholders.workEmail', 'e.g. name@company.com')}
                  value={profile.contact_email}
                  onChange={(e) => setProfile((prev) => ({ ...prev, contact_email: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="onb-biz-gstin">GSTIN / Tax ID</label>
                <input
                  id="onb-biz-gstin"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.gstin', 'e.g. 27AAACS1234F1Z5')}
                  value={profile.gstin_or_tax_id}
                  onChange={(e) => setProfile((prev) => ({ ...prev, gstin_or_tax_id: e.target.value }))}
                />
              </div>
              <div className="form-group col-span-2">
                <label className="form-label" htmlFor="onb-biz-address">Address</label>
                <input
                  id="onb-biz-address"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.supplierAddress', 'e.g. Plot 14, Market Yard, Jaipur')}
                  value={profile.address}
                  onChange={(e) => setProfile((prev) => ({ ...prev, address: e.target.value }))}
                />
              </div>
            </div>
          )}

          {currentStep === 5 && (
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="onb-pref-currency">Currency</label>
                <input
                  id="onb-pref-currency"
                  type="text"
                  className="form-control"
                  placeholder={t('placeholders.currency', 'e.g. INR')}
                  value={prefs.currency}
                  onChange={(e) => setPrefs((prev) => ({ ...prev, currency: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="onb-pref-threshold">Default Low-Stock Threshold</label>
                <input
                  id="onb-pref-threshold"
                  type="number"
                  min={0}
                  step={1}
                  className="form-control"
                  placeholder={t('placeholders.thresholdDefault', 'e.g. 20')}
                  value={prefs.low_stock_threshold_default}
                  onChange={(e) => setPrefs((prev) => ({ ...prev, low_stock_threshold_default: e.target.value }))}
                />
              </div>
              <div className="form-group col-span-2">
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.84rem' }}>
                  <input
                    type="checkbox"
                    checked={prefs.allow_negative_stock}
                    onChange={(e) => setPrefs((prev) => ({ ...prev, allow_negative_stock: e.target.checked }))}
                  />
                  <span>Allow negative stock on sales/adjustments</span>
                </label>
              </div>
            </div>
          )}

          {currentStep === 6 && (
            <div style={{ display: 'grid', gap: '0.95rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                <HelpCircle size={14} />
                <span>{t('common.skuHelp')}</span>
              </div>

              <div style={{ padding: '0.9rem', borderRadius: 'var(--radius-md)', border: '1px dashed var(--erp-border-strong)', backgroundColor: 'var(--erp-surface-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <div style={{ fontSize: '0.8rem' }}>
                    <strong>Import Products via CSV</strong>
                    <div style={{ color: 'var(--erp-text-muted)', fontSize: '0.74rem' }}>
                      Columns: sku, name, category, unit, cost_price, selling_price, reorder_level
                    </div>
                  </div>
                  <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
                    <Upload size={14} />
                    <span>Upload CSV</span>
                    <input
                      type="file"
                      accept=".csv,text/csv"
                      style={{ display: 'none' }}
                      onChange={async (e) => {
                        const file = e.target.files?.[0]
                        if (!file) return
                        const text = await file.text()
                        const parseCsvRow = (line) => {
                          const out = []
                          let cur = ''
                          let inQuotes = false
                          for (let idx = 0; idx < line.length; idx += 1) {
                            const ch = line[idx]
                            if (ch === '"') {
                              if (inQuotes && line[idx + 1] === '"') {
                                cur += '"'
                                idx += 1
                              } else {
                                inQuotes = !inQuotes
                              }
                            } else if (ch === ',' && !inQuotes) {
                              out.push(cur.trim())
                              cur = ''
                            } else {
                              cur += ch
                            }
                          }
                          out.push(cur.trim())
                          return out
                        }
                        const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
                        if (lines.length < 2) {
                          setCsvResultMsg('CSV must include header row and at least one data row.')
                          setCsvPreviewRows([])
                          return
                        }
                        const headers = parseCsvRow(lines[0]).map((h) => h.replace(/^\ufeff/, '').toLowerCase())
                        const existingSkus = new Set(workspaceProducts.map((p) => String(p.sku).toLowerCase()))
                        const seenInFile = new Set()
                        const parsed = lines.slice(1).map((line, i) => {
                          const cols = parseCsvRow(line)
                          const rec = {}
                          headers.forEach((h, idx) => { rec[h] = cols[idx] ?? '' })
                          const sku = String(rec.sku || '').trim()
                          const name = String(rec.name || '').trim()
                          const cost = Number(rec.cost_price || 0)
                          const sell = Number(rec.selling_price || 0)
                          const reorder = Number(rec.reorder_level || prefs.low_stock_threshold_default || 10)
                          let issue = ''
                          if (!sku || !name) issue = 'Missing SKU or name'
                          else if (existingSkus.has(sku.toLowerCase()) || seenInFile.has(sku.toLowerCase())) issue = 'Duplicate SKU'
                          else if (Number.isNaN(cost) || cost < 0 || Number.isNaN(sell) || sell < 0) issue = 'Invalid price'
                          seenInFile.add(sku.toLowerCase())
                          return {
                            rowNum: i + 1,
                            sku,
                            name,
                            category: rec.category || 'General',
                            unit: rec.unit || 'piece',
                            cost_price: Number.isNaN(cost) ? 0 : cost,
                            selling_price: Number.isNaN(sell) ? 0 : sell,
                            reorder_level: Number.isNaN(reorder) ? 10 : reorder,
                            valid: !issue,
                            issue,
                          }
                        })
                        setCsvPreviewRows(parsed)
                        setCsvResultMsg('')
                        e.target.value = ''
                      }}
                    />
                  </label>
                </div>

                {csvPreviewRows.length > 0 && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <div className="table-responsive" style={{ maxHeight: '200px' }}>
                      <table className="erp-table" style={{ fontSize: '0.76rem' }}>
                        <thead>
                          <tr>
                            <th>SKU</th>
                            <th>Name</th>
                            <th>Cost</th>
                            <th>Selling</th>
                            <th>Validation</th>
                          </tr>
                        </thead>
                        <tbody>
                          {csvPreviewRows.map((r) => (
                            <tr key={r.rowNum}>
                              <td>{r.sku || '—'}</td>
                              <td>{r.name || '—'}</td>
                              <td>{r.cost_price}</td>
                              <td>{r.selling_price}</td>
                              <td>
                                <Badge status={r.valid ? 'ACTIVE' : 'CANCELLED'} label={r.valid ? 'Valid' : r.issue} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.6rem', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                        {csvPreviewRows.filter((r) => r.valid).length} valid / {csvPreviewRows.length} total rows
                      </span>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                          const validRows = csvPreviewRows.filter((r) => r.valid).map((r) => ({
                            _key: createStableRowKey('onb-prod'),
                            sku: r.sku,
                            name: r.name,
                            category: r.category,
                            unit: r.unit,
                            cost_price: String(r.cost_price),
                            selling_price: String(r.selling_price),
                            reorder_level: String(r.reorder_level),
                          }))
                          if (validRows.length > 0) {
                            const nonEmptyExisting = draftProducts.filter((d) => d.sku.trim() || d.name.trim())
                            setDraftProducts([...nonEmptyExisting, ...validRows])
                            setCsvResultMsg(`Confirmed ${validRows.length} valid product row(s) into setup queue.`)
                            setCsvPreviewRows([])
                          }
                        }}
                      >
                        Confirm &amp; Stage Valid Rows
                      </button>
                    </div>
                  </div>
                )}

                {csvResultMsg && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: 'var(--erp-brand)', fontWeight: 600 }}>
                    {csvResultMsg}
                  </div>
                )}
              </div>

              {draftProducts.map((row) => (
                <div key={row._key} style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr 1fr 1fr auto', gap: '0.5rem', alignItems: 'end' }}>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-prod-sku-${row._key}`}>SKU <span className="required">*</span></label>
                    <input
                      id={`onb-prod-sku-${row._key}`}
                      type="text"
                      className="form-control"
                      placeholder={t('placeholders.productSku', 'e.g. RICE-001')}
                      value={row.sku}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftProducts((prev) => prev.map((it) => (it._key === row._key ? { ...it, sku: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-prod-name-${row._key}`}>Product Name <span className="required">*</span></label>
                    <input
                      id={`onb-prod-name-${row._key}`}
                      type="text"
                      className="form-control"
                      placeholder={t('placeholders.productName', 'e.g. Premium Basmati Rice 5kg')}
                      value={row.name}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftProducts((prev) => prev.map((it) => (it._key === row._key ? { ...it, name: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-prod-cost-${row._key}`}>Cost Price</label>
                    <input
                      id={`onb-prod-cost-${row._key}`}
                      type="number"
                      min={0}
                      step="0.01"
                      className="form-control"
                      placeholder={t('placeholders.costPrice', 'e.g. 45.00')}
                      value={row.cost_price}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftProducts((prev) => prev.map((it) => (it._key === row._key ? { ...it, cost_price: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-prod-sell-${row._key}`}>Selling Price</label>
                    <input
                      id={`onb-prod-sell-${row._key}`}
                      type="number"
                      min={0}
                      step="0.01"
                      className="form-control"
                      placeholder={t('placeholders.sellingPrice', 'e.g. 60.00')}
                      value={row.selling_price}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftProducts((prev) => prev.map((it) => (it._key === row._key ? { ...it, selling_price: val } : it)))
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn-action-icon danger"
                    onClick={() => setDraftProducts((prev) => prev.filter((it) => it._key !== row._key))}
                    disabled={draftProducts.length <= 1}
                    title="Remove row"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() =>
                    setDraftProducts((prev) => [
                      ...prev,
                      { _key: createStableRowKey('onb-prod'), sku: '', name: '', category: 'General', unit: 'piece', cost_price: '', selling_price: '', reorder_level: '10' },
                    ])
                  }
                >
                  <Plus size={14} />
                  <span>Add Product Row</span>
                </button>
              </div>
            </div>
          )}

          {currentStep === 7 && (
            <div style={{ display: 'grid', gap: '0.8rem' }}>
              {draftSuppliers.map((row) => (
                <div key={row._key} style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 0.7fr auto', gap: '0.5rem', alignItems: 'end' }}>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-sup-name-${row._key}`}>Supplier Name <span className="required">*</span></label>
                    <input
                      id={`onb-sup-name-${row._key}`}
                      type="text"
                      className="form-control"
                      placeholder={t('placeholders.supplierName', 'e.g. ABC Wholesale Distributors')}
                      value={row.name}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftSuppliers((prev) => prev.map((it) => (it._key === row._key ? { ...it, name: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-sup-contact-${row._key}`}>Contact Person</label>
                    <input
                      id={`onb-sup-contact-${row._key}`}
                      type="text"
                      className="form-control"
                      placeholder={t('placeholders.supplierContact', 'e.g. Rajesh Verma')}
                      value={row.contact_person}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftSuppliers((prev) => prev.map((it) => (it._key === row._key ? { ...it, contact_person: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-sup-phone-${row._key}`}>Phone</label>
                    <input
                      id={`onb-sup-phone-${row._key}`}
                      type="text"
                      className="form-control"
                      placeholder={t('placeholders.supplierPhone', 'e.g. +91 98765 43210')}
                      value={row.phone}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftSuppliers((prev) => prev.map((it) => (it._key === row._key ? { ...it, phone: val } : it)))
                      }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor={`onb-sup-lead-${row._key}`}>Lead Days</label>
                    <input
                      id={`onb-sup-lead-${row._key}`}
                      type="number"
                      min={0}
                      step={1}
                      className="form-control"
                      placeholder={t('placeholders.supplierLeadDays', 'e.g. 7')}
                      value={row.lead_time_days}
                      onChange={(e) => {
                        const val = e.target.value
                        setDraftSuppliers((prev) => prev.map((it) => (it._key === row._key ? { ...it, lead_time_days: val } : it)))
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn-action-icon danger"
                    onClick={() => setDraftSuppliers((prev) => prev.filter((it) => it._key !== row._key))}
                    disabled={draftSuppliers.length <= 1}
                    title="Remove row"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() =>
                    setDraftSuppliers((prev) => [
                      ...prev,
                      { _key: createStableRowKey('onb-sup'), name: '', contact_person: '', email: '', phone: '', lead_time_days: '7' },
                    ])
                  }
                >
                  <Plus size={14} />
                  <span>Add Supplier Row</span>
                </button>
              </div>
            </div>
          )}

          {currentStep === 8 && (
            <div style={{ display: 'grid', gap: '0.65rem' }}>
              {workspaceProducts.length === 0 ? (
                <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--erp-text-muted)' }}>
                  No products in catalog yet. You can skip this step or go back to Step 6 to add products.
                </p>
              ) : (
                workspaceProducts.map((p) => (
                  <div
                    key={p.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '1rem',
                      padding: '0.7rem 0.9rem',
                      borderRadius: 'var(--radius-md)',
                      backgroundColor: 'var(--erp-surface-subtle)',
                      border: '1px solid var(--erp-border)',
                    }}
                  >
                    <div>
                      <strong>{p.name}</strong>
                      <div style={{ fontSize: '0.75rem', color: 'var(--erp-text-muted)' }}>
                        SKU: {p.sku} • Current stock: {p.current_stock}
                      </div>
                    </div>
                    <input
                      type="number"
                      min={0}
                      placeholder={t('placeholders.openingStock', 'e.g. 25')}
                      aria-label={`Opening stock for ${p.name}`}
                      className="form-control"
                      style={{ width: '140px' }}
                      value={openingEntries[p.id] ?? ''}
                      onChange={(e) =>
                        setOpeningEntries({ ...openingEntries, [p.id]: e.target.value })
                      }
                    />
                  </div>
                ))
              )}
            </div>
          )}

          {currentStep === 9 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.85rem' }}>
              {(businessType === 'supplier'
                ? [
                  { title: 'Shared Purchase Orders', desc: 'View only POs explicitly shared with your supplier workspace.' },
                  { title: 'Dispatch & Updates', desc: 'Acknowledge orders and record dispatch milestones safely.' },
                ]
                : [
                  { title: 'Inventory & Ledger', desc: 'Track on-hand, incoming PO stock, and auditable movements.' },
                  { title: 'Sales & POS', desc: 'Record idempotent sales and automatic stock deductions.' },
                  { title: 'Procurement', desc: 'Create POs, share with linked suppliers, and post goods receipts.' },
                ]
              ).map((card) => (
                <div
                  key={card.title}
                  style={{
                    padding: '0.95rem',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--erp-surface-subtle)',
                    border: '1px solid var(--erp-border)',
                  }}
                >
                  <strong style={{ display: 'block', marginBottom: '0.25rem' }}>{card.title}</strong>
                  <span style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>{card.desc}</span>
                </div>
              ))}
            </div>
          )}

          {currentStep === 10 && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                padding: '1rem',
                borderRadius: 'var(--radius-lg)',
                backgroundColor: 'var(--status-success-bg)',
                border: '1px solid var(--status-success-border)',
                color: 'var(--status-success-text)',
              }}
            >
              <CheckCircle2 size={24} />
              <div>
                <strong>Ready to Launch</strong>
                <p style={{ margin: '0.2rem 0 0', fontSize: '0.82rem' }}>
                  Click &quot;{t('common.finish')}&quot; to mark workspace onboarding complete and open your workspace.
                </p>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', marginTop: '1.5rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={saving || currentStepIdx === 0}
              onClick={() => submitStepAction('back')}
            >
              <ArrowLeft size={15} />
              <span>{t('common.back')}</span>
            </button>

            <div style={{ display: 'flex', gap: '0.6rem' }}>
              {OPTIONAL_STEPS.has(currentStep) && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={saving}
                  onClick={() => submitStepAction('skip')}
                >
                  <SkipForward size={15} />
                  <span>{t('common.skip')}</span>
                </button>
              )}
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving}
                onClick={handleNext}
              >
                <span>{saving ? t('common.saving') : currentStep === 10 ? t('common.finish') : t('common.next')}</span>
                <ArrowRight size={15} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
