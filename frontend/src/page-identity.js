/** @file page-identity.js @description Page lease identifiers for HTTPS and intranet HTTP. */
export function createPageIdentity(cryptoProvider = window.crypto) {
  // randomUUID requires a secure context; getRandomValues also works on intranet HTTP.
  // This identifies a page lease only. Authentication uses server-issued sessions.
  const bytes = new Uint8Array(16);
  cryptoProvider.getRandomValues(bytes);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}
