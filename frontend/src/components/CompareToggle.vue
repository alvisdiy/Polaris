<script setup lang="ts">
import { computed, ref } from 'vue'
import { COMPARE_MAX, useCompare } from '../stores/compare'

const props = defineProps<{ scholarshipId: string }>()

const { has, toggle, isFull } = useCompare()

const selected = computed(() => has(props.scholarshipId))
const showFullNotice = ref(false)

function onChange(event: Event) {
  const checkbox = event.target as HTMLInputElement
  if (checkbox.checked && isFull() && !selected.value) {
    checkbox.checked = false
    showFullNotice.value = true
    setTimeout(() => {
      showFullNotice.value = false
    }, 2500)
    return
  }
  toggle(props.scholarshipId)
}
</script>

<template>
  <span class="compare-toggle">
    <label class="compare-label">
      <input
        type="checkbox"
        class="compare-checkbox"
        :checked="selected"
        @change="onChange"
      />
      <span class="compare-text">Compare</span>
    </label>
    <span v-if="showFullNotice" class="full-notice" role="status">
      You can compare up to {{ COMPARE_MAX }} scholarships
    </span>
  </span>
</template>

<style scoped>
.compare-toggle {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.compare-label {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-height: 42px;
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.compare-checkbox {
  width: 15px;
  height: 15px;
  accent-color: var(--color-brand);
  cursor: pointer;
}

.full-notice {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--color-sem-unknown);
  white-space: nowrap;
}
</style>
