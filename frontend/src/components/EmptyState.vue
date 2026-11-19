<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <h2 class="title">{{ title }}</h2>
    <p v-if="description" class="description">{{ description }}</p>
    <div v-if="$slots.default" class="actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  padding: var(--space-7) var(--space-5);
  text-align: center;
  border: 1px dashed var(--color-line-strong);
  border-radius: var(--radius-card);
  background: var(--color-surface);
}

.title {
  font-family: var(--font-display);
  font-size: 1.4rem;
  margin-bottom: var(--space-2);
}

.description {
  max-width: 40ch;
  margin: 0 auto;
  color: var(--color-ink-secondary);
  font-size: var(--font-size-sm);
}

.actions {
  margin-top: var(--space-5);
  display: flex;
  gap: var(--space-3);
  justify-content: center;
  flex-wrap: wrap;
}
</style>
