<script setup lang="ts">
import HeroGlobe from '../components/HeroGlobe.vue'
import { onMounted } from 'vue'
import { useScholarshipList } from '../api/composables'
import ScholarshipCard from '../components/ScholarshipCard.vue'
import ErrorState from '../components/ErrorState.vue'
import SkeletonBlock from '../components/SkeletonBlock.vue'

const { data, state, error, fetchList } = useScholarshipList()

onMounted(() => {
  fetchList({ limit: 3 })
})

async function retry() {
  await fetchList({ limit: 3 })
}
</script>

<template>
  <div>
    <section class="hero">
      <div class="hero-inner">
        <p class="hero-eyebrow">Scholarship intelligence · live registry</p>
        <h1 class="hero-title">
          International scholarships, <em class="hero-em">verified</em> from the official
          source.
        </h1>
        <div class="hero-copy">
          <p class="hero-sub">
            Browse a knowledge base collected from official provider websites, or let Polaris
            match your profile and explain every result.
          </p>
          <div class="hero-actions">
            <RouterLink to="/discover" class="button-primary">Browse scholarships</RouterLink>
            <RouterLink to="/match" class="button-secondary">Match my profile</RouterLink>
          </div>
        </div>
        <div class="hero-figure">
          <HeroGlobe />
        </div>
      </div>
    </section>

    <section class="how" aria-labelledby="how-heading">
      <div class="section-inner how-inner">
        <h2 id="how-heading" class="how-title">How Polaris works</h2>
        <div class="how-steps">
          <div class="how-step">
            <h3>Collected from official sources</h3>
            <p>
              The Polaris engine gathers scholarship pages from official provider websites and
              records where every fact came from.
            </p>
            <RouterLink to="/about" class="how-link">How collection works</RouterLink>
          </div>
          <div class="how-step">
            <h3>Every record keeps its source</h3>
            <p>
              Each scholarship carries a link to its official page and a freshness status, so
              you always know what you are looking at.
            </p>
            <RouterLink to="/about" class="how-link">About trust and provenance</RouterLink>
          </div>
          <div class="how-step">
            <h3>Matching with explicit reasons</h3>
            <p>
              Enter your profile once and the matching engine ranks scholarships by transparent
              criteria, listing strengths and gaps for every result.
            </p>
            <RouterLink to="/about" class="how-link">How matching works</RouterLink>
          </div>
        </div>
      </div>
    </section>

    <section class="examples" aria-labelledby="examples-heading">
      <div class="section-inner">
        <div class="examples-head">
          <h2 id="examples-heading">From the knowledge base</h2>
          <RouterLink to="/discover" class="examples-link">See all in Browse</RouterLink>
        </div>

        <div v-if="state === 'loading'" class="examples-grid">
          <SkeletonBlock :lines="4" height="1.25rem" />
          <SkeletonBlock :lines="4" height="1.25rem" />
          <SkeletonBlock :lines="4" height="1.25rem" />
        </div>

        <ErrorState
          v-else-if="state === 'error' && error"
          :message="error.message"
          @retry="retry"
        />

        <template v-else-if="data && data.results.length">
          <div class="examples-grid">
            <ScholarshipCard
              v-for="item in data.results"
              :key="item.scholarship_id"
              :scholarship="item"
            />
          </div>
        </template>

        <p v-else class="examples-empty">
          The knowledge base is empty or being updated. Check back soon.
        </p>
      </div>
    </section>

    <section class="trust" aria-labelledby="trust-heading">
      <div class="section-inner">
        <h2 id="trust-heading">What verified means here</h2>
        <div class="trust-body">
          <p>
            Every scholarship in Polaris points to the official page it came from. When a source
            does not publish a deadline, Polaris says so instead of guessing. Records past their
            deadline are marked as archive and never presented as current opportunities.
          </p>
          <p>
            Matching scores are computed from explicit criteria against your profile. They
            explain how well you fit the stated requirements. They are not a prediction of
            admission.
          </p>
          <RouterLink to="/about" class="trust-link">Read about the method</RouterLink>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  overflow: hidden;
  border-bottom: 1px solid var(--color-line-strong);
  background:
    linear-gradient(180deg, var(--color-surface) 0%, var(--color-paper) 100%);
}

.hero-inner {
  position: relative;
  z-index: 1;
  max-width: var(--container-max);
  margin: 0 auto;
  padding: clamp(2.75rem, 6vw, 4.75rem) var(--space-5) clamp(2.75rem, 6vw, 4.75rem);
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 4fr);
  grid-template-areas:
    'eyebrow eyebrow'
    'title figure'
    'copy figure';
  grid-template-rows: auto auto 1fr;
  column-gap: var(--space-7);
  align-items: start;
}

.hero-figure {
  grid-area: figure;
  position: relative;
  align-self: center;
  min-height: 24rem;
  height: 100%;
}

.hero-copy {
  grid-area: copy;
  align-self: end;
  padding-top: var(--space-2);
}

.hero-eyebrow {
  grid-area: eyebrow;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--color-brand);
  margin: 0 0 var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-line);
}

.hero-title {
  grid-area: title;
  font-family: var(--font-display);
  font-size: clamp(2.5rem, 5.8vw, 4.6rem);
  line-height: 1.06;
  letter-spacing: -0.02em;
  font-weight: 400;
  margin: 0 0 var(--space-5);
  max-width: 18ch;
}

.hero-em {
  font-style: italic;
  color: var(--color-brand);
}

.hero-title::after {
  content: '';
  display: block;
  width: 4.5rem;
  height: 2px;
  background: var(--color-brand);
  box-shadow: 0 0 10px var(--color-brand);
  margin-top: var(--space-5);
}

.hero-sub {
  font-size: 1.05rem;
  color: var(--color-ink-secondary);
  max-width: 46ch;
  margin: 0 0 var(--space-6);
}

.hero-actions {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.how,
.examples,
.trust {
  border-bottom: 1px solid var(--color-line);
}

.section-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: clamp(2.5rem, 5vw, 4.5rem) var(--space-5);
}

.section-inner > h2 {
  font-size: clamp(1.6rem, 2.6vw, 2.2rem);
  letter-spacing: -0.02em;
  margin-bottom: var(--space-6);
}

.how-inner {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: var(--space-7);
  align-items: start;
}

.how-title {
  position: sticky;
  top: 6rem;
  margin: 0;
}

.how-steps {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-5);
  counter-reset: step;
}

.how-step {
  position: relative;
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-line-strong);
  counter-increment: step;
}

.how-step::before {
  content: counter(step, decimal-leading-zero);
  display: block;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--color-brand);
  margin-bottom: var(--space-2);
}

.how-step h3 {
  font-family: var(--font-display);
  font-size: 1.18rem;
  font-weight: 500;
  margin: 0 0 var(--space-2);
}

.how-step p {
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-3);
}

.how-link,
.examples-link,
.trust-link {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink);
  text-decoration: none;
}

.how-link::after,
.examples-link::after,
.trust-link::after {
  content: ' →';
  color: var(--color-brand);
}

.how-link:hover,
.examples-link:hover,
.trust-link:hover {
  color: var(--color-brand);
}

.examples-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.examples-head h2 {
  margin: 0;
}

.examples-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-4);
}

.examples-grid:has(> :nth-child(2)) {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.examples-grid:has(> :nth-child(3):last-child) {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}

.examples-grid:has(> :nth-child(3):last-child) > :first-child {
  grid-row: 1 / span 2;
}

.examples-empty {
  padding: var(--space-6);
  border: 1px dashed var(--color-line-strong);
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
}

.trust-body {
  max-width: 62ch;
  font-size: var(--font-size-lg);
  color: var(--color-ink-secondary);
}

@media (max-width: 900px) {
  .hero-inner {
    grid-template-columns: 1fr;
    grid-template-areas:
      'eyebrow'
      'title'
      'copy';
    gap: var(--space-4);
  }

  .hero-figure {
    display: none;
  }

  .how-inner {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }

  .how-title {
    position: static;
  }

  .examples-grid,
  .examples-grid:has(> :nth-child(2)),
  .examples-grid:has(> :nth-child(3):last-child) {
    grid-template-columns: 1fr;
  }

  .examples-grid:has(> :nth-child(3):last-child) > :first-child {
    grid-row: auto;
  }
}
</style>
