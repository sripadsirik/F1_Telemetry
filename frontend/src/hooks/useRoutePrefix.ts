import { useLocation } from 'react-router-dom'

const LEGACY_PREFIX = '/legacy'

function normalizePath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`
}

export function useRoutePrefix() {
  const { pathname } = useLocation()
  const isLegacyRoute = pathname === LEGACY_PREFIX || pathname.startsWith(`${LEGACY_PREFIX}/`)

  const withPrefix = (path: string): string => {
    const normalized = normalizePath(path)

    if (normalized === LEGACY_PREFIX || normalized.startsWith(`${LEGACY_PREFIX}/`)) {
      return normalized
    }

    if (!isLegacyRoute) {
      return normalized
    }

    if (normalized === '/') {
      return LEGACY_PREFIX
    }

    return `${LEGACY_PREFIX}${normalized}`
  }

  return { isLegacyRoute, withPrefix }
}
