import { ref, watchEffect } from 'vue'

/*
 * Theme store: light is the default; the user's explicit choice persists in
 * localStorage. Both themes are fully tokenized (web-design.md section 23).
 */

const STORAGE_KEY = 'polaris.theme'

export type Theme = 'light' | 'dark'

const stored = localStorage.getItem(STORAGE_KEY)
const theme = ref<Theme>(stored === 'dark' || stored === 'light' ? stored : 'light')

watchEffect(() => {
  document.documentElement.dataset.theme = theme.value
})

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
  }
  return { theme, toggle }
}
