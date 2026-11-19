<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useScholarshipList } from '../api/composables'
import ScholarshipCard from '../components/ScholarshipCard.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'
import ProgressLine from '../components/ProgressLine.vue'
import FilterChip from '../components/FilterChip.vue'

const route = useRoute()
const router = useRouter()
const { data, state, error, fetchList } = useScholarshipList()

const PAGE_SIZE = 20

const COUNTRIES = [
  'Australia',
  'Brunei',
  'China',
  'Germany',
  'France',
  'United Kingdom',
  'Indonesia',
  'Japan',
  'Malaysia',
  'Singapore',
  'South Korea',
  'United States',
]

const DEGREES = ['Bachelor', 'Master', 'PhD', 'Exchange', 'Short Course']

/* URL is the source of truth (web-design.md section 27). */
const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const country = ref(typeof route.query.country === 'string' ? route.query.country : '')
const degree = ref(typeof route.query.degree === 'string' ? route.query.degree : '')
const page = ref(Number(route.query.page) > 0 ? Number(route.query.page) : 1)

const hasActiveFilters = computed(
  () => Boolean(q.value) || Boolean(country.value) || Boolean(degree.value),
)

const total = computed(() => data.value?.total ?? 0)
const results = computed(() => data.value?.results ?? [])
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const showOffset = computed(() => (page.value - 1) * PAGE_SIZE)

let debounceTimer: ReturnType<typeof setTimeout> | undefined

function syncUrl() {
  const query: Record<string, string> = {}
  if (q.value.trim()) query.q = q.value.trim()
  if (country.value) query.country = country.value
  if (degree.value) query.degree = degree.value
  if (page.value > 1) query.page = String(page.value)
  router.replace({ path: '/discover', query })
}

function fetchCurrent() {
  fetchList({
    q: q.value.trim() || undefined,
    country: country.value || undefined,
    degree: degree.value || undefined,
    limit: PAGE_SIZE,
    offset: (page.value - 1) * PAGE_SIZE,
  })
}

/* Debounced typing for the query field; immediate for selects and paging. */
watch(q, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    page.value = 1
    syncUrl()
    fetchCurrent()
  }, 300)
})

watch([country, degree], () => {
  page.value = 1
  syncUrl()
  fetchCurrent()
})

watch(page, () => {
  syncUrl()
  fetchCurrent()
})

/* Back/forward navigation re-reads the URL. */
watch(
  () => route.query,
  (query) => {
    const nextQ = typeof query.q === 'string' ? query.q : ''
    const nextCountry = typeof query.country === 'string' ? query.country : ''
    const nextDegree = typeof query.degree === 'string' ? query.degree : ''
    const nextPage = Number(query.page) > 0 ? Number(query.page) : 1
    if (
      nextQ !== q.value ||
      nextCountry !== country.value ||
      nextDegree !== degree.value ||
      nextPage !== page.value
    ) {
      q.value = nextQ
      country.value = nextCountry
      degree.value = nextDegree
      page.value = nextPage
      fetchCurrent()
    }
  },
)

onMounted(fetchCurrent)

function clearFilters() {
  q.value = ''
  country.value = ''
  degree.value = ''
  page.value = 1
  syncUrl()
  fetchCurrent()
}

function goToPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
}

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
            <select id="filter-country" v-model="country" class="filter-select">
              <option value="">All countries</option>
              <option v-for="c in COUNTRIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>

          <div class="filter-group">
            <label class="filter-label" for="filter-degree">Degree</label>
            <select id="filter-degree" v-model="degree" class="filter-select">
              <option value="">All degrees</option>
              <option v-for="d in DEGREES" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>

          <p class="filter-note">
            Funding, field of study, and deadline-status filters will arrive with a backend
            update. They are not yet available.
          </p>
        </aside>

        <section class="results" aria-label="Results" :aria-busy="state === 'loading'">
          <ProgressLine v-if="state === 'loading' && results.length" />
          <p class="result-count" aria-live="polite">{{ announceCount() }}</p>

          <div v-if="hasActiveFilters" class="chips" aria-label="Active filters">
            <FilterChip
              v-if="q"
              label="Keyword"
              :value="q"
              @remove="
                q = '';
                page = 1;
                syncUrl();
                fetchCurrent()
              "
            />
            <FilterChip
              v-if="country"
              label="Country"
              :value="country"
              @remove="
                country = '';
                page = 1;
                syncUrl();
                fetchCurrent()
              "
            />
            <FilterChip
              v-if="degree"
              label="Degree"
              :value="degree"
              @remove="
                degree = '';
                page = 1;
                syncUrl();
                fetchCurrent()
              "
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
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.filter-label {
  font-family: var(--font-mono);
  font-size: 0.66rem;
  text-transform: uppercase;
  letter-spacing: 0.14em;
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
  letter-spacing: 0.12em;
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
  letter-spacing: 0.1em;
  color: var(--color-brand);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.skeleton-list,
.card-grid {
  display: flex;
  flex-direction: column;
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
  letter-spacing: 0.12em;
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
  letter-spacing: 0.1em;
  color: var(--color-ink-secondary);
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
    gap: var(--space-5);
  }

  .filter-rail {
    position: static;
  }
}
</style>
