<script setup lang="ts">
const model = defineModel<string>({ default: '' })
defineEmits<{ (e: 'submit'): void }>()
</script>

<template>
  <form class="global-search" role="search" @submit.prevent="$emit('submit')">
    <label class="visually-hidden" for="global-search-input">Search scholarships</label>
    <input
      id="global-search-input"
      v-model="model"
      type="search"
      class="search-input"
      placeholder="Search scholarships"
      @keydown.enter="$emit('submit')"
    />
  </form>
</template>

<style scoped>
.global-search {
  display: inline-flex;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.search-input {
  width: 13rem;
  min-height: 38px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface-raised);
  color: var(--color-ink);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0.04em;
  transition: border-color var(--motion-fast), box-shadow var(--motion-fast);
}

.search-input::placeholder {
  color: var(--color-ink-secondary);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  font-size: 0.7rem;
}

.search-input:focus-visible {
  border-color: var(--color-brand);
  outline: none;
  box-shadow: 0 0 0 3px var(--color-brand-soft);
}

@media (max-width: 720px) {
  .global-search {
    display: none;
  }
}
</style>
