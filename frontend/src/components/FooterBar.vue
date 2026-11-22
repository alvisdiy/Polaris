<script setup lang="ts">
const year = new Date().getFullYear()
</script>

<template>
  <footer class="footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <span class="wordmark">Polaris</span>
        <p class="method-note">
          Scholarship data is collected automatically from official provider websites. Always
          confirm details on the official page before applying.
        </p>
      </div>
      <nav class="footer-links" aria-label="Footer">
        <RouterLink to="/discover">Browse</RouterLink>
        <RouterLink to="/match">Match profile</RouterLink>
        <RouterLink to="/about">About and method</RouterLink>
        <RouterLink to="/privacy">Privacy</RouterLink>
        <RouterLink to="/terms">Terms</RouterLink>
      </nav>
    </div>
    <p class="copyright">Polaris {{ year }}</p>
  </footer>
</template>

<style scoped>
.footer {
  border-top: 1px solid var(--color-line-strong);
  margin-top: var(--space-8);
  padding: var(--space-6) 0 var(--space-5);
  background: var(--color-paper);
}

.footer-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: 0 var(--space-5);
  display: grid;
  grid-template-columns: minmax(12rem, 1fr) minmax(16rem, 1.4fr) auto;
  gap: var(--space-6);
  align-items: start;
}

.footer-brand .wordmark {
  font-family: var(--font-display);
  font-size: 1.35rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--color-ink);
  text-decoration: none;
}

.method-note {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  max-width: 42ch;
}

.footer-links {
  display: flex;
  gap: var(--space-4);
  justify-content: flex-end;
}

.footer-links a {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  text-decoration: none;
}

.footer-links a:hover {
  color: var(--color-brand);
}

.copyright {
  grid-column: 1 / -1;
  margin: var(--space-5) 0 0;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-line);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  letter-spacing: var(--tracking-meta);
  text-transform: uppercase;
  color: var(--color-ink-secondary);
}

@media (max-width: 820px) {
  .footer-inner {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }

  .footer-links {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
