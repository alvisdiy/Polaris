<script setup lang="ts">
const sections = [
  {
    id: 'collection',
    title: 'How data is collected',
    body: [
      'Polaris explores official provider websites: government scholarship portals, university pages, and established foundations. For each country, the engine runs bounded searches, reads candidate pages, and verifies that a site is an official provider before recording scholarships from it.',
      'Pages that only aggregate or list other organizations\u2019 scholarships are held to stricter checks, so an aggregator is never presented as the official provider of a program.',
    ],
  },
  {
    id: 'provenance',
    title: 'Sources and provenance',
    body: [
      'Every scholarship record keeps the link to the official page it was captured from. Requirements, benefits, and deadlines come from that page; when the source does not publish a detail, the record says so instead of filling the gap.',
      'Providers that share one domain are consolidated so the same organization does not appear as several providers, and duplicate scholarship records for the same program are merged into a single canonical record with version history.',
    ],
  },
  {
    id: 'freshness',
    title: 'Deadlines and freshness',
    body: [
      'Each record carries a deadline state. Active means the source published a deadline that is still in the future. Rolling means the program accepts applications on an ongoing basis. Unknown means the source does not state a deadline; Polaris never invents one. Expired records are kept as an archive and are never shown as current opportunities.',
    ],
  },
  {
    id: 'matching',
    title: 'How matching works',
    body: [
      'The matching engine scores your profile against each approved scholarship using weighted criteria: target country, degree, fields of study, GPA, language scores, research, work, leadership, and funding preference. Each result lists the strengths and gaps behind its score.',
      'Scores are deterministic: the same profile and the same knowledge base always produce the same ranking. A score describes how well your profile fits the stated requirements. It is not a prediction of admission, and Polaris does not make admission decisions.',
    ],
  },
  {
    id: 'limits',
    title: 'What Polaris does not do',
    body: [
      'Polaris does not accept applications on behalf of providers, does not charge students, and does not publish scholarship facts it cannot trace to an official source. Always confirm details on the official page before applying; the official provider is the final authority on its own program.',
    ],
  },
]
</script>

<template>
  <div class="about">
    <div class="about-inner">
      <header class="page-head">
        <h1>About Polaris</h1>
        <p class="page-sub">
          Polaris is a scholarship intelligence platform. It collects scholarships from official
          sources, keeps the evidence, and helps you find where you fit.
        </p>
      </header>

      <div class="body">
        <nav class="toc" aria-label="On this page">
          <h2>On this page</h2>
          <ul>
            <li v-for="section in sections" :key="section.id">
              <a :href="`#${section.id}`">{{ section.title }}</a>
            </li>
          </ul>
        </nav>

        <article class="sections">
          <section v-for="section in sections" :key="section.id" class="section">
            <h2 :id="section.id">{{ section.title }}</h2>
            <p v-for="(paragraph, index) in section.body" :key="index">{{ paragraph }}</p>
          </section>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.about-inner {
  max-width: 62rem;
  margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-8);
}

.page-head h1 {
  font-family: var(--font-display);
  font-size: clamp(2.2rem, 4.5vw, 3.4rem);
  letter-spacing: -0.035em;
  margin: 0 0 var(--space-3);
  max-width: 22ch;
}

.page-sub {
  font-size: var(--font-size-lg);
  color: var(--color-ink-secondary);
  max-width: 56ch;
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-line-strong);
  margin-bottom: var(--space-6);
}

.body {
  display: grid;
  grid-template-columns: 14rem minmax(0, 1fr);
  gap: var(--space-7);
  align-items: start;
}

.toc {
  position: sticky;
  top: 5.5rem;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.toc a {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  text-decoration: none;
  padding: 0.25rem 0;
  border-left: 2px solid transparent;
  padding-left: 0.6rem;
}

.toc a:hover {
  color: var(--color-brand);
  border-left-color: var(--color-brand);
}

.sections {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.section h2 {
  font-family: var(--font-display);
  font-size: 1.5rem;
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-line);
}

.section p,
.section li {
  color: var(--color-ink-secondary);
  font-size: var(--font-size-sm);
}

@media (max-width: 900px) {
  .body {
    grid-template-columns: 1fr;
  }

  .toc {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
