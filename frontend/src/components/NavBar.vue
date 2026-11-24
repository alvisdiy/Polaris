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
const { theme, toggle } = useTheme()

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
      <RouterLink to="/" class="wordmark" aria-label="Polaris home">
        <svg class="star" width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M12 1.5c.8 4.9 2 6.9 3 7.9s3 2.2 7.9 3v1.2c-4.9.8-6.9 2-7.9 3s-2.2 3-3 7.9h-1.2c-.8-4.9-2-6.9-3-7.9s-3-2.2-7.9-3v-1.2c4.9-.8 6.9-2 7.9-3s2.2-3 3-7.9Z"
            fill="currentColor"
          />
        </svg>
        Polaris
      </RouterLink>

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
        <ThemeToggle :theme="theme" @toggle="toggle" />
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
  background: color-mix(in srgb, var(--color-paper) 78%, transparent);
  backdrop-filter: blur(14px) saturate(140%);
  border-bottom: 1px solid var(--color-line);
}

.nav-inner {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: 0 var(--space-5);
  height: 4.25rem;
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.wordmark {
  font-family: var(--font-display);
  font-size: 1.6rem;
  font-weight: 400;
  letter-spacing: -0.01em;
  color: var(--color-ink);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  line-height: 1;
}

.star {
  color: var(--color-star);
  flex-shrink: 0;
  transition: transform var(--motion-fast);
}

.wordmark:hover .star {
  transform: rotate(90deg) scale(1.1);
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
  transition: color var(--motion-fast);
}

.link::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  border-radius: 1px;
  background: var(--color-brand);
  box-shadow: 0 0 8px var(--color-brand);
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
  transition: border-color var(--motion-fast);
}

.menu-button:hover {
  border-color: var(--color-brand);
  color: var(--color-brand);
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
