import { ref, watchEffect } from 'vue'

/*
 * Theme store: light is the default; an OS dark preference is honoured until the
 * user makes an explicit choice, which then persists in localStorage. Both
 * themes are fully tokenized (web-design.md section 23).
 *
 * index.html runs the same choice inline before first paint, so a dark-theme
 * reader never sees a cream flash while this module loads.
 */

const STORAGE_KEY = 'polaris.theme'

export type Theme = 'light' | 'dark'

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'dark' || value === 'light' ? value : null
  } catch {
    return null
  }
}

function systemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(storedTheme() ?? systemTheme())

watchEffect(() => {
  document.documentElement.dataset.theme = theme.value
})

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
    try {
      localStorage.setItem(STORAGE_KEY, theme.value)
    } catch {
      // Storage unavailable (private mode): the choice still applies this session.
    }
  }
  return { theme, toggle }
}
