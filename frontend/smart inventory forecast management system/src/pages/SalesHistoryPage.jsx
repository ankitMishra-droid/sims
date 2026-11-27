import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { Plus, RefreshCw, Eye, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { showToast } from '../store/uiSlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import CsvExportButton from '../components/common/CsvExportButton'
import Badge from '../components/Badge'
import Modal from '../components/Modal'
import { ErrorState, ConfirmDialog } from '../components/common/StateBlocks'

export default function SalesHistoryPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const products = useSelector(selectAllProducts)

  const [sales, setSales] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedSale, setSelectedSale] = useState(null)
  const [cancelTarget, setCancelTarget] = useState(null)
  const [cancelling, setCancelling] = useState(false)

  const loadSales = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.getSalesPage({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        limit: 500,
        skip: 0,
      })
      setSales(res.data || [])
      setTotalCount(res.total ?? (res.data || []).length)
    } catch (err) {
      setError(err.message || 'Failed to load sales history.')
    } finally {
      setLoading(false)
    }
  }, [startDate, endDate])

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  useEffect(() => {
    const id = setTimeout(() => {
      loadSales()
    }, 0)
    return () => clearTimeout(id)
  }, [loadSales])

  const productsMap = useMemo(() => {
    const m = {}
    products.forEach((p) => {
      m[p.id] = p
    })
    return m
  }, [products])

  const filteredSales = useMemo(() => {
    const q = searchQuery.toLowerCase().trim()
    if (!q) return sales
    return sales.filter((s) => {
      const p = productsMap[s.product_id]
      return (
        String(s.id).includes(q) ||
        (p && (p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q))) ||
        (s.sales_date && s.sales_date.toLowerCase().includes(q))
      )
    })
  }, [sales, productsMap, searchQuery])

  const handleCancelSale = async () => {
    if (!cancelTarget) return
    setCancelling(true)
    try {
      await api.cancelSale(cancelTarget.id, 'sale_cancelled_by_user')
      dispatch(showToast('Sale Cancelled', `Sale #SO-${String(cancelTarget.id).padStart(4, '0')} reversed.`, 'info'))
      setCancelTarget(null)
      await loadSales()
      dispatch(fetchProducts())
    } catch (err) {
      dispatch(showToast('Cancel Failed', err.message || 'Could not cancel sale.', 'error'))
    } finally {
      setCancelling(false)
    }
  }

  const columns = useMemo(
    () => [
      {
        key: 'id',
        label: 'Sale ID',
        sortable: true,
        render: (s) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>#SO-{String(s.id).padStart(4, '0')}</span>,
      },
      {
        key: 'sales_date',
        label: 'Date',
        sortable: true,
        render: (s) => (s.sales_date ? new Date(s.sales_date).toLocaleString() : '—'),
      },
      {
        key: 'product_id',
        label: 'Product',
        render: (s) => {
          const p = productsMap[s.product_id]
          return p ? `${p.name} (${p.sku})` : `Product #${s.product_id}`
        },
      },
      {
        key: 'quantity_sold',
        label: 'Quantity',
        numeric: true,
        sortable: true,
      },
      {
        key: 'selling_price',
        label: 'Unit Price',
        numeric: true,
        sortable: true,
        render: (s) => `₹${Number(s.selling_price || 0).toFixed(2)}`,
      },
      {
        key: 'revenue',
        label: 'Total',
        numeric: true,
        sortable: true,
        render: (s) => <strong style={{ color: '#059669' }}>₹{Number(s.revenue || 0).toFixed(2)}</strong>,
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        render: (s) => <Badge status={s.status === 'CANCELLED' ? 'CANCELLED' : 'RECEIVED'} label={s.status || 'COMPLETED'} />,
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (s) => (
          <div className="actions-group">
            <button type="button" className="btn-action-icon" title="Details" onClick={() => setSelectedSale(s)}>
              <Eye size={14} />
            </button>
            {s.status !== 'CANCELLED' && (
              <button
                type="button"
                className="btn-action-icon danger"
                title="Cancel & Reverse Stock"
                onClick={() => setCancelTarget(s)}
              >
                <RotateCcw size={14} />
              </button>
            )}
          </div>
        ),
      },
    ],
    [productsMap]
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Sales History"
        subtitle={`Showing ${filteredSales.length} of ${totalCount.toLocaleString()} recorded sales`}
        actions={
          <>
            <CsvExportButton data={filteredSales} filename="sales_history" />
            <button type="button" className="btn btn-secondary btn-sm" onClick={loadSales} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => navigate('/sales/new')}>
              <Plus size={14} />
              <span>Record Sale</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={loadSales} />}

      <div className="section-card" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          className="form-control"
          style={{ flex: '1 1 220px', maxWidth: '320px' }}
          placeholder="Search Sale ID, product, or SKU..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <input
          type="date"
          className="form-control"
          style={{ width: '160px' }}
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          aria-label="Start date"
        />
        <input
          type="date"
          className="form-control"
          style={{ width: '160px' }}
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          aria-label="End date"
        />
      </div>

      <DataTable
        columns={columns}
        data={filteredSales}
        keyField="id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No sales found"
        emptyMessage="Record a sale or adjust your date filters."
      />

      <Modal
        isOpen={Boolean(selectedSale)}
        onClose={() => setSelectedSale(null)}
        title={selectedSale ? `Sale #SO-${String(selectedSale.id).padStart(4, '0')}` : 'Sale Details'}
      >
        {selectedSale && (
          <div className="modal-body">
            <div className="form-grid">
              <div><strong>Product:</strong> {productsMap[selectedSale.product_id]?.name || `#${selectedSale.product_id}`}</div>
              <div><strong>Status:</strong> {selectedSale.status || 'COMPLETED'}</div>
              <div><strong>Quantity:</strong> {selectedSale.quantity_sold}</div>
              <div><strong>Unit Price:</strong> ₹{Number(selectedSale.selling_price).toFixed(2)}</div>
              <div><strong>Total Revenue:</strong> ₹{Number(selectedSale.revenue).toFixed(2)}</div>
              <div><strong>Date:</strong> {new Date(selectedSale.sales_date).toLocaleString()}</div>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(cancelTarget)}
        onClose={() => setCancelTarget(null)}
        onConfirm={handleCancelSale}
        title="Cancel Sale & Reverse Stock"
        message={`Cancel sale #SO-${cancelTarget ? String(cancelTarget.id).padStart(4, '0') : ''}? This will restore ${cancelTarget?.quantity_sold || 0} units back to inventory via a REVERSAL ledger entry.`}
        confirmLabel="Cancel Sale"
        danger
        loading={cancelling}
      />
    </div>
  )
}
