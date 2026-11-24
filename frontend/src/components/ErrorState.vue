<script setup lang="ts">
defineProps<{
  title?: string
  message: string
}>()
defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div class="error-state" role="alert">
    <h2 class="title">{{ title ?? 'Something went wrong' }}</h2>
    <p class="message">{{ message }}</p>
    <button type="button" class="retry-button" @click="$emit('retry')">Try again</button>
  </div>
</template>

<style scoped>
.error-state {
  padding: var(--space-5);
  border: 1px solid var(--color-line-strong);
  border-left: 3px solid var(--color-feedback-error);
  border-radius: var(--radius-card);
  background: var(--color-surface);
}

.title {
  font-family: var(--font-display);
  font-size: 1.35rem;
  margin: 0 0 var(--space-2);
}

.message {
  margin: 0 0 var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

.retry-button {
  min-height: 40px;
  padding: 0 var(--space-4);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  transition: border-color var(--motion-fast), color var(--motion-fast);
}

.retry-button:hover {
  border-color: var(--color-feedback-error);
  color: var(--color-feedback-error);
}
</style>
