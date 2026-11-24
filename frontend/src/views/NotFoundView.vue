<script setup lang="ts">
</script>

<template>
  <div class="not-found">
    <div class="inner">
      <p class="code" aria-hidden="true">
        <svg class="star" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 1.5c.8 4.9 2 6.9 3 7.9s3 2.2 7.9 3v1.2c-4.9.8-6.9 2-7.9 3s-2.2 3-3 7.9h-1.2c-.8-4.9-2-6.9-3-7.9s-3-2.2-7.9-3v-1.2c4.9-.8 6.9-2 7.9-3s2.2-3 3-7.9Z"
            fill="currentColor"
          />
        </svg>
        Error 404 · off the chart
      </p>
      <h1>Page not found</h1>
      <p class="sub">The page you are looking for does not exist or has moved.</p>
      <div class="actions">
        <RouterLink to="/" class="button-primary">Go to the homepage</RouterLink>
        <RouterLink to="/discover" class="button-secondary">Browse scholarships</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.not-found {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-5);
}

.inner {
  max-width: 34rem;
  text-align: left;
  border-left: 3px solid var(--color-brand);
  padding-left: var(--space-5);
}

.code {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--color-brand);
  margin: 0 0 var(--space-2);
}

.star {
  color: var(--color-star);
}

.inner h1 {
  font-family: var(--font-display);
  font-size: clamp(2.4rem, 5.5vw, 3.4rem);
  letter-spacing: -0.02em;
  margin: 0 0 var(--space-3);
}

.sub {
  color: var(--color-ink-secondary);
  margin: 0 0 var(--space-5);
}

.actions {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}
</style>
