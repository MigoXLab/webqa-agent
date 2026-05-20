const CASE_PORTAL_URLS = {
  staging: 'https://webqa.staging.openxlab.org.cn/case',
  prod: 'https://webqa.openxlab.org.cn/case',
} as const;

function isStagingHost(hostname: string): boolean {
  return (
    hostname.includes('staging') ||
    hostname === 'localhost' ||
    hostname === '127.0.0.1'
  );
}

/** External case portal URL (independent webqa case service). */
export function getCasePortalUrl(): string {
  const override = import.meta.env.VITE_CASE_PORTAL_URL;
  if (typeof override === 'string' && override.trim()) {
    return override.trim();
  }

  const hostname =
    typeof window !== 'undefined' ? window.location.hostname : '';
  return isStagingHost(hostname)
    ? CASE_PORTAL_URLS.staging
    : CASE_PORTAL_URLS.prod;
}
