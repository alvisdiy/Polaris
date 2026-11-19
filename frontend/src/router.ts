import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
  { path: '/discover', name: 'discover', component: () => import('./views/DiscoverView.vue') },
  {
    path: '/scholarships/:id',
    name: 'scholarship-detail',
    component: () => import('./views/ScholarshipDetailView.vue'),
  },
  { path: '/match', name: 'match', component: () => import('./views/MatchView.vue') },
  { path: '/compare', name: 'compare', component: () => import('./views/CompareView.vue') },
  { path: '/saved', name: 'saved', component: () => import('./views/SavedView.vue') },
  { path: '/about', name: 'about', component: () => import('./views/AboutView.vue') },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('./views/NotFoundView.vue') },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
})
