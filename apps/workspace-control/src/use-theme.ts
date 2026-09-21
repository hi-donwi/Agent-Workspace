import { useEffect, useState } from 'react';
export type ThemePreference = 'light' | 'dark' | 'system';
const key = 'workspace-control-theme';
export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(() => {
    try { const value = localStorage.getItem(key); return value === 'light' || value === 'dark' ? value : 'system'; }
    catch { return 'system'; }
  });
  const [dark, setDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches);
  const [warning, setWarning] = useState('');
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      const isDark = preference === 'system' ? media.matches : preference === 'dark';
      document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
      document.documentElement.classList.toggle('dark', isDark);
      document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
      setDark(isDark);
    };
    apply(); media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [preference]);
  function changeTheme(value: ThemePreference) {
    setPreference(value);
    try { localStorage.setItem(key, value); setWarning(''); }
    catch { setWarning('The theme will apply for this visit. Browser storage is unavailable.'); }
  }
  return { preference, dark, changeTheme, warning };
}
