import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSelector, useDispatch } from 'react-redux'
import { RefreshCw, History, SlidersHorizontal } from 'lucide-react'
import {
  fetchInventoryPositions,
  selectInventoryPositions,
  selectInventoryPositionsLoading,
} from '../store/inventorySlice'
import PageHeader from '../components/common/PageHeader'
import DataTable from '../components/common/DataTable'
import CsvExportButton from '../components/common/CsvExportButton'
import Badge from '../components/Badge'
import { ErrorState } from '../components/common/StateBlocks'

export default function StockManagementPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const positions = useSelector(selectInventoryPositions)
  const loading = useSelector(selectInventoryPositionsLoading)
  const error = useSelector((state) => state.inventory.error)

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')

  useEffect(() => {
    dispatch(fetchInventoryPositions())
  }, [dispatch])

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase().trim()
    return positions.filter((item) => {
      const matchSearch =
        !q ||
        item.name.toLowerCase().includes(q) ||
        item.sku.toLowerCase().includes(q)
      let matchStatus = true
      if (statusFilter === 'OUT') matchStatus = item.on_hand_stock === 0
      else if (statusFilter === 'LOW') matchStatus = item.on_hand_stock > 0 && item.on_hand_stock <= item.reorder_level
      else if (statusFilter === 'INCOMING') matchStatus = item.incoming_stock > 0
      return matchSearch && matchStatus
    })
  }, [positions, searchQuery, statusFilter])

  const columns = useMemo(
    () => [
      {
        key: 'sku',
        label: 'SKU',
        sortable: true,
        render: (r) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{r.sku}</span>,
      },
      { key: 'name', label: 'Product', sortable: true },
      {
        key: 'on_hand_stock',
        label: 'On Hand',
        numeric: true,
        sortable: true,
        render: (r) => <span style={{ fontWeight: 700 }}>{r.on_hand_stock}</span>,
      },
      {
        key: 'available_stock',
        label: 'Available',
        numeric: true,
        sortable: true,
      },
      {
        key: 'incoming_stock',
        label: 'Incoming (POs)',
        numeric: true,
        sortable: true,
        render: (r) => (
          <span style={{ color: r.incoming_stock > 0 ? 'var(--erp-brand)' : 'var(--erp-text-muted)', fontWeight: 600 }}>
            {r.incoming_stock}
          </span>
        ),
      },
      {
        key: 'inventory_position',
        label: 'Inv. Position',
        numeric: true,
        sortable: true,
        render: (r) => <span style={{ fontWeight: 700 }}>{r.inventory_position}</span>,
      },
      {
        key: 'reorder_level',
        label: 'Reorder At',
        numeric: true,
        sortable: true,
      },
      {
        key: 'inventory_value',
        label: 'Stock Value',
        numeric: true,
        sortable: true,
        render: (r) => `₹${Number(r.inventory_value || 0).toFixed(2)}`,
      },
      {
        key: 'status',
        label: 'Status',
        center: true,
        render: (r) =>
          r.on_hand_stock === 0 ? (
            <Badge status="OUT OF STOCK" />
          ) : r.on_hand_stock <= r.reorder_level ? (
            <Badge status="LOW STOCK" />
          ) : (
            <Badge status="HEALTHY" label="Healthy" />
          ),
      },
      {
        key: 'actions',
        label: 'Actions',
        center: true,
        sortable: false,
        render: (r) => (
          <div className="actions-group">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => navigate(`/inventory/adjustments?product_id=${r.product_id}`)}
            >
              <SlidersHorizontal size={13} />
              <span>Adjust</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => navigate(`/inventory/history?product_id=${r.product_id}`)}
            >
              <History size={13} />
              <span>Ledger</span>
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
        title="Stock Management"
        subtitle="Real-time inventory positions (On-Hand + Incoming POs). Reservations are not yet enabled."
        actions={
          <>
            <CsvExportButton data={filtered} filename="inventory_positions" />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => dispatch(fetchInventoryPositions())}
              disabled={loading}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => navigate('/inventory/adjustments')}
            >
              <SlidersHorizontal size={14} />
              <span>Adjust Stock</span>
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={() => dispatch(fetchInventoryPositions())} />}

      <div className="section-card" style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="form-control"
          style={{ flex: '1 1 240px', maxWidth: '360px' }}
          placeholder="Search SKU or product name..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select
          className="form-control"
          style={{ width: '180px' }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="ALL">All Statuses</option>
          <option value="LOW">Low Stock</option>
          <option value="OUT">Out of Stock</option>
          <option value="INCOMING">Has Incoming PO</option>
        </select>
      </div>

      <DataTable
        columns={columns}
        data={filtered}
        keyField="product_id"
        defaultPageSize={10}
        loading={loading}
        emptyTitle="No inventory records"
        emptyMessage="Add products to start tracking stock positions."
      />
    </div>
  )
}
