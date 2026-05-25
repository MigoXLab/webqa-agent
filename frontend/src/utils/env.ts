/** External case portal URL, configured via VITE_CASE_PORTAL_URL build-time env var. */
export function getCasePortalUrl(): string {
  const url = import.meta.env.VITE_CASE_PORTAL_URL;
  return typeof url === 'string' ? url.trim() : '';
}
