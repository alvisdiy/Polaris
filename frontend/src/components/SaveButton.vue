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
        d="M12 2.5c.7 4.2 1.7 6 2.6 6.9.9.9 2.7 1.9 6.9 2.6v1c-4.2.7-6 1.7-6.9 2.6-.9.9-1.9 2.7-2.6 6.9h-1c-.7-4.2-1.7-6-2.6-6.9-.9-.9-2.7-1.9-6.9-2.6v-1c4.2-.7 6-1.7 6.9-2.6.9-.9 1.9-2.7 2.6-6.9Z"
        stroke="currentColor"
        stroke-width="1.4"
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
  color: var(--color-ink-secondary);
  transition: border-color var(--motion-fast), color var(--motion-fast),
    background var(--motion-fast), transform var(--motion-fast);
}

.save-button:hover {
  border-color: var(--color-star);
  color: var(--color-star);
  transform: translateY(-1px);
}

.save-button:active {
  transform: scale(0.94);
}

/* A saved item is the user's own star: gold, the only place gold appears
   outside the wordmark. */
.save-button.saved {
  border-color: var(--color-star);
  background: var(--color-star-soft);
  color: var(--color-star);
}
</style>
