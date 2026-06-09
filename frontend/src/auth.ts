export const AUTH_TOKEN_KEY = "aicost_auth_token";
export const TRIAL_STORAGE_KEY = "aicost_trial";
export const ACTIVATE_EVENT = "aicost:activate";
export const AUTH_CHANGED_EVENT = "aicost:auth-changed";

export interface TrialInfo {
  active: boolean;
  trial_days: number;
  remaining_days: number;
  started_at: string;
  ends_at: string;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  user_id: number;
  username: string;
  role: string;
  display_name: string;
  trial: TrialInfo;
}

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getStoredTrial(): TrialInfo | null {
  const raw = localStorage.getItem(TRIAL_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as TrialInfo;
  } catch {
    return null;
  }
}

export function hasActiveTrial(): boolean {
  const token = getAuthToken();
  const trial = getStoredTrial();
  if (!token || !trial?.active) return false;
  return new Date(trial.ends_at).getTime() > Date.now();
}

export function saveAuthSession(session: AuthSession): void {
  localStorage.setItem(AUTH_TOKEN_KEY, session.access_token);
  localStorage.setItem(TRIAL_STORAGE_KEY, JSON.stringify(session.trial));
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

export function clearAuthSession(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(TRIAL_STORAGE_KEY);
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

export function requestActivation(days: 7 | 14 = 14): void {
  window.dispatchEvent(new CustomEvent(ACTIVATE_EVENT, { detail: { days } }));
}
