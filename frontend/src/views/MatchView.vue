<script setup lang="ts">
import { ref } from 'vue'
import { useMatching } from '../api/composables'
import { useProfile } from '../stores/profile'
import type { Recommendation, RecommendationRequest } from '../api/types'
import ProfileForm from '../components/ProfileForm.vue'
import ScholarshipCard from '../components/ScholarshipCard.vue'
import ScoreBadge from '../components/ScoreBadge.vue'
import ExplanationPanel from '../components/ExplanationPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'

const { submitMatch, results, total, returned, state, error } = useMatching()
const { markSaved } = useProfile()

const formRef = ref<InstanceType<typeof ProfileForm> | null>(null)
const expanded = ref<Set<string>>(new Set())
const submittedProfile = ref<RecommendationRequest | null>(null)

async function onSubmit(profile: RecommendationRequest) {
  submittedProfile.value = profile
  await submitMatch(profile)
  if (state.value === 'success') {
    markSaved()
  } else if (state.value === 'error' && error.value?.fieldErrors.length) {
    formRef.value?.mapServerErrors(error.value.fieldErrors)
  }
}

function toggleExplanation(item: Recommendation) {
  const next = new Set(expanded.value)
  if (next.has(item.scholarship_id)) {
    next.delete(item.scholarship_id)
  } else {
    next.add(item.scholarship_id)
  }
  expanded.value = next
}

function retry() {
  if (submittedProfile.value) {
    onSubmit(submittedProfile.value)
  }
}
</script>

<template>
  <div class="match">
    <div class="match-inner">
      <header class="page-head">
        <h1>Match your profile</h1>
        <p class="page-sub">
          Scholarships are ranked by explicit criteria against your profile. Scores explain how
          well you fit the stated requirements; they are not a prediction of admission.
        </p>
      </header>

      <div class="layout">
        <div class="form-column">
          <ProfileForm
            ref="formRef"
            :submitting="state === 'loading'"
            :server-field-errors="[]"
            @submit="onSubmit"
          />
        </div>

        <section class="results-column" aria-label="Matching results" :aria-busy="state === 'loading'">
          <div v-if="state === 'loading'" class="loading-note" role="status">
            Computing matches against your profile...
          </div>

          <ErrorState
            v-else-if="state === 'error' && error && error.kind !== 'validation'"
            :message="error.message"
            @retry="retry"
          />

          <template v-else-if="state === 'success'">
            <p class="results-count" aria-live="polite">
              <!--
                `total` is the size of the whole match set; `returned` is this
                page of it. When the engine truncated the list, say which is
                which instead of implying the user has seen everything.
              -->
              <template v-if="returned < total">
                Showing {{ returned }} of {{ total }} matching
                {{ total === 1 ? 'scholarship' : 'scholarships' }}
              </template>
              <template v-else>
                {{ total }} matching {{ total === 1 ? 'scholarship' : 'scholarships' }}
              </template>
            </p>

            <EmptyState
              v-if="results.length === 0"
              title="No matches yet"
              description="No scholarships currently match this profile. Try adjusting your target country, degree, or experience levels."
            >
              <RouterLink to="/discover" class="button-secondary">Browse everything</RouterLink>
            </EmptyState>

            <div v-else class="result-list">
              <div v-for="(item, index) in results" :key="item.scholarship_id" class="result">
                <div class="result-top">
                  <span class="result-rank" aria-hidden="true">{{ index + 1 }}</span>
                  <ScoreBadge :score="item.match_score" :category="item.recommendation_category" />
                  <button
                    type="button"
                    class="why-link"
                    :aria-expanded="expanded.has(item.scholarship_id)"
                    @click="toggleExplanation(item)"
                  >
                    {{ expanded.has(item.scholarship_id) ? 'Hide reasons' : 'Why this match' }}
                  </button>
                </div>
                <ScholarshipCard :scholarship="item" variant="match" :rank="index + 1" />
                <ExplanationPanel
                  v-if="expanded.has(item.scholarship_id)"
                  :recommendation="item"
                />
              </div>
            </div>
          </template>

          <EmptyState
            v-else-if="state === 'idle'"
            title="Fill in your profile to see matches"
            description="The matching engine compares your profile against every approved scholarship and explains each result."
          />
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.match-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7);
}

.page-head h1 {
  font-family: var(--font-display);
  font-size: clamp(2rem, 4vw, 3rem);
  letter-spacing: -0.03em;
  margin: 0 0 var(--space-2);
}

.page-sub {
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  max-width: 58ch;
  margin: 0 0 var(--space-6);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-line);
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--space-7);
  align-items: start;
}

.form-column {
  position: sticky;
  top: 5.5rem;
  padding: var(--space-5);
  border: 1px solid var(--color-line);
  border-top: 2px solid var(--color-ink);
  background: var(--color-surface);
}

.results-column {
  min-width: 0;
}

.loading-note {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.results-count {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-4);
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.result {
  padding: var(--space-4) 0;
  border-bottom: 1px solid var(--color-line);
}

.result-top {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
}

.result-rank {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: var(--tracking-meta);
  color: var(--color-brand);
}

.why-link {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
    gap: var(--space-5);
  }

  .form-column {
    position: static;
  }
}
</style>
