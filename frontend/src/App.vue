<script setup lang="ts">
import { ref } from 'vue'
import NavBar from './components/NavBar.vue'
import FooterBar from './components/FooterBar.vue'
import MobileMenuSheet from './components/MobileMenuSheet.vue'

const menuOpen = ref(false)
</script>

<template>
  <a class="skip-link" href="#main-content">Skip to content</a>
  <NavBar @open-menu="menuOpen = true" />
  <MobileMenuSheet :open="menuOpen" @close="menuOpen = false" />
  <main id="main-content" class="app-main" tabindex="-1">
    <RouterView />
  </main>
  <FooterBar />
</template>

<style scoped>
.app-main {
  min-height: calc(100dvh - 8rem);
}

/* The skip link focuses <main> programmatically; the ring would appear around
   the whole page, so the target stays silently focusable. */
.app-main:focus {
  outline: none;
}
</style>
