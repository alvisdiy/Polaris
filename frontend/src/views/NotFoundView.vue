<script setup lang="ts">
</script>

<template>
  <div class="not-found">
    <div class="inner">
      <p class="code" aria-hidden="true">404</p>
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
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--color-brand);
  margin: 0 0 var(--space-2);
}

.inner h1 {
  font-family: var(--font-display);
  font-size: clamp(2rem, 5vw, 3rem);
  letter-spacing: -0.03em;
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
