<script setup lang="ts">
defineProps<{
  label: string
  value: string
}>()
defineEmits<{ (e: 'remove'): void }>()
</script>

<template>
  <span class="chip">
    <span class="chip-label">{{ label }}:</span>
    <span class="chip-value">{{ value }}</span>
    <button
      type="button"
      class="chip-remove"
      :aria-label="`Remove ${label} filter`"
      @click="$emit('remove')"
    >
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="m2.5 2.5 7 7m0-7-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>
    </button>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.4rem 0.25rem 0.5rem;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-pill);
  background: var(--color-surface-raised);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
}

.chip-label {
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.chip-value {
  font-weight: 500;
  color: var(--color-ink);
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-control);
  background: none;
  color: var(--color-ink-secondary);
}

.chip-remove:hover {
  color: var(--color-brand);
  background: var(--color-brand-soft);
}
</style>
