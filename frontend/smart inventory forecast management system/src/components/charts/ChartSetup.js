import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  RadialLinearScale,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  RadialLinearScale,
  Title,
  Tooltip,
  Legend,
  Filler
)

export const getChartTheme = (isDark = false) => {
  return {
    textColor: isDark ? '#9ca3af' : '#64748b',
    textMainColor: isDark ? '#f9fafb' : '#0f172a',
    gridColor: isDark ? 'rgba(255, 255, 255, 0.07)' : 'rgba(0, 0, 0, 0.05)',
    tooltipBg: isDark ? '#111827' : '#0f172a',
    tooltipBorder: isDark ? '#374151' : '#334155',
    tooltipTitleColor: '#ffffff',
    tooltipBodyColor: '#f1f5f9',
    palette: [
      '#8b5cf6', // purple
      '#10b981', // emerald
      '#3b82f6', // blue
      '#f59e0b', // amber
      '#ec4899', // pink
      '#06b6d4', // cyan
      '#f97316', // orange
    ],
  }
}
