<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useCompare } from '../stores/compare'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const route = useRoute()
const { ids } = useCompare()

const sheetRef = ref<HTMLElement | null>(null)
let trigger: HTMLElement | null = null

const links = [
  { to: '/discover', label: 'Browse' },
  { to: '/match', label: 'Match profile' },
  { to: '/compare', label: 'Compare' },
  { to: '/saved', label: 'Saved' },
  { to: '/about', label: 'About' },
]

watch(
  () => props.open,
  async (open) => {
    if (open) {
      trigger = document.activeElement as HTMLElement | null
      document.body.style.overflow = 'hidden'
      await nextTick()
      sheetRef.value?.querySelector<HTMLElement>('a, button')?.focus()
    } else {
      document.body.style.overflow = ''
      trigger?.focus()
      trigger = null
    }
  },
)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key === 'Tab' && sheetRef.value) {
    const focusables = sheetRef.value.querySelectorAll<HTMLElement>('a[href], button')
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }
}

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="overlay" @click.self="emit('close')">
        <nav
          ref="sheetRef"
          class="sheet"
          aria-label="Mobile navigation"
          @keydown="onKeydown"
        >
          <div class="sheet-head">
            <span class="wordmark">Polaris</span>
            <button type="button" class="close-button" aria-label="Close menu" @click="emit('close')">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <path d="m4 4 10 10M14 4 4 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
            </button>
          </div>
          <ul>
            <li v-for="link in links" :key="link.to">
              <RouterLink
                :to="link.to"
                class="sheet-link"
                :class="{ 'sheet-link-active': isActive(link.to) }"
                :aria-current="isActive(link.to) ? 'page' : undefined"
                @click="emit('close')"
              >
                {{ link.label }}
                <span v-if="link.to === '/compare' && ids.length" class="count-badge">{{ ids.length }}</span>
              </RouterLink>
            </li>
          </ul>
        </nav>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-sheet);
  background: color-mix(in srgb, var(--color-ink) 45%, transparent);
}

.sheet {
  position: absolute;
  inset: 0 0 auto 0;
  background: var(--color-paper);
  border-bottom: 1px solid var(--color-line-strong);
  padding: var(--space-4) var(--space-5) var(--space-5);
  animation: drop var(--motion-sheet) both;
}

@keyframes drop {
  from {
    transform: translateY(-100%);
  }
  to {
    transform: none;
  }
}

.sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-line);
  margin-bottom: var(--space-3);
}

.sheet-head .wordmark {
  font-family: var(--font-display);
  font-size: 1.35rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--color-ink);
  text-decoration: none;
}

.close-button {
  width: 42px;
  height: 42px;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-ink);
}

.sheet-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-line);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--color-ink-secondary);
  text-decoration: none;
}

.sheet-link-active {
  color: var(--color-ink);
  border-bottom-color: var(--color-brand);
}

.count-badge {
  background: var(--color-brand);
  color: #fff;
  border-radius: var(--radius-pill);
  padding: 0 0.35rem;
  font-size: 0.62rem;
}
</style>
