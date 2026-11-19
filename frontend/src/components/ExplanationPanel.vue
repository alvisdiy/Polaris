<script setup lang="ts">
import type { Recommendation } from '../api/types'
import { hostOf } from '../lib/format'

defineProps<{ recommendation: Recommendation }>()

function urlHost(item: string): string | null {
  const match = item.match(/https?:\/\/[^\s)]+/)
  return match ? hostOf(match[0]) : null
}

function urlOf(item: string): string | null {
  const match = item.match(/https?:\/\/[^\s)]+/)
  return match ? match[0] : null
}
</script>

<template>
  <div class="explanation-panel">
    <p class="summary">{{ recommendation.explanation }}</p>

    <div class="columns">
      <section aria-labelledby="strengths-heading">
        <h3 id="strengths-heading" class="heading heading-strengths">Strengths</h3>
        <ul class="list">
          <li v-for="item in recommendation.strengths" :key="item" class="item item-strength">
            {{ item }}
          </li>
        </ul>
      </section>

      <section aria-labelledby="gaps-heading">
        <h3 id="gaps-heading" class="heading heading-gaps">Gaps</h3>
        <ul class="list">
          <li v-for="item in recommendation.gaps" :key="item" class="item item-gap">
            {{ item }}
          </li>
          <li v-if="recommendation.gaps.length === 0" class="item item-none">
            No gaps identified for your profile.
          </li>
        </ul>
      </section>
    </div>

    <section aria-labelledby="steps-heading">
      <h3 id="steps-heading" class="heading">Suggested next steps</h3>
      <ol class="steps">
        <li v-for="(item, index) in recommendation.next_steps" :key="index" class="step">
          <template v-if="urlOf(item)">
            {{ item.replace(/https?:\/\/[^\s)]+/, '').trim() }}
            <a :href="urlOf(item) ?? '#'" target="_blank" rel="noopener noreferrer">
              {{ urlHost(item) }}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M14 5h5v5M19 5l-8 8M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </a>
          </template>
          <template v-else>{{ item }}</template>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.explanation-panel {
  margin-top: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-line);
  background: var(--color-surface-raised);
}

.summary {
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-3);
}

.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

.heading {
  font-family: var(--font-mono);
  font-size: 0.64rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-2);
}

.heading-strengths {
  color: var(--color-evidence);
}

.heading-gaps {
  color: var(--color-sem-unknown);
}

.list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.item {
  font-size: var(--font-size-sm);
  padding-left: 0.9rem;
  position: relative;
  color: var(--color-ink-secondary);
}

.item::before {
  position: absolute;
  left: 0;
  font-family: var(--font-mono);
}

.item-strength::before {
  content: '+';
  color: var(--color-evidence);
}

.item-gap::before {
  content: '−';
  color: var(--color-sem-unknown);
}

.item-none {
  font-style: italic;
}

.steps {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-line);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.step {
  font-size: var(--font-size-xs);
  color: var(--color-ink-secondary);
}

@media (max-width: 700px) {
  .columns {
    grid-template-columns: 1fr;
  }
}
</style>
