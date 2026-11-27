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

export const DEFAULT_CHART_FONT_FAMILY =
  "'Inter', 'Noto Sans Devanagari', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

export const syncChartTypography = () => {
  const rootFont =
    typeof window !== 'undefined' && typeof document !== 'undefined'
      ? window.getComputedStyle(document.documentElement).fontFamily
      : ''
  ChartJS.defaults.font.family = rootFont && rootFont.trim() ? rootFont : DEFAULT_CHART_FONT_FAMILY
  ChartJS.defaults.font.size = 12
  ChartJS.defaults.font.weight = '500'
  ChartJS.defaults.font.lineHeight = 1.4
  return ChartJS.defaults.font.family
}

syncChartTypography()

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
