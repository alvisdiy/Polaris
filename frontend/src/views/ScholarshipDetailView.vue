<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useScholarshipDetail } from '../api/composables'
import { deadlineDisplay, formatDate, hostOf } from '../lib/format'
import SourceCitation from '../components/SourceCitation.vue'
import ErrorState from '../components/ErrorState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import SaveButton from '../components/SaveButton.vue'
import CompareToggle from '../components/CompareToggle.vue'

const route = useRoute()
const { data, state, error, fetchDetail } = useScholarshipDetail()

const id = computed(() => String(route.params.id))

onMounted(() => fetchDetail(id.value))
watch(id, (value) => {
  if (value) fetchDetail(value)
})

const scholarship = computed(() => data.value)

const isExpired = computed(() => deadlineDisplay(scholarship.value?.deadline ?? null).state === 'expired')

const timelineRows = computed(() => {
  const timeline = scholarship.value?.timeline
  if (!timeline) return []
  return [
    { label: 'Application opens', value: formatDate(timeline.application_open) },
    { label: 'Application deadline', value: formatDate(timeline.application_deadline) },
    { label: 'Application cycle', value: timeline.application_cycle },
    { label: 'Interview date', value: formatDate(timeline.interview_date) },
    { label: 'Result date', value: formatDate(timeline.result_date) },
    { label: 'Study starts', value: formatDate(timeline.study_start) },
  ].filter((row) => row.value)
})

const requirementRows = computed(() => {
  const req = scholarship.value?.requirement
  if (!req) return []
  const notMentioned = 'Not mentioned in the source'
  return [
    {
      label: 'Minimum GPA',
      value: req.minimum_gpa !== null ? String(req.minimum_gpa) : notMentioned,
    },
    {
      label: 'IELTS',
      value: req.ielts_required
        ? req.minimum_ielts !== null
          ? `Required, minimum ${req.minimum_ielts}`
          : 'Required'
        : 'Not required',
    },
    {
      label: 'TOEFL iBT',
      value: req.toefl_required
        ? req.minimum_toefl !== null
          ? `Required, minimum ${req.minimum_toefl}`
          : 'Required'
        : 'Not required',
    },
    { label: 'Work experience', value: req.work_experience ?? notMentioned },
    { label: 'Research experience', value: req.research_experience ?? notMentioned },
    { label: 'Publications', value: req.publication ?? notMentioned },
  ]
})

const benefitRows = computed(() => {
  const benefit = scholarship.value?.benefit
  if (!benefit) return []
  return [
    { label: 'Tuition fee', value: benefit.tuition_fee },
    { label: 'Monthly allowance', value: benefit.monthly_allowance },
    { label: 'Accommodation', value: benefit.accommodation },
    { label: 'Health insurance', value: benefit.health_insurance },
    { label: 'Travel ticket', value: benefit.travel_ticket },
    { label: 'Research grant', value: benefit.research_grant },
  ]
})

const applicationLink = computed(() => {
  const detail = scholarship.value
  if (!detail) return null
  if (!detail.application_url) return null
  return detail.application_url === detail.official_url ? null : detail.application_url
})

const officialHost = computed(() => (scholarship.value ? hostOf(scholarship.value.official_url) : null))

function retry() {
  fetchDetail(id.value)
}
</script>

<template>
  <div class="detail">
    <div class="detail-inner">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <RouterLink to="/discover">Browse</RouterLink>
        <span aria-hidden="true">/</span>
        <span class="breadcrumb-current">{{
          scholarship?.scholarship_name ?? 'Scholarship'
        }}</span>
      </nav>

      <div v-if="state === 'loading'" class="detail-loading">
        <SkeletonBlock :lines="3" height="1.75rem" />
        <SkeletonBlock :lines="5" height="1rem" />
        <SkeletonBlock :lines="5" height="1rem" />
      </div>

      <ErrorState
        v-else-if="state === 'error' && error"
        :message="error.kind === 'not-found'
          ? 'This scholarship does not exist, may have been removed, or the link is wrong.'
          : error.message"
        :title="error.kind === 'not-found' ? 'Scholarship not found' : undefined"
        @retry="retry"
      >
        <RouterLink to="/discover" class="button-secondary">Back to Browse</RouterLink>
      </ErrorState>

      <article v-else-if="scholarship">
        <div v-if="isExpired" class="archive-banner" role="status">
          This scholarship's deadline has passed. The information below is shown as an archive.
        </div>

        <header class="detail-head">
          <div class="head-main">
            <h1>{{ scholarship.scholarship_name }}</h1>
            <p class="provider-line">
              {{ scholarship.provider_name }}
              <template v-if="scholarship.provider_type"> · {{ scholarship.provider_type }}</template>
              · {{ scholarship.country }}
            </p>
            <ul class="head-meta" aria-label="Key details">
              <li>{{ scholarship.degree }}</li>
              <li>{{ scholarship.funding_type }}</li>
              <li v-for="field in scholarship.field_of_study" :key="field">{{ field }}</li>
            </ul>
          </div>
          <div class="head-actions">
            <a
              :href="scholarship.official_url"
              target="_blank"
              rel="noopener noreferrer"
              class="button-primary"
              :class="{ 'button-demoted': isExpired }"
            >
              Open official page
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M14 5h5v5M19 5l-8 8M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </a>
            <a
              v-if="applicationLink"
              :href="applicationLink"
              target="_blank"
              rel="noopener noreferrer"
              class="button-secondary"
            >
              Application page
            </a>
            <div class="head-tools">
              <SaveButton :scholarship-id="scholarship.scholarship_id" />
              <CompareToggle :scholarship-id="scholarship.scholarship_id" />
            </div>
          </div>
        </header>

        <section class="facts" aria-label="Key facts">
          <dl class="facts-list">
            <div class="fact">
              <dt>Degree</dt>
              <dd v-if="scholarship.degree">{{ scholarship.degree }}</dd>
              <dd v-else-if="scholarship.degree_levels?.length" class="fact-levels">
                {{ scholarship.degree_levels.join(' · ') }}
              </dd>
              <dd v-else class="fact-unknown">Level not stated on the page</dd>
            </div>
            <div class="fact">
              <dt>Funding</dt>
              <dd v-if="scholarship.funding_type">{{ scholarship.funding_type }}</dd>
              <dd v-else class="fact-unknown">Funding not stated on the page</dd>
            </div>
            <div class="fact">
              <dt>Deadline</dt>
              <dd>
                <span
                  v-if="scholarship.timeline?.application_deadline"
                  class="fact-date"
                  :class="{ 'fact-expired': isExpired }"
                >
                  {{ formatDate(scholarship.timeline.application_deadline) }}
                </span>
                <span v-else class="fact-unknown">Deadline unknown</span>
              </dd>
            </div>
            <div class="fact" v-if="scholarship.timeline?.application_cycle">
              <dt>Application cycle</dt>
              <dd>{{ scholarship.timeline.application_cycle }}</dd>
            </div>
            <div class="fact">
              <dt>Last verified</dt>
              <dd v-if="scholarship.last_verified_at">
                {{ formatDate(scholarship.last_verified_at.slice(0, 10)) }}
              </dd>
              <dd v-else class="fact-unknown">Not recorded</dd>
            </div>
          </dl>
        </section>

        <section v-if="timelineRows.length" class="section" aria-labelledby="timeline-heading">
          <h2 id="timeline-heading">Timeline</h2>
          <dl class="row-list">
            <div v-for="row in timelineRows" :key="row.label" class="row">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </dl>
        </section>

        <section class="section" aria-labelledby="requirements-heading">
          <h2 id="requirements-heading">Eligibility and requirements</h2>
          <dl v-if="requirementRows.length" class="row-list">
            <div v-for="row in requirementRows" :key="row.label" class="row">
              <dt>{{ row.label }}</dt>
              <dd :class="{ 'not-mentioned': row.value === 'Not mentioned in the source' }">
                {{ row.value }}
              </dd>
            </div>
          </dl>
          <p v-else class="section-empty">Requirements were not collected for this record.</p>
        </section>

        <section class="section" aria-labelledby="benefits-heading">
          <h2 id="benefits-heading">Benefits</h2>
          <ul v-if="benefitRows.length" class="benefit-list">
            <li v-for="row in benefitRows" :key="row.label" class="benefit" :class="{ off: !row.value }">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
                class="benefit-icon"
              >
                <path
                  v-if="row.value"
                  d="m5 13 4 4L19 7"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path v-else d="M6 12h12" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </svg>
              {{ row.label }}
            </li>
          </ul>
          <p v-else class="section-empty">Benefits were not collected for this record.</p>
        </section>

        <section class="provenance" aria-labelledby="provenance-heading">
          <h2 id="provenance-heading">Source and provenance</h2>
          <p class="provenance-note">
            This record was captured by Polaris from the provider's official page
            <template v-if="officialHost"> ({{ officialHost }})</template>. Always check the
            official page for the latest information.
          </p>
          <SourceCitation :url="scholarship.official_url" class="provenance-citation" />
          <details class="method-disclosure">
            <summary>How this data is collected</summary>
            <p>
              Polaris explores official provider websites, records each scholarship page, and
              keeps the source link with the record. Deadlines are never invented: when a source
              does not publish one, the record says so.
            </p>
            <RouterLink to="/about">Read the full method</RouterLink>
          </details>
        </section>
      </article>
    </div>
  </div>
</template>

<style scoped>
.detail-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: var(--space-5) var(--space-5) var(--space-8);
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  margin-bottom: var(--space-5);
}

.breadcrumb a {
  color: var(--color-ink-secondary);
  text-decoration: none;
}

.breadcrumb a:hover {
  color: var(--color-brand);
}

.breadcrumb-current {
  color: var(--color-ink);
  text-transform: none;
  letter-spacing: 0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 46ch;
}

.detail-loading {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.archive-banner {
  margin-bottom: var(--space-5);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-line-strong);
  border-left: 3px solid var(--color-sem-expired);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

.detail-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-6);
  align-items: start;
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-line);
}

.head-main h1 {
  font-family: var(--font-display);
  font-size: clamp(1.9rem, 3.6vw, 2.9rem);
  letter-spacing: -0.03em;
  line-height: 1.08;
  margin: 0 0 var(--space-3);
  max-width: 24ch;
}

.provider-line {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-3);
}

.head-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.head-meta li {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--color-line);
  background: var(--color-surface-raised);
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-meta);
  color: var(--color-ink-secondary);
}

.head-actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 13rem;
}

/* The expired record's primary action is demoted, so it must not inherit the
   vermilion hover from .button-primary (0,2,0 beats a single class). */
.button-primary.button-demoted,
.button-primary.button-demoted:hover {
  background: var(--color-surface);
  border-color: var(--color-line-strong);
  color: var(--color-ink-secondary);
}

.button-primary.button-demoted:hover {
  transform: none;
}

.head-tools {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}

.facts {
  display: grid;
  grid-template-columns: minmax(0, 8fr) minmax(0, 4fr);
  gap: var(--space-7);
  padding: var(--space-6) 0;
  border-bottom: 1px solid var(--color-line);
}

.facts-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.fact,
.row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  font-size: var(--font-size-sm);
  padding: var(--space-2) 0;
  border-bottom: 1px dotted var(--color-line);
}

.fact::before,
.row > :first-child {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.fact-date {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
}

.fact-expired {
  color: var(--color-sem-expired);
}

.fact-unknown {
  color: var(--color-sem-unknown);
  font-style: italic;
}

.fact-levels {
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  letter-spacing: 0.02em;
}

.section {
  padding: var(--space-6) 0;
  border-bottom: 1px solid var(--color-line);
}

.section h2 {
  font-family: var(--font-display);
  font-size: 1.45rem;
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-4);
}

.row-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.row {
  display: grid;
  grid-template-columns: minmax(10rem, 14rem) minmax(0, 1fr);
  gap: var(--space-4);
}

.not-mentioned {
  color: var(--color-ink-secondary);
  font-style: italic;
}

.section-empty {
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  font-style: italic;
}

.benefit-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2) var(--space-5);
}

.benefit {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  padding: var(--space-2) 0;
  border-bottom: 1px dotted var(--color-line);
}

.benefit.off {
  color: var(--color-ink-secondary);
  text-decoration: line-through;
  text-decoration-color: var(--color-line-strong);
}

.benefit-icon {
  font-family: var(--font-mono);
  color: var(--color-evidence);
}

.provenance {
  padding: var(--space-5);
  border: 1px solid var(--color-line-strong);
  border-left: 3px solid var(--color-evidence);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  margin-top: var(--space-5);
}

.provenance-note,
.provenance-citation {
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

.method-disclosure {
  margin-top: var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

@media (max-width: 900px) {
  .detail-head,
  .facts {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }

  .head-actions {
    min-width: 0;
  }

  .row {
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }

  .benefit-list {
    grid-template-columns: 1fr;
  }
}
</style>
