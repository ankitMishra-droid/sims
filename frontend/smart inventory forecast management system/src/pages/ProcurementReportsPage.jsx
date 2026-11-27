import { useEffect, useState, useMemo, useCallback } from 'react'
import { api } from '../api'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import KpiCard from '../components/common/KpiCard'
import DataTable from '../components/common/DataTable'
import Badge from '../components/Badge'
import CsvExportButton from '../components/common/CsvExportButton'
import { LoadingState, ErrorState } from '../components/common/StateBlocks'
import { ClipboardList, Truck, Users, Clock, RefreshCw } from 'lucide-react'

const formatCurrency = (val) =>
  `₹${Number(val || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function ProcurementReportsPage() {
  const { t } = useTranslation()
  const [poMetrics, setPoMetrics] = useState(null)
  const [supMetrics, setSupMetrics] = useState(null)
  const [orders, setOrders] = useState([])
  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadReport = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [pmRes, smRes, poRes, supRes] = await Promise.all([
        api.getPurchaseOrderMetrics(),
        api.getSupplierMetrics(),
        api.getPurchaseOrders(),
        api.getSuppliers(),
      ])
      setPoMetrics(pmRes)
      setSupMetrics(smRes)
      setOrders(Array.isArray(poRes) ? poRes : [])
      setSuppliers(Array.isArray(supRes) ? supRes : [])
    } catch (err) {
      setError(err.message || 'Failed to load procurement report')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => {
      loadReport()
    }, 0)
    return () => clearTimeout(id)
  }, [loadReport])

  const statusSummary = useMemo(() => {
    const counts = { DRAFT: 0, SENT: 0, PARTIALLY_RECEIVED: 0, RECEIVED: 0, CANCELLED: 0 }
    const spend = { DRAFT: 0, SENT: 0, PARTIALLY_RECEIVED: 0, RECEIVED: 0, CANCELLED: 0 }
    orders.forEach((po) => {
      const st = String(po.status || 'DRAFT').toUpperCase()
      counts[st] = (counts[st] || 0) + 1
      spend[st] = (spend[st] || 0) + Number(po.total_amount || 0)
    })
    return Object.keys(counts).map((st) => ({
      status: st,
      count: counts[st],
      amount: spend[st],
    }))
  }, [orders])

  const supplierSummary = useMemo(() => {
    const supMap = new Map(suppliers.map((s) => [s.id, s]))
    const agg = new Map()
    orders.forEach((po) => {
      const sup = supMap.get(po.supplier_id)
      const cur = agg.get(po.supplier_id) || {
        supplier_id: po.supplier_id,
        supplier_name: sup?.name || `Supplier #${po.supplier_id}`,
        lead_time_days: sup?.lead_time_days ?? '—',
        po_count: 0,
        open_pos: 0,
        total_value: 0,
      }
      cur.po_count += 1
      if (['DRAFT', 'SENT', 'PARTIALLY_RECEIVED'].includes(String(po.status).toUpperCase())) {
        cur.open_pos += 1
      }
      if (String(po.status).toUpperCase() !== 'CANCELLED') {
        cur.total_value += Number(po.total_amount || 0)
      }
      agg.set(po.supplier_id, cur)
    })
    return Array.from(agg.values()).sort((a, b) => b.total_value - a.total_value)
  }, [orders, suppliers])

  const supplierColumns = [
    {
      key: 'supplier_name',
      label: 'Supplier',
      render: (row) => <strong>{row.supplier_name}</strong>,
    },
    { key: 'lead_time_days', label: 'Lead Time (Days)' },
    { key: 'po_count', label: 'Total POs' },
    {
      key: 'open_pos',
      label: 'Open POs',
      render: (row) => (
        <Badge status={row.open_pos > 0 ? 'PENDING' : 'DRAFT'} label={String(row.open_pos)} />
      ),
    },
    {
      key: 'total_value',
      label: 'Total Committed Value',
      render: (row) => <strong>{formatCurrency(row.total_value)}</strong>,
    },
  ]

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('reports.procurementTitle')}
        subtitle={t('reports.procurementSubtitle')}
        actions={
          <>
            <CsvExportButton
              data={orders}
              filename="procurement_report"
              title="Export CSV"
            />
            <button type="button" className="btn btn-secondary" onClick={loadReport} disabled={loading}>
              <RefreshCw size={15} />
              <span>{t('common.refresh')}</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={loadReport} />}

      {loading ? (
        <LoadingState message="Loading live procurement metrics..." />
      ) : (
        <>
          <div className="erp-grid-4">
            <KpiCard
              title="Total Purchase Orders"
              value={Number(poMetrics?.total_purchase_orders || 0).toLocaleString()}
              subtitle={`${poMetrics?.pending_purchase_orders ?? 0} pending orders`}
              icon={ClipboardList}
              color="blue"
            />
            <KpiCard
              title="Expected Incoming Units"
              value={Number(poMetrics?.expected_stock || 0).toLocaleString()}
              subtitle={`${poMetrics?.incomplete_deliveries ?? 0} partially received`}
              icon={Truck}
              color="emerald"
            />
            <KpiCard
              title="Active Suppliers"
              value={Number(supMetrics?.active_suppliers || 0).toLocaleString()}
              subtitle={`${supMetrics?.total_suppliers ?? 0} total suppliers`}
              icon={Users}
              color="purple"
            />
            <KpiCard
              title="Suppliers With Pending POs"
              value={Number(supMetrics?.suppliers_with_pending_pos || 0).toLocaleString()}
              subtitle={`${supMetrics?.inactive_suppliers ?? 0} inactive suppliers`}
              icon={Clock}
              color="amber"
            />
          </div>

          <div className="dashboard-grid-2">
            <div className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">Purchase Order Status Summary</h2>
              </div>
              <div style={{ display: 'grid', gap: '0.6rem' }}>
                {statusSummary.map((row) => (
                  <div
                    key={row.status}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '0.7rem 0.85rem',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--erp-surface-muted)',
                      border: '1px solid var(--erp-border)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                      <Badge status={row.status} />
                      <span style={{ fontSize: '0.82rem', color: 'var(--erp-text-muted)' }}>
                        {row.count} orders
                      </span>
                    </div>
                    <strong style={{ fontSize: '0.9rem' }}>{formatCurrency(row.amount)}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div className="section-card">
              <div className="section-card-header">
                <h2 className="section-card-title">Supplier Procurement Breakdown</h2>
              </div>
              <DataTable
                columns={supplierColumns}
                data={supplierSummary}
                keyField="supplier_id"
                pageSize={8}
                emptyMessage="No supplier purchase orders recorded yet."
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
