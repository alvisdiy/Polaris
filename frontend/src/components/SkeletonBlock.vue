<script setup lang="ts">
withDefaults(
  defineProps<{
    lines?: number
    height?: string
  }>(),
  { lines: 3, height: '1rem' },
)
</script>

<template>
  <div class="skeleton" aria-hidden="true">
    <div
      v-for="line in lines"
      :key="line"
      class="skeleton-line"
      :style="{ height, width: line === lines ? '62%' : '100%' }"
    />
  </div>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-card);
  background: var(--color-surface);
}

.skeleton-line {
  position: relative;
  height: 0.8rem;
  border-radius: 4px;
  overflow: hidden;
  background: var(--color-line);
}

.skeleton-line::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(
    90deg,
    transparent 0%,
    var(--color-surface-raised) 50%,
    transparent 100%
  );
  animation: sweep 1.4s ease-in-out infinite;
}

@keyframes sweep {
  100% {
    transform: translateX(100%);
  }
}
</style>
