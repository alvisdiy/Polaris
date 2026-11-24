<script setup lang="ts">
import { computed } from 'vue'
import type { ScholarshipSummary, Recommendation } from '../api/types'
import DeadlineBadge from './DeadlineBadge.vue'
import SourceCitation from './SourceCitation.vue'
import SaveButton from './SaveButton.vue'
import CompareToggle from './CompareToggle.vue'

/** Common fields present on both list summaries and match results. */
interface CardItem {
  scholarship_id: string
  scholarship_name: string
  /** Null when the backend has no provider resolved for this record. */
  provider_name: string | null
  country: string | null
  deadline: string | null
  official_url: string
  field_of_study?: string[]
  degree?: string | null
  degree_levels?: string[]
  funding_type?: string | null
  match_score?: number
  recommendation_category?: string
  explanation?: string
}

const props = withDefaults(
  defineProps<{
    scholarship: CardItem
    variant?: 'browse' | 'match'
    rank?: number
  }>(),
  { variant: 'browse' },
)

const isMatch = computed(() => props.variant === 'match' && props.scholarship.match_score !== undefined)
const name = computed(() => props.scholarship.scholarship_name)
const deadline = computed(() => props.scholarship.deadline ?? null)

/*
 * Provider and country are nullable because the backend reports them as null
 * rather than inventing "Unknown". Rendering a placeholder here would push the
 * fabricated value straight back into the UI, so the line is omitted when
 * there is nothing true to show.
 */
/*
 * A scholarship whose page stated several levels has no single `degree`; the
 * levels live in `degree_levels`. Showing the set is the honest rendering, and
 * an empty value becomes "Level not stated" rather than a missing chip, because
 * a reader should be able to tell "not applicable" from "we did not record it".
 */
const degreeLabel = computed(() => {
  const levels = props.scholarship.degree_levels ?? []
  if (props.scholarship.degree) return props.scholarship.degree
  return levels.length ? levels.join(' · ') : null
})

const providerLine = computed(() => {
  const parts = [props.scholarship.provider_name, props.scholarship.country].filter(
    (part): part is string => Boolean(part),
  )
  return parts.length ? parts.join(' · ') : null
})

const categoryLabel: Record<string, string> = {
  'Excellent Match': 'Excellent match',
  'Strong Match': 'Strong match',
  'Good Match': 'Good match',
  'Moderate Match': 'Moderate match',
  'Low Match': 'Low match',
}
</script>

<template>
  <article class="card" :class="{ 'card-match': isMatch }">
    <div class="card-head">
      <span v-if="isMatch && rank" class="rank" aria-hidden="true">{{ rank }}</span>
      <div class="heading">
        <h3 class="name">
          <RouterLink
            :to="`/scholarships/${scholarship.scholarship_id}`"
            class="name-link"
          >
            {{ name }}
          </RouterLink>
        </h3>
        <p v-if="providerLine" class="provider">{{ providerLine }}</p>
      </div>
      <div v-if="isMatch" class="score">
        <span class="score-value">{{ scholarship.match_score }}<span class="score-max">/100</span></span>
        <span class="score-category">{{ (scholarship.recommendation_category && categoryLabel[scholarship.recommendation_category]) ?? scholarship.recommendation_category }}</span>
      </div>
    </div>

    <ul class="meta" aria-label="Key details">
      <li v-if="degreeLabel" class="meta-item">{{ degreeLabel }}</li>
      <li v-else class="meta-item meta-absent">Level not stated</li>
      <li v-if="scholarship.funding_type" class="meta-item">{{ scholarship.funding_type }}</li>
      <li v-for="field in (scholarship.field_of_study ?? []).slice(0, 2)" :key="field" class="meta-item">
        {{ field }}
      </li>
      <li v-if="(scholarship.field_of_study ?? []).length > 2" class="meta-item meta-more">
        +{{ (scholarship.field_of_study?.length ?? 0) - 2 }}
      </li>
    </ul>

    <DeadlineBadge :deadline="deadline" />

    <p v-if="isMatch" class="explanation">{{ scholarship.explanation }}</p>

    <div class="card-actions">
      <RouterLink
        :to="`/scholarships/${scholarship.scholarship_id}`"
        class="detail-link"
      >
        View details
      </RouterLink>
      <div class="card-tools">
        <SaveButton :scholarship-id="scholarship.scholarship_id" />
        <CompareToggle :scholarship-id="scholarship.scholarship_id" />
      </div>
    </div>

    <SourceCitation :url="scholarship.official_url" />
  </article>
</template>

<style scoped>
.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  transition: transform var(--motion-fast), box-shadow var(--motion-fast),
    border-color var(--motion-fast);
}

/* The card is a plotted position, not a tile: on hover the top edge lights up
   like a sight line. */
.card::before {
  content: '';
  position: absolute;
  inset: -1px -1px auto -1px;
  height: 2px;
  border-radius: var(--radius-card) var(--radius-card) 0 0;
  background: linear-gradient(90deg, var(--color-brand), transparent 72%);
  opacity: 0;
  transition: opacity var(--motion-fast);
}

.card:hover,
.card:focus-within {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--color-line-strong);
}

.card:hover::before,
.card:focus-within::before {
  opacity: 1;
}

.card-match::before {
  background: linear-gradient(90deg, var(--color-evidence), transparent 72%);
}

.card-head {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}

.rank {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: var(--tracking-meta);
  color: var(--color-brand);
  padding-top: 0.3rem;
}

.heading {
  min-width: 0;
}

.name {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.42rem;
  font-weight: 400;
  line-height: 1.15;
  letter-spacing: -0.01em;
}

.name-link {
  color: var(--color-ink);
  text-decoration: none;
}

.name-link:hover {
  color: var(--color-brand);
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 4px;
}

.provider {
  margin: 0.35rem 0 0;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.score {
  margin-left: auto;
  text-align: right;
  flex-shrink: 0;
}

.score-value {
  font-family: var(--font-display);
  font-size: 2.1rem;
  font-weight: 400;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--color-ink);
}

.score-max {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--color-ink-secondary);
}

.score-category {
  display: block;
  margin-top: 0.3rem;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-brand);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.meta-item {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--color-line);
  background: var(--color-surface-raised);
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-meta);
  color: var(--color-ink-secondary);
}

.meta-more {
  border-style: dashed;
}

.meta-absent {
  border-style: dashed;
  color: var(--color-sem-unknown);
}

.explanation {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-line);
}

.detail-link {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink);
  text-decoration: none;
}

.detail-link::after {
  content: ' →';
  color: var(--color-brand);
  transition: transform var(--motion-fast);
  display: inline-block;
}

.detail-link:hover {
  color: var(--color-brand);
}

.detail-link:hover::after {
  transform: translateX(3px);
}

.card-tools {
  display: flex;
  gap: var(--space-2);
}
</style>
