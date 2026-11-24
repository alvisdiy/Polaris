<script setup lang="ts">
defineProps<{
  score: number
  category: string
}>()
</script>

<template>
  <span class="score-badge">
    <span class="score">{{ score }}<span class="max">/100</span></span>
    <span class="category">{{ category }}</span>
  </span>
</template>

<style scoped>
.score-badge {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.15rem;
}

.score {
  font-family: var(--font-display);
  font-size: 1.8rem;
  font-weight: 400;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--color-ink);
}

.max {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--color-ink-secondary);
}

.category {
  font-family: var(--font-mono);
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-brand);
}
</style>
