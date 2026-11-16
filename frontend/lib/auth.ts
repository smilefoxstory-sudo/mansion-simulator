export const STORAGE_KEY = "access_token";
export const USER_KEY = "login_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(STORAGE_KEY);
}

export function clearAuth() {
  sessionStorage.removeItem(STORAGE_KEY);
  sessionStorage.removeItem(USER_KEY);
}