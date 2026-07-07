/**
 * CSRF-token read, shared by every module that POSTs to the Django API.
 * Prefers the `csrftoken` cookie, falls back to a rendered
 * `csrfmiddlewaretoken` hidden input.
 */
export function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);
  const element = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  if (element) return element.value;
  console.warn("csrf: token not found — authenticated POSTs will 403");
  return "";
}
