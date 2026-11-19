<script setup lang="ts">
import { computed } from 'vue'
import { useShortlist } from '../stores/shortlist'

const props = defineProps<{ scholarshipId: string }>()

const { has, toggle } = useShortlist()

const saved = computed(() => has(props.scholarshipId))

function onClick() {
  const nowSaved = toggle(props.scholarshipId)
  // Announce the change for screen readers via the button label below.
  void nowSaved
}
</script>

<template>
  <button
    type="button"
    class="save-button"
    :class="{ saved }"
    :aria-pressed="saved"
    :aria-label="saved ? 'Remove from saved' : 'Save scholarship'"
    :title="saved ? 'Remove from saved' : 'Save scholarship'"
    @click="onClick"
  >
    <svg width="16" height="16" viewBox="0 0 24 24" :fill="saved ? 'currentColor' : 'none'" aria-hidden="true">
      <path
        d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
    </svg>
  </button>
</template>

<style scoped>
.save-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-ink);
  transition: border-color var(--motion-fast), color var(--motion-fast),
    background var(--motion-fast);
}

.save-button:hover {
  border-color: var(--color-ink);
}

.save-button.saved {
  border-color: var(--color-brand);
  background: var(--color-brand-soft);
  color: var(--color-brand-ink);
}
</style>
