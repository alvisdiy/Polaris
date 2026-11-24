<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useScholarshipList } from '../api/composables'
import ScholarshipCard from '../components/ScholarshipCard.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import ProgressLine from '../components/ProgressLine.vue'
import FilterChip from '../components/FilterChip.vue'
import { loadCountries } from '../lib/countries'

const route = useRoute()
const router = useRouter()
const { data, state, error, fetchList } = useScholarshipList()

const PAGE_SIZE = 20

// From the API, not hardcoded: this list used to be maintained by hand
// here and in ProfileForm, and the two copies disagreed.
const countries = ref<string[]>([])
loadCountries().then((list) => {
  countries.value = list
})

const DEGREES = ['Bachelor', 'Master', 'PhD', 'Exchange', 'Short Course']

function readQueryState(query: Record<string, unknown>) {
  return {
    q: typeof query.q === 'string' ? query.q : '',
    country: typeof query.country === 'string' ? query.country : '',
    degree: typeof query.degree === 'string' ? query.degree : '',
    funding: typeof query.funding === 'string' ? query.funding : '',
    sort: query.sort === 'name' ? 'name' as const : 'deadline' as const,
    page: Number(query.page) > 0 ? Number(query.page) : 1,
  }
}

/* URL is the source of truth (web-design.md section 27). */
const initial = readQueryState(route.query as Record<string, unknown>)
const q = ref(initial.q)
const country = ref(initial.country)
const degree = ref(initial.degree)
const funding = ref(initial.funding)
const sort = ref<'deadline' | 'name'>(initial.sort)
const page = ref(initial.page)

const FUNDING_TYPES = ['Fully Funded', 'Partial Funded', 'Tuition Only']

const filterDetails = ref<HTMLDetailsElement | null>(null)
const hasActiveFilters = computed(
  () => Boolean(q.value) || Boolean(country.value) || Boolean(degree.value) || Boolean(funding.value),
)
const activeFilterCount = computed(
  () => [q.value.trim(), country.value, degree.value, funding.value].filter(Boolean).length,
)

const total = computed(() => data.value?.total ?? 0)
const results = computed(() => data.value?.results ?? [])
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

let debounceTimer: ReturnType<typeof setTimeout> | undefined
let syncingFromRoute = false

function buildParams() {
  return {
    q: q.value.trim() || undefined,
    country: country.value || undefined,
    degree: degree.value || undefined,
    funding: funding.value || undefined,
    sort: sort.value,
    limit: PAGE_SIZE,
    offset: (page.value - 1) * PAGE_SIZE,
  }
}

function syncUrl() {
  const query: Record<string, string> = {}
  if (q.value.trim()) query.q = q.value.trim()
  if (country.value) query.country = country.value
  if (degree.value) query.degree = degree.value
  if (funding.value) query.funding = funding.value
  if (sort.value !== 'deadline') query.sort = sort.value
  if (page.value > 1) query.page = String(page.value)
  router.replace({ path: '/discover', query })
}

function runFetch() {
  syncUrl()
  fetchList(buildParams())
}

function scheduleFetch(debounced: boolean) {
  clearTimeout(debounceTimer)
  if (debounced) {
    debounceTimer = setTimeout(runFetch, 300)
  } else {
    runFetch()
  }
}

function fetchCurrent() {
  clearTimeout(debounceTimer)
  runFetch()
}

/* Debounced typing for the query field. */
watch(q, () => {
  if (syncingFromRoute) return
  page.value = 1
  scheduleFetch(true)
})

function onCountryChange(event: Event) {
  country.value = (event.target as HTMLSelectElement).value
  page.value = 1
  scheduleFetch(false)
}

function onDegreeChange(event: Event) {
  degree.value = (event.target as HTMLSelectElement).value
  page.value = 1
  scheduleFetch(false)
}

function onFundingChange(event: Event) {
  funding.value = (event.target as HTMLSelectElement).value
  page.value = 1
  scheduleFetch(false)
}

function onSortChange(event: Event) {
  sort.value = (event.target as HTMLSelectElement).value as 'deadline' | 'name'
  page.value = 1
  scheduleFetch(false)
}

function suppressAndApply(mutate: () => void) {
  syncingFromRoute = true
  mutate()
  scheduleFetch(false)
  nextTick(() => {
    syncingFromRoute = false
  })
}

function removeKeyword() {
  suppressAndApply(() => {
    q.value = ''
    page.value = 1
  })
}

function removeCountry() {
  suppressAndApply(() => {
    country.value = ''
    page.value = 1
  })
}

function removeDegree() {
  suppressAndApply(() => {
    degree.value = ''
    page.value = 1
  })
}

function removeFunding() {
  suppressAndApply(() => {
    funding.value = ''
    page.value = 1
  })
}

function clearFilters() {
  suppressAndApply(() => {
    q.value = ''
    country.value = ''
    degree.value = ''
    funding.value = ''
    page.value = 1
  })
}

function goToPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  scheduleFetch(false)
}

/* Back/forward navigation re-reads the URL. */
watch(
  () => route.query,
  (query) => {
    const next = readQueryState(query as Record<string, unknown>)
    if (
      next.q === q.value &&
      next.country === country.value &&
      next.degree === degree.value &&
      next.funding === funding.value &&
      next.sort === sort.value &&
      next.page === page.value
    ) {
      return
    }
    syncingFromRoute = true
    q.value = next.q
    country.value = next.country
    degree.value = next.degree
    funding.value = next.funding
    sort.value = next.sort
    page.value = next.page
    clearTimeout(debounceTimer)
    fetchList(buildParams())
    nextTick(() => {
      syncingFromRoute = false
    })
  },
)

onMounted(() => {
  if (filterDetails.value && window.matchMedia('(min-width: 901px)').matches) {
    filterDetails.value.open = true
  }
  fetchCurrent()
})

function announceCount(): string {
  return state.value === 'success' ? `${total.value} scholarships found` : ''
}
</script>

<template>
  <div class="discover">
    <div class="discover-inner">
      <header class="page-head">
        <h1>Browse scholarships</h1>
        <p class="page-sub">
          Every record is collected from an official provider page. Expired opportunities are
          excluded automatically.
        </p>
      </header>

      <div class="layout">
        <aside class="filter-rail" aria-label="Filters">
          <details ref="filterDetails" class="filter-disclosure">
            <summary class="filter-summary">
              <span>Filters</span>
              <span v-if="activeFilterCount" class="filter-count">{{ activeFilterCount }} active</span>
            </summary>
            <div class="filter-body">
              <div class="filter-group">
                <label class="filter-label" for="filter-q">Keyword</label>
                <input
                  id="filter-q"
                  v-model="q"
                  type="search"
                  class="filter-input"
                  placeholder="Scholarship name"
                />
              </div>

              <div class="filter-group">
                <label class="filter-label" for="filter-country">Country</label>
                <select id="filter-country" :value="country" class="filter-select" @change="onCountryChange">
                  <option value="">All countries</option>
                  <option v-for="c in countries" :key="c" :value="c">{{ c }}</option>
                </select>
              </div>

              <div class="filter-group">
                <label class="filter-label" for="filter-degree">Degree</label>
                <select id="filter-degree" :value="degree" class="filter-select" @change="onDegreeChange">
                  <option value="">All degrees</option>
                  <option v-for="d in DEGREES" :key="d" :value="d">{{ d }}</option>
                </select>
              </div>

              <div class="filter-group">
                <label class="filter-label" for="filter-funding">Funding</label>
                <select id="filter-funding" :value="funding" class="filter-select" @change="onFundingChange">
                  <option value="">Any funding</option>
                  <option v-for="f in FUNDING_TYPES" :key="f" :value="f">{{ f }}</option>
                </select>
              </div>

              <div class="filter-group">
                <label class="filter-label" for="filter-sort">Sort by</label>
                <select id="filter-sort" :value="sort" class="filter-select" @change="onSortChange">
                  <option value="deadline">Closing soonest</option>
                  <option value="name">Name A–Z</option>
                </select>
              </div>

              <p class="filter-note">
                Field of study and deadline-status filters will arrive with a backend
                update. They are not yet available.
              </p>
            </div>
          </details>
        </aside>

        <section class="results" aria-label="Results" :aria-busy="state === 'loading'">
          <ProgressLine v-if="state === 'loading' && results.length" />
          <p class="result-count" aria-live="polite">{{ announceCount() }}</p>

          <div v-if="hasActiveFilters" class="chips" aria-label="Active filters">
            <FilterChip
              v-if="q"
              label="Keyword"
              :value="q"
              @remove="removeKeyword"
            />
            <FilterChip
              v-if="country"
              label="Country"
              :value="country"
              @remove="removeCountry"
            />
            <FilterChip
              v-if="degree"
              label="Degree"
              :value="degree"
              @remove="removeDegree"
            />
            <FilterChip
              v-if="funding"
              label="Funding"
              :value="funding"
              @remove="removeFunding"
            />
            <button type="button" class="clear-all" @click="clearFilters">Clear all</button>
          </div>

          <div v-if="state === 'loading' && !results.length" class="skeleton-list">
            <SkeletonBlock :lines="4" height="1.25rem" />
            <SkeletonBlock :lines="4" height="1.25rem" />
            <SkeletonBlock :lines="4" height="1.25rem" />
            <SkeletonBlock :lines="4" height="1.25rem" />
          </div>

          <ErrorState
            v-else-if="state === 'error' && error"
            :message="error.message"
            @retry="fetchCurrent"
          />

          <template v-else-if="state === 'success'">
            <EmptyState
              v-if="results.length === 0 && total === 0 && !hasActiveFilters"
              title="No scholarships yet"
              description="The knowledge base is empty or being updated. Learn how collection works on the About page."
            >
              <RouterLink to="/about" class="button-secondary">About the method</RouterLink>
            </EmptyState>

            <EmptyState
              v-else-if="results.length === 0"
              title="No results for these filters"
              description="Try removing a filter or searching for a different term."
            >
              <button type="button" class="button-secondary" @click="clearFilters">
                Clear all filters
              </button>
            </EmptyState>

            <template v-else>
              <div class="card-grid">
                <ScholarshipCard
                  v-for="item in results"
                  :key="item.scholarship_id"
                  :scholarship="item"
                />
              </div>

              <nav v-if="totalPages > 1" class="pagination" aria-label="Pagination">
                <button
                  type="button"
                  class="page-button"
                  :disabled="page <= 1"
                  @click="goToPage(page - 1)"
                >
                  Previous
                </button>
                <span class="page-indicator">Page {{ page }} of {{ totalPages }}</span>
                <button
                  type="button"
                  class="page-button"
                  :disabled="page >= totalPages"
                  @click="goToPage(page + 1)"
                >
                  Next
                </button>
              </nav>
            </template>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.discover-inner {
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
  grid-template-columns: var(--rail-width) minmax(0, 1fr);
  gap: var(--space-7);
  align-items: start;
}

.filter-rail {
  position: sticky;
  top: 5.5rem;
}

.filter-disclosure {
  margin: 0;
  border: 1px solid var(--color-line);
  border-top: 2px solid var(--color-brand);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  padding: var(--space-3);
}

.filter-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 44px;
  padding: 0 var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink);
  cursor: pointer;
  list-style: none;
}

.filter-summary::-webkit-details-marker {
  display: none;
}

.filter-count {
  color: var(--color-brand);
  letter-spacing: var(--tracking-meta);
}

.filter-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin-top: var(--space-4);
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.filter-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.filter-input,
.filter-select {
  width: 100%;
  min-height: 44px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface-raised);
  color: var(--color-ink);
  font-size: var(--font-size-sm);
}

.filter-input:focus-visible,
.filter-select:focus-visible {
  outline: 2px solid var(--color-brand);
  outline-offset: 1px;
}

.filter-note {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-ink-secondary);
  border-top: 1px dashed var(--color-line);
  padding-top: var(--space-3);
}

.results {
  min-width: 0;
}

.result-count {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-3);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.clear-all {
  border: none;
  background: none;
  padding: 0;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-brand);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Browse results run two-up on desktop: the registry is a catalog, and a
   two-column spread reads faster than a single long column. */
.card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-line);
}

.page-button {
  min-height: 44px;
  padding: 0 var(--space-4);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
}

.page-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-button:not(:disabled):hover {
  border-color: var(--color-ink);
}

.page-indicator {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

@media (min-width: 901px) {
  .filter-summary {
    display: none;
  }

  .filter-body {
    margin-top: 0;
  }
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
    gap: var(--space-5);
  }

  .filter-rail {
    position: static;
  }

  .card-grid {
    grid-template-columns: 1fr;
  }
}
</style>
