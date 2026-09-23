export function loginDestination(search: string) {
  const next = new URLSearchParams(search).get('next') ?? '/runs';
  return /^\/runs(?:\/|\?|$)|^\/methodology(?:\?|$)/.test(next) ? next : '/runs';
}
