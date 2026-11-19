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
  height: 0.8rem;
  border-radius: 1px;
  background: linear-gradient(
    90deg,
    var(--color-line) 0%,
    var(--color-surface-raised) 40%,
    var(--color-line) 80%
  );
  background-size: 300% 100%;
  animation: sweep 1.4s ease-in-out infinite;
}

@keyframes sweep {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: 0 0;
  }
}
</style>
