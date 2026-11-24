<script setup lang="ts">
const year = new Date().getFullYear()
</script>

<template>
  <footer class="footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <span class="wordmark">
          <svg class="star" width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M12 1.5c.8 4.9 2 6.9 3 7.9s3 2.2 7.9 3v1.2c-4.9.8-6.9 2-7.9 3s-2.2 3-3 7.9h-1.2c-.8-4.9-2-6.9-3-7.9s-3-2.2-7.9-3v-1.2c4.9-.8 6.9-2 7.9-3s2.2-3 3-7.9Z"
              fill="currentColor"
            />
          </svg>
          Polaris
        </span>
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
        <RouterLink to="/review">Review queue (operators)</RouterLink>
      </nav>
    </div>
    <p class="copyright">Polaris {{ year }}</p>
  </footer>
</template>

<style scoped>
.footer {
  border-top: 1px solid var(--color-line);
  margin-top: var(--space-8);
  padding: var(--space-6) 0 var(--space-5);
  background: color-mix(in srgb, var(--color-surface) 62%, transparent);
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
  font-size: 1.4rem;
  font-weight: 400;
  letter-spacing: -0.01em;
  color: var(--color-ink);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.footer-brand .star {
  color: var(--color-star);
}

.method-note {
  margin: var(--space-2) 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-ink-secondary);
  max-width: 42ch;
}

.footer-links {
  display: flex;
  gap: var(--space-4);
  justify-content: flex-end;
  flex-wrap: wrap;
}

.footer-links a {
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  text-decoration: none;
  transition: color var(--motion-fast);
}

.footer-links a:hover {
  color: var(--color-brand);
}

.copyright {
  max-width: none;
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
