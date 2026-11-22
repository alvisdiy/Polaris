<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GlobalSearch from './GlobalSearch.vue'
import ThemeToggle from './ThemeToggle.vue'
import { useCompare } from '../stores/compare'
import { useTheme } from '../stores/theme'

defineEmits<{ (e: 'open-menu'): void }>()

const route = useRoute()
const router = useRouter()
const { ids } = useCompare()
const { theme } = useTheme()

const links = [
  { to: '/discover', label: 'Browse' },
  { to: '/match', label: 'Match profile' },
  { to: '/compare', label: 'Compare' },
  { to: '/saved', label: 'Saved' },
  { to: '/about', label: 'About' },
]

const searchQuery = ref('')

function submitSearch() {
  if (!searchQuery.value.trim()) return
  router.push({ path: '/discover', query: { q: searchQuery.value.trim() } })
}

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<template>
  <header class="nav">
    <div class="nav-inner">
      <RouterLink to="/" class="wordmark" aria-label="Polaris home">Polaris</RouterLink>

      <nav class="links" aria-label="Primary">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="link"
          :class="{ 'link-active': isActive(link.to) }"
          :aria-current="isActive(link.to) ? 'page' : undefined"
        >
          {{ link.label }}
          <span v-if="link.to === '/compare' && ids.length" class="count-badge">{{ ids.length }}</span>
        </RouterLink>
      </nav>

      <div class="actions">
        <GlobalSearch v-model="searchQuery" @submit="submitSearch" />
        <ThemeToggle :theme="theme" />
        <button type="button" class="menu-button" aria-label="Open menu" @click="$emit('open-menu')">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: var(--z-nav);
  background: color-mix(in srgb, var(--color-paper) 88%, transparent);
  backdrop-filter: blur(10px) saturate(120%);
  border-bottom: 1px solid var(--color-line-strong);
}

.nav-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: 0 var(--space-5);
  height: 4.5rem;
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.wordmark {
  font-family: var(--font-display);
  font-size: 1.55rem;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--color-ink);
  text-decoration: none;
  display: inline-flex;
  align-items: baseline;
  gap: 0.4rem;
}

.wordmark::before {
  content: '';
  width: 0.5rem;
  height: 0.5rem;
  background: var(--color-brand);
  display: inline-block;
  transform: translateY(-0.55rem);
}

.wordmark:hover {
  color: var(--color-ink);
}

.links {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.link {
  position: relative;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  text-decoration: none;
  padding: 0.35rem 0;
}

.link::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--color-brand);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--motion-fast);
}

.link:hover {
  color: var(--color-ink);
}

.link:hover::after,
.link-active::after {
  transform: scaleX(1);
}

.link-active {
  color: var(--color-ink);
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.15rem;
  height: 1.15rem;
  margin-left: 0.35rem;
  padding: 0 0.25rem;
  border-radius: var(--radius-pill);
  background: var(--color-brand);
  color: var(--color-on-brand);
  font-size: 0.7rem;
  letter-spacing: 0;
}

.actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.menu-button {
  display: none;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-ink);
}

.menu-button:hover {
  border-color: var(--color-ink);
}

@media (max-width: 900px) {
  .links {
    display: none;
  }

  .menu-button {
    display: inline-flex;
  }

  .nav-inner {
    height: 4rem;
    gap: var(--space-4);
  }
}
</style>
