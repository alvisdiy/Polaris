<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getScholarship, ApiError } from '../api/client'
import type { ScholarshipSummary } from '../api/types'
import { useShortlist } from '../stores/shortlist'
import ScholarshipCard from '../components/ScholarshipCard.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'

const { ids, remove } = useShortlist()

const items = ref<(ScholarshipSummary & { timeline?: { application_deadline: string | null } | null })[]>([])
const state = ref<'loading' | 'success' | 'error'>('loading')
const error = ref<ApiError | null>(null)
const droppedCount = ref(0)

onMounted(async () => {
  if (ids.value.length === 0) {
    state.value = 'success'
    return
  }
  const loaded: ScholarshipSummary[] = []
  let dropped = 0
  let failed: ApiError | null = null
  for (const id of ids.value) {
    try {
      loaded.push(await getScholarship(id) as (ScholarshipSummary & { timeline?: { application_deadline: string | null } | null }))
    } catch (err) {
      if (err instanceof ApiError && err.kind === 'not-found') {
        remove(id)
        dropped += 1
      } else {
        failed = err instanceof ApiError ? err : new ApiError('server', 'Something went wrong.')
        break
      }
    }
  }
  droppedCount.value = dropped
  if (failed && loaded.length === 0) {
    error.value = failed
    state.value = 'error'
  } else {
    items.value = loaded
    state.value = 'success'
  }
})

async function retry() {
  state.value = 'loading'
  error.value = null
  window.location.reload()
}
</script>

<template>
  <div class="saved">
    <div class="saved-inner">
      <header class="page-head">
        <h1>Saved scholarships</h1>
        <p class="page-sub">
          Your shortlist is saved in this browser only. It is not linked to any account.
        </p>
      </header>

      <p v-if="droppedCount" class="dropped-note" role="status">
        {{ droppedCount }} saved {{ droppedCount === 1 ? 'item was' : 'items were' }} no longer
        available and {{ droppedCount === 1 ? 'was' : 'were' }} removed.
      </p>

      <div v-if="state === 'loading' && items.length === 0" class="skeleton-list">
        <SkeletonBlock :lines="4" height="1.25rem" />
        <SkeletonBlock :lines="4" height="1.25rem" />
      </div>

      <ErrorState v-else-if="state === 'error' && error" :message="error.message" @retry="retry" />

      <EmptyState
        v-else-if="state === 'success' && items.length === 0"
        title="Nothing saved yet"
        description="Use the bookmark button on any scholarship card to build your shortlist."
      >
        <RouterLink to="/discover" class="button-primary">Browse scholarships</RouterLink>
      </EmptyState>

      <div v-else class="card-grid">
        <ScholarshipCard
          v-for="item in items"
          :key="item.scholarship_id"
          :scholarship="{ ...item, deadline: item.deadline ?? item.timeline?.application_deadline ?? null }"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.saved-inner {
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
  margin: 0 0 var(--space-5);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-line);
}

.dropped-note {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  letter-spacing: 0.05em;
  color: var(--color-sem-unknown);
  margin-bottom: var(--space-4);
}

.skeleton-list,
.card-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
