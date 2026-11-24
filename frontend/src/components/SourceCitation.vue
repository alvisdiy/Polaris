<script setup lang="ts">
import { computed } from 'vue'
import { hostOf } from '../lib/format'

const props = defineProps<{ url: string }>()

const host = computed(() => hostOf(props.url))
</script>

<template>
  <p class="citation">
    <span class="source-label">Source:</span>
    <a :href="url" target="_blank" rel="noopener noreferrer" class="source-link">
      {{ host ?? url }}
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true" class="icon">
        <path
          d="M14 5h5v5M19 5l-8 8M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </a>
  </p>
</template>

<style scoped>
.citation {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0;
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-line);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.source-label {
  flex-shrink: 0;
}

.source-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  color: var(--color-ink-secondary);
  text-decoration: none;
  text-transform: none;
  letter-spacing: 0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-link:hover {
  color: var(--color-brand);
  text-decoration: underline;
}

.icon {
  flex-shrink: 0;
}
</style>
