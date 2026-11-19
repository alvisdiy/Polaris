<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getScholarship, ApiError } from '../api/client'
import type { ScholarshipDetail } from '../api/types'
import { deadlineDisplay, formatDate } from '../lib/format'
import EmptyState from '../components/EmptyState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import ErrorState from '../components/ErrorState.vue'

const route = useRoute()
const router = useRouter()

interface Column {
  id: string
  data: ScholarshipDetail | null
  state: 'loading' | 'success' | 'error'
  error: ApiError | null
}

const columns = ref<Column[]>([])

function readIds(): string[] {
  const raw = route.query.ids
  if (typeof raw !== 'string') return []
  return raw.split(',').filter(Boolean).slice(0, 4)
}

async function loadColumns() {
  const ids = readIds()
  columns.value = ids.map((id) => ({ id, data: null, state: 'loading', error: null }))
  await Promise.all(
    columns.value.map(async (column: Column) => {
      try {
        column.data = await getScholarship(column.id)
        column.state = 'success'
      } catch (err) {
        column.state = 'error'
        column.error = err instanceof ApiError ? err : new ApiError('server', 'Failed to load.')
      }
    }),
  )
}

onMounted(loadColumns)
watch(() => route.query.ids, loadColumns)

function removeColumn(id: string) {
  const remaining = readIds().filter((existing) => existing !== id)
  router.replace({ path: '/compare', query: remaining.length ? { ids: remaining.join(',') } : {} })
}

const loadedCount = computed(() => columns.value.filter((column: Column) => column.state === 'success').length)

interface Row {
  label: string
  /** Rows render a string; a field the backend reports as null becomes a
   *  dash, never a word pretending to be a value. */
  value: (item: ScholarshipDetail) => string
}

const notRecorded = '—'

const rows: Row[] = [
  {
    label: 'Provider',
    value: (item) =>
      item.provider_name
        ? item.provider_type
          ? `${item.provider_name} (${item.provider_type})`
          : item.provider_name
        : notRecorded,
  },
  { label: 'Country', value: (item) => item.country ?? notRecorded },
  { label: 'Degree', value: (item) => item.degree ?? notRecorded },
  { label: 'Funding', value: (item) => item.funding_type },
  {
    label: 'Deadline',
    value: (item) => {
      const display = deadlineDisplay(item.timeline?.application_deadline ?? item.deadline ?? null)
      return display.date ? `${display.label}: ${display.date}` : display.label
    },
  },
  {
    label: 'Application cycle',
    value: (item) => item.timeline?.application_cycle ?? 'Not mentioned',
  },
  {
    label: 'Minimum GPA',
    value: (item) => (item.requirement?.minimum_gpa !== null && item.requirement?.minimum_gpa !== undefined
      ? String(item.requirement.minimum_gpa)
      : 'Not mentioned'),
  },
  {
    label: 'IELTS',
    value: (item) => {
      const req = item.requirement
      if (!req) return 'Not mentioned'
      if (!req.ielts_required) return 'Not required'
      return req.minimum_ielts !== null ? `Minimum ${req.minimum_ielts}` : 'Required'
    },
  },
  {
    label: 'TOEFL iBT',
    value: (item) => {
      const req = item.requirement
      if (!req) return 'Not mentioned'
      if (!req.toefl_required) return 'Not required'
      return req.minimum_toefl !== null ? `Minimum ${req.minimum_toefl}` : 'Required'
    },
  },
  {
    label: 'Tuition covered',
    value: (item) => (item.benefit ? (item.benefit.tuition_fee ? 'Yes' : 'No') : 'Not mentioned'),
  },
  {
    label: 'Monthly allowance',
    value: (item) => (item.benefit ? (item.benefit.monthly_allowance ? 'Yes' : 'No') : 'Not mentioned'),
  },
  {
    label: 'Accommodation',
    value: (item) => (item.benefit ? (item.benefit.accommodation ? 'Yes' : 'No') : 'Not mentioned'),
  },
  {
    label: 'Health insurance',
    value: (item) => (item.benefit ? (item.benefit.health_insurance ? 'Yes' : 'No') : 'Not mentioned'),
  },
  {
    label: 'Travel ticket',
    value: (item) => (item.benefit ? (item.benefit.travel_ticket ? 'Yes' : 'No') : 'Not mentioned'),
  },
  {
    label: 'Research grant',
    value: (item) => (item.benefit ? (item.benefit.research_grant ? 'Yes' : 'No') : 'Not mentioned'),
  },
]

function formatOpen(value: string | null): string {
  const formatted = formatDate(value)
  return formatted ?? ''
}
</script>

<template>
  <div class="compare">
    <div class="compare-inner">
      <header class="page-head">
        <h1>Compare scholarships</h1>
        <p class="page-sub">Side-by-side view of up to four scholarships from the knowledge base.</p>
      </header>

      <EmptyState
        v-if="columns.length < 2"
        title="Select at least two scholarships"
        description="Add scholarships to compare using the Compare checkbox on any scholarship card or detail page."
      >
        <RouterLink to="/discover" class="button-primary">Browse scholarships</RouterLink>
      </EmptyState>

      <template v-else>
        <p class="selection-note" aria-live="polite">
          Comparing {{ columns.length }} scholarships ({{ loadedCount }} loaded)
        </p>

        <div class="table-wrap" role="region" aria-label="Comparison table" tabindex="0">
          <table class="compare-table">
            <thead>
              <tr>
                <th scope="col" class="row-head-col"><span class="visually-hidden">Field</span></th>
                <th v-for="column in columns" :key="column.id" scope="col" class="item-col">
                  <div v-if="column.state === 'loading'" class="col-loading">
                    <SkeletonBlock :lines="2" height="1rem" />
                  </div>
                  <div v-else-if="column.state === 'error'" class="col-error">
                    <p class="col-error-text">Could not load this scholarship.</p>
                  </div>
                  <template v-else-if="column.data">
                    <RouterLink
                      :to="`/scholarships/${column.data.scholarship_id}`"
                      class="col-name"
                    >
                      {{ column.data.scholarship_name }}
                    </RouterLink>
                    <button
                      type="button"
                      class="col-remove"
                      :aria-label="`Remove ${column.data.scholarship_name} from comparison`"
                      @click="removeColumn(column.id)"
                    >
                      Remove
                    </button>
                  </template>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.label">
                <th scope="row" class="row-head">{{ row.label }}</th>
                <td v-for="column in columns" :key="column.id" class="cell">
                  <template v-if="column.state === 'success' && column.data">
                    <template v-if="row.label === 'Deadline' && column.data.timeline?.application_open">
                      <span class="cell-deadline" :class="{ expired: deadlineDisplay(column.data.timeline.application_deadline).state === 'expired' }">
                        {{ row.value(column.data) }}
                      </span>
                      <span class="cell-sub">Opens {{ formatOpen(column.data.timeline.application_open) }}</span>
                    </template>
                    <template v-else-if="row.label === 'Deadline'">
                      <span
                        class="cell-deadline"
                        :class="{
                          expired: deadlineDisplay(column.data.timeline?.application_deadline ?? column.data.deadline ?? null).state === 'expired',
                          unknown: deadlineDisplay(column.data.timeline?.application_deadline ?? column.data.deadline ?? null).state === 'unknown',
                        }"
                      >
                        {{ row.value(column.data) }}
                      </span>
                    </template>
                    <template v-else>{{ row.value(column.data) }}</template>
                  </template>
                  <template v-else-if="column.state === 'loading'">
                    <span class="cell-loading" aria-hidden="true">...</span>
                    <span class="visually-hidden">Loading</span>
                  </template>
                  <template v-else>
                    <span class="cell-error-inline">Not loaded</span>
                  </template>
                </td>
              </tr>
              <tr>
                <th scope="row" class="row-head">Official source</th>
                <td v-for="column in columns" :key="column.id" class="cell">
                  <a
                    v-if="column.state === 'success' && column.data"
                    :href="column.data.official_url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="official-link"
                  >
                    Official page
                  </a>
                  <template v-else>{{ '\u2014' }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="stack">
          <section
            v-for="column in columns"
            :key="column.id"
            class="stack-item"
            :aria-label="column.data?.scholarship_name ?? 'Scholarship'"
          >
            <div v-if="column.state === 'loading'">
              <SkeletonBlock :lines="5" height="1rem" />
            </div>
            <div v-else-if="column.state === 'error'">
              <ErrorState :message="column.error?.message ?? 'Failed to load.'" @retry="loadColumns" />
            </div>
            <template v-else-if="column.data">
              <header class="stack-head">
                <h2 class="stack-name">{{ column.data.scholarship_name }}</h2>
                <button type="button" class="col-remove" @click="removeColumn(column.id)">Remove</button>
              </header>
              <dl class="stack-list">
                <div v-for="row in rows" :key="row.label" class="stack-row">
                  <dt>{{ row.label }}</dt>
                  <dd>{{ row.value(column.data) }}</dd>
                </div>
                <div class="stack-row">
                  <dt>Official source</dt>
                  <dd>
                    <a
                      :href="column.data.official_url"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="official-link"
                    >
                      Official page
                    </a>
                  </dd>
                </div>
              </dl>
            </template>
          </section>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.compare-inner {
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
  margin: 0 0 var(--space-4);
  max-width: 58ch;
}

.selection-note {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--color-ink-secondary);
  margin-bottom: var(--space-4);
}

.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--color-line);
  background: var(--color-surface);
}

.compare-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 52rem;
}

.compare-table th,
.compare-table td {
  text-align: left;
  vertical-align: top;
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-line);
  font-size: var(--font-size-sm);
}

.row-head-col,
.row-head {
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--color-ink-secondary);
  width: 12rem;
  background: var(--color-paper);
  position: sticky;
  left: 0;
}

.item-col {
  min-width: 16rem;
}

.col-name {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 500;
}

.col-remove {
  border: none;
  background: none;
  color: var(--color-ink-secondary);
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.col-remove:hover {
  color: var(--color-brand);
}

.cell-deadline.expired {
  color: var(--color-sem-expired);
}

.cell-deadline.unknown {
  color: var(--color-sem-unknown);
}

.cell-sub {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-ink-secondary);
}

.official-link {
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin-top: var(--space-6);
}

.stack-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  border-bottom: 1px solid var(--color-line-strong);
  padding-bottom: var(--space-2);
}

.stack-name {
  font-family: var(--font-display);
  font-size: 1.2rem;
}

.stack-list {
  display: flex;
  flex-direction: column;
}

.stack-row {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) 0;
  border-bottom: 1px dotted var(--color-line);
  font-size: var(--font-size-sm);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
