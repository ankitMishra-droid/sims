import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { RefreshCw } from 'lucide-react'
import { fetchProducts, selectAllProducts } from '../store/productsSlice'
import { fetchInventoryLogs, selectLogsForProduct } from '../store/inventorySlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import SearchableSelect from '../components/common/SearchableSelect'
import CsvExportButton from '../components/common/CsvExportButton'
import Badge from '../components/Badge'
import { ErrorState } from '../components/common/StateBlocks'

export default function StockHistoryPage() {
  const dispatch = useDispatch()
  const [searchParams, setSearchParams] = useSearchParams()
  const products = useSelector(selectAllProducts)
  const loading = useSelector((state) => state.inventory.loading)
  const error = useSelector((state) => state.inventory.error)

  const [selectedProductId, setSelectedProductId] = useState(searchParams.get('product_id') || '')
  const activeProductId = selectedProductId || (products[0] ? String(products[0].id) : '')
  const logs = useSelector(selectLogsForProduct(activeProductId))

  useEffect(() => {
    dispatch(fetchProducts())
  }, [dispatch])

  useEffect(() => {
    if (activeProductId) {
      dispatch(fetchInventoryLogs(activeProductId))
    }
  }, [activeProductId, dispatch])

  const productOptions = useMemo(
    () =>
      products.map((p) => ({
        value: p.id,
        label: p.name,
        subLabel: `On hand: ${p.current_stock} ${p.unit}`,
        badge: p.sku,
      })),
    [products]
  )

  const columns = useMemo(
    () => [
      {
        key: 'timestamp',
        label: 'Date & Time',
        sortable: true,
        render: (l) => (l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'),
      },
      {
        key: 'movement_type',
        label: 'Movement Type',
        sortable: true,
        render: (l) => <Badge status={l.movement_type} label={l.movement_type} />,
      },
      {
        key: 'previous_stock',
        label: 'Previous',
        numeric: true,
        sortable: true,
      },
      {
        key: 'quantity',
        label: 'Quantity',
        numeric: true,
        sortable: true,
        render: (l) => {
          const qty = Number(l.quantity ?? (l.stock_in || 0) - (l.stock_out || 0))
          return (
            <span style={{ fontWeight: 700, color: qty >= 0 ? '#059669' : '#dc2626' }}>
              {qty > 0 ? `+${qty}` : qty}
            </span>
          )
        },
      },
      {
        key: 'resulting_stock',
        label: 'Resulting',
        numeric: true,
        sortable: true,
        render: (l) => <strong>{l.resulting_stock ?? l.closing_stock}</strong>,
      },
      {
        key: 'reference_type',
        label: 'Reference',
        render: (l) =>
          l.reference_type ? (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.775rem' }}>
              {l.reference_type}
              {l.reference_id ? ` #${l.reference_id}` : ''}
            </span>
          ) : (
            '—'
          ),
      },
      {
        key: 'user_id',
        label: 'User',
        render: (l) => (l.user_id ? `User #${l.user_id}` : 'System'),
      },
      { key: 'reason', label: 'Reason', sortable: true },
    ],
    []
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <PageHeader
        title="Stock Movement History"
        subtitle="Traceable inventory ledger entries per product"
        actions={
          <>
            <CsvExportButton data={logs} filename={`stock_history_${activeProductId}`} />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => activeProductId && dispatch(fetchInventoryLogs(activeProductId))}
              disabled={loading || !activeProductId}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={() => activeProductId && dispatch(fetchInventoryLogs(activeProductId))} />}

      <div className="section-card" style={{ maxWidth: '520px' }}>
        <label className="form-label" style={{ marginBottom: '0.4rem', display: 'block' }}>
          Select Product
        </label>
        <SearchableSelect
          options={productOptions}
          value={activeProductId}
          onChange={(val) => {
            setSelectedProductId(String(val))
            setSearchParams(val ? { product_id: String(val) } : {})
          }}
          placeholder="Select product to inspect ledger..."
        />
      </div>

      <DataTable
        columns={columns}
        data={logs}
        keyField="id"
        defaultPageSize={15}
        loading={loading}
        emptyTitle="No movement entries"
        emptyMessage="No stock movements have been recorded for this product yet."
      />
    </div>
  )
}
