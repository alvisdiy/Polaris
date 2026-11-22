<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

interface Section {
  id: string
  title: string
  body: string[]
}

interface LegalPage {
  title: string
  sub: string
  updated: string
  sections: Section[]
}

const PAGES: Record<string, LegalPage> = {
  privacy: {
    title: 'Privacy',
    sub: 'Polaris has no accounts, no analytics, and no advertising. This page lists the only data the product touches, and where it lives.',
    updated: 'Last updated 20 November 2026',
    sections: [
      {
        id: 'browser',
        title: 'What is stored in your browser',
        body: [
          'Three values are kept in this browser\u2019s local storage, and nothing else: your shortlist, the profile you last used for matching, and your theme choice. They are stored under the keys polaris.shortlist.v1, polaris.profile.v1, and polaris.theme.',
          'Local storage is readable by scripts on this site and by anyone using this browser profile. It is not sent to Polaris unless a feature needs it, described below.',
        ],
      },
      {
        id: 'sent',
        title: 'What is sent to the server',
        body: [
          'Searching and browsing send your keyword, country, degree, and page to the scholarship API so it can return matching records. Running a match sends the profile fields you entered. Each request is handled to produce the response and is not attached to an account, because Polaris does not have accounts.',
          'The scholarship knowledge base itself is collected from public official provider pages. It contains information about programs and organizations, not about visitors.',
        ],
      },
      {
        id: 'third-parties',
        title: 'Third parties',
        body: [
          'Typefaces are loaded from Google Fonts, which means your browser requests them from Google\u2019s servers and Google may see your IP address and user agent. This is the only third-party request the site makes.',
          'There is no analytics script, no tracking pixel, no advertising network, and no session recording. Opening a scholarship\u2019s official page takes you to the provider\u2019s site, where that provider\u2019s own privacy policy applies.',
        ],
      },
      {
        id: 'control',
        title: 'Removing your data',
        body: [
          'Removing a scholarship from Saved, or clearing the saved profile on the Match page, deletes those entries immediately. Clearing site data for this domain in your browser removes all three local values; the theme then follows your operating system preference again.',
        ],
      },
    ],
  },
  terms: {
    title: 'Terms of use',
    sub: 'Polaris is an informational tool for finding scholarships. It is not a scholarship provider, an agent, or an admissions adviser.',
    updated: 'Last updated 20 November 2026',
    sections: [
      {
        id: 'service',
        title: 'What this service is',
        body: [
          'Polaris collects scholarship records from official provider websites and lets you browse, save, compare, and score them against a profile you enter. Using the site is free and requires no account.',
          'Polaris does not accept or forward applications, does not communicate with providers on your behalf, and does not charge students at any point.',
        ],
      },
      {
        id: 'accuracy',
        title: 'Accuracy and the official page',
        body: [
          'Records are collected automatically and can lag behind a provider\u2019s current page. Where a source does not state a detail, the record says so rather than filling the gap, and records past their deadline are marked as archive.',
          'The official provider page is the final authority on every program. Confirm eligibility, deadlines, and benefits there before applying, and treat a Polaris record as a pointer to that page rather than a substitute for it.',
        ],
      },
      {
        id: 'matching',
        title: 'Matching scores',
        body: [
          'A match score describes how well the profile you entered fits the requirements a provider states, using explicit weighted criteria. It is not a prediction of admission and does not influence any provider\u2019s decision.',
        ],
      },
      {
        id: 'availability',
        title: 'Availability and changes',
        body: [
          'The service is provided as it is, without warranty of uninterrupted availability or completeness. Pages, filters, and these terms may change as the knowledge base and the product develop; the date above records the current version.',
        ],
      },
    ],
  },
}

const route = useRoute()
const page = computed<LegalPage>(() => PAGES[String(route.name)] ?? PAGES.privacy)
</script>

<template>
  <div class="legal">
    <div class="legal-inner">
      <header class="page-head">
        <h1>{{ page.title }}</h1>
        <p class="page-sub">{{ page.sub }}</p>
        <p class="updated">{{ page.updated }}</p>
      </header>

      <article class="sections">
        <section v-for="section in page.sections" :key="section.id" class="section">
          <h2 :id="section.id">{{ section.title }}</h2>
          <p v-for="(paragraph, index) in section.body" :key="index">{{ paragraph }}</p>
        </section>
      </article>
    </div>
  </div>
</template>

<style scoped>
.legal-inner {
  max-width: 46rem;
  margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-8);
}

.page-head h1 {
  font-family: var(--font-display);
  font-size: clamp(2.2rem, 4.5vw, 3.2rem);
  letter-spacing: -0.035em;
  margin: 0 0 var(--space-3);
}

.page-sub {
  font-size: var(--font-size-lg);
  color: var(--color-ink-secondary);
  max-width: 54ch;
  margin: 0 0 var(--space-3);
}

.updated {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-6);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-line-strong);
}

.sections {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.section h2 {
  font-family: var(--font-display);
  font-size: 1.4rem;
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-line);
}

.section p {
  color: var(--color-ink-secondary);
  font-size: var(--font-size-sm);
}
</style>
