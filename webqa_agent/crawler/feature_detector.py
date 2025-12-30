"""Lightweight page feature detection for WebQA Agent.

This module provides utilities to detect page characteristics that guide LLM
tool selection during test planning.
"""

import logging
from typing import List

from playwright.async_api import Page


async def detect_page_features(page: Page) -> List[str]:
    """Lightweight page feature detection to guide LLM tool selection.

    This function performs simple page analysis without heavy computation:
    - Detects API calls (fetch/XMLHttpRequest)
    - Detects forms
    - Detects database usage (IndexedDB, localStorage)
    - Detects SPA frameworks (React, Vue, Angular)
    - Detects DOM mutation capabilities (MutationObserver)
    - Detects lazy loading patterns (IntersectionObserver, lazy images)

    Args:
        page: Playwright Page object

    Returns:
        List of detected feature strings (e.g., 'API calls detected', 'Forms detected')
    """
    features = []

    try:
        # Detect API calls from network requests
        network_requests = await page.evaluate('''() => {
            try {
                const resources = window.performance.getEntriesByType('resource');
                const apiRequests = resources.filter(r =>
                    r.initiatorType === 'fetch' ||
                    r.initiatorType === 'xmlhttprequest'
                );
                return apiRequests.map(r => r.name);
            } catch (e) {
                return [];
            }
        }''')

        if network_requests and len(network_requests) > 0:
            # Extract unique API endpoints
            unique_endpoints = set()
            for url in network_requests:
                # Simple endpoint extraction (e.g., /api/users, /graphql)
                if '/api/' in url or '/graphql' in url or url.endswith('.json'):
                    unique_endpoints.add(url)

            if unique_endpoints:
                features.append(f'API calls detected ({len(unique_endpoints)} endpoints)')
                logging.debug(f'Feature Detection: Found {len(unique_endpoints)} API endpoints: {list(unique_endpoints)[:3]}...')

    except Exception as e:
        logging.debug(f'Feature Detection: API detection failed: {e}')

    try:
        # Detect forms on the page
        forms = await page.query_selector_all('form')
        if forms and len(forms) > 0:
            features.append(f'Forms detected ({len(forms)} forms)')
            logging.debug(f'Feature Detection: Found {len(forms)} forms')
    except Exception as e:
        logging.debug(f'Feature Detection: Form detection failed: {e}')

    try:
        # Detect database usage (IndexedDB, localStorage)
        has_database = await page.evaluate('''() => {
            try {
                // Check IndexedDB
                const hasIndexedDB = 'indexedDB' in window &&
                    window.indexedDB !== null;

                // Check localStorage usage
                const hasLocalStorage = 'localStorage' in window &&
                    window.localStorage.length > 0;

                // Check sessionStorage usage
                const hasSessionStorage = 'sessionStorage' in window &&
                    window.sessionStorage.length > 0;

                return {
                    indexedDB: hasIndexedDB,
                    localStorage: hasLocalStorage,
                    sessionStorage: hasSessionStorage
                };
            } catch (e) {
                return {indexedDB: false, localStorage: false, sessionStorage: false};
            }
        }''')

        db_features = []
        if has_database.get('indexedDB'):
            db_features.append('IndexedDB')
        if has_database.get('localStorage'):
            db_features.append('localStorage')
        if has_database.get('sessionStorage'):
            db_features.append('sessionStorage')

        if db_features:
            features.append(f'Database usage detected ({", ".join(db_features)})')
            logging.debug(f'Feature Detection: Found database features: {db_features}')

    except Exception as e:
        logging.debug(f'Feature Detection: Database detection failed: {e}')

    try:
        # Detect SPA frameworks (React, Vue, Angular)
        spa_frameworks = await page.evaluate('''() => {
            try {
                const frameworks = [];

                // React detection
                if (window.React || window.ReactDOM ||
                    document.querySelector('[data-reactroot]') ||
                    document.querySelector('[data-reactid]')) {
                    frameworks.push('React');
                }

                // Vue detection
                if (window.Vue || document.querySelector('[data-v-]')) {
                    frameworks.push('Vue');
                }

                // Angular detection
                if (window.angular || document.querySelector('[ng-app]') ||
                    document.querySelector('[ng-version]')) {
                    frameworks.push('Angular');
                }

                return frameworks;
            } catch (e) {
                return [];
            }
        }''')

        if spa_frameworks and len(spa_frameworks) > 0:
            features.append(f'SPA framework detected ({", ".join(spa_frameworks)})')
            logging.debug(f'Feature Detection: Found SPA frameworks: {spa_frameworks}')

    except Exception as e:
        logging.debug(f'Feature Detection: SPA framework detection failed: {e}')

    try:
        # Detect DOM mutation capabilities (MutationObserver)
        has_mutation_observer = await page.evaluate('''() => {
            try {
                return 'MutationObserver' in window;
            } catch (e) {
                return false;
            }
        }''')

        if has_mutation_observer:
            features.append('DOM mutation capability detected (MutationObserver)')
            logging.debug('Feature Detection: MutationObserver API available')

    except Exception as e:
        logging.debug(f'Feature Detection: MutationObserver detection failed: {e}')

    try:
        # Detect lazy loading patterns
        lazy_loading_info = await page.evaluate('''() => {
            try {
                const info = [];

                // IntersectionObserver (modern lazy loading)
                if ('IntersectionObserver' in window) {
                    info.push('IntersectionObserver');
                }

                // Image lazy loading attribute
                const lazyImages = document.querySelectorAll('img[loading="lazy"]');
                if (lazyImages.length > 0) {
                    info.push(`${lazyImages.length} lazy images`);
                }

                // Lazy loading libraries (data-src pattern)
                const dataSrcImages = document.querySelectorAll('img[data-src]');
                if (dataSrcImages.length > 0) {
                    info.push(`${dataSrcImages.length} lazy-load candidates`);
                }

                return info;
            } catch (e) {
                return [];
            }
        }''')

        if lazy_loading_info and len(lazy_loading_info) > 0:
            features.append(f'Lazy loading detected ({", ".join(lazy_loading_info)})')
            logging.debug(f'Feature Detection: Found lazy loading patterns: {lazy_loading_info}')

    except Exception as e:
        logging.debug(f'Feature Detection: Lazy loading detection failed: {e}')

    return features
