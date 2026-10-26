'use client';

import { HarnessClient } from './client';

/**
 * The one client the renderer uses for task work.
 *
 * In the desktop app the address and token come from Electron; in a browser
 * during development the backend listens on its default local port. The token
 * travels in `Authorization` only, and no provider key is ever part of this
 * object.
 */
export function createBrowserClient(): HarnessClient {
  const target =
    typeof window !== 'undefined' && window.desktop?.api
      ? window.desktop.api
      : { url: 'http://127.0.0.1:8765', token: '' };
  return new HarnessClient({ baseUrl: target.url, token: target.token });
}
