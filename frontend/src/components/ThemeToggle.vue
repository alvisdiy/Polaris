<script setup lang="ts">
import type { Theme } from '../stores/theme'

defineProps<{ theme: Theme }>()
defineEmits<{ (e: 'toggle'): void }>()
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :aria-label="theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'"
    :title="theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'"
    @click="$emit('toggle')"
  >
    <svg
      v-if="theme === 'light'"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M20 12.5A8.5 8.5 0 0 1 11.5 4a7 7 0 1 0 8.5 8.5Z"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <circle cx="18.5" cy="5.5" r="1" fill="currentColor" />
    </svg>
    <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.5" />
      <path
        d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6l1.4 1.4m10 10 1.4 1.4m0-12.8-1.4 1.4m-10 10L5.6 18.4"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
      />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-ink);
  transition: border-color var(--motion-fast), color var(--motion-fast);
}

.theme-toggle:hover {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
</style>
