<script setup lang="ts">
import { computed } from 'vue'
import { deadlineDisplay } from '../lib/format'
import type { DeadlineState } from '../api/types'

const props = defineProps<{ deadline: string | null }>()

const display = computed(() => deadlineDisplay(props.deadline))

const iconPath: Record<DeadlineState, string> = {
  active: 'M12 7v5l3 2M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Z',
  rolling: 'M4 12a8 8 0 0 1 13.6-5.7M20 12a8 8 0 0 1-13.6 5.7M17.6 3v3.5h-3.5M6.4 21v-3.5h3.5',
  unknown: 'M12 17.2v.2M9.5 9a2.6 2.6 0 1 1 3.9 2.3c-.9.5-1.4 1-1.4 2M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Z',
  expired: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18ZM12 7v5l3 2M4 4l16 16',
  legacy: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Z',
}

const colorVar: Record<DeadlineState, string> = {
  active: 'var(--color-sem-active)',
  rolling: 'var(--color-sem-rolling)',
  unknown: 'var(--color-sem-unknown)',
  expired: 'var(--color-sem-expired)',
  legacy: 'var(--color-sem-legacy)',
}

const color = computed(() => colorVar[display.value.state])
</script>

<template>
  <span class="deadline-badge" :style="{ color }">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        :d="iconPath[display.state]"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
    <span class="label">{{ display.label }}</span>
    <span v-if="display.date" class="date">{{ display.date }}</span>
  </span>
</template>

<style scoped>
.deadline-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 500;
}

.date {
  color: var(--color-ink);
  text-transform: none;
  letter-spacing: 0.02em;
}
</style>
