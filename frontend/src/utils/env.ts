const CASE_PORTAL_PATH = '/case';

/**
 * External case portal URL.
 * Priority: VITE_CASE_PORTAL_URL (build-time) > current origin + /case (runtime).
 */
export function getCasePortalUrl(): string {
  const override = import.meta.env.VITE_CASE_PORTAL_URL;
  if (typeof override === 'string' && override.trim()) {
    return override.trim();
  }

  if (typeof window !== 'undefined') {
    return `${window.location.origin}${CASE_PORTAL_PATH}`;
  }

  return '';
}
