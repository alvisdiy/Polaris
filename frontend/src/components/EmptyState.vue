<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state">
    <svg class="glyph" width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.5c.7 4.2 1.7 6 2.6 6.9.9.9 2.7 1.9 6.9 2.6v1c-4.2.7-6 1.7-6.9 2.6-.9.9-1.9 2.7-2.6 6.9h-1c-.7-4.2-1.7-6-2.6-6.9-.9-.9-2.7-1.9-6.9-2.6v-1c4.2-.7 6-1.7 6.9-2.6.9-.9 1.9-2.7 2.6-6.9Z"
        stroke="currentColor"
        stroke-width="1.2"
        stroke-linejoin="round"
      />
    </svg>
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
  background:
    radial-gradient(420px 180px at 50% 0%, var(--color-brand-soft), transparent 70%),
    var(--color-surface);
}

.glyph {
  color: var(--color-star);
  margin-bottom: var(--space-2);
}

.title {
  font-family: var(--font-display);
  font-size: 1.6rem;
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
