import { createRouter, createWebHistory } from 'vue-router'

const DEFAULT_DESCRIPTION =
  "Polaris is a scholarship intelligence platform. Every record is traced to the provider's own page, with the deadline and funding the page actually states."

const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: 'Polaris | Scholarship Intelligence', description: DEFAULT_DESCRIPTION },
  },
  {
    path: '/discover',
    name: 'discover',
    component: () => import('./views/DiscoverView.vue'),
    meta: {
      title: 'Browse scholarships | Polaris',
      description:
        'Browse scholarships collected from official provider pages, with the deadline and funding kept as the source states them.',
    },
  },
  {
    path: '/scholarships/:id',
    name: 'scholarship-detail',
    component: () => import('./views/ScholarshipDetailView.vue'),
    meta: {
      title: 'Scholarship details | Polaris',
      description:
        'A scholarship record with its official source, deadline state, requirements, benefits, and the provenance of every field.',
    },
  },
  {
    path: '/match',
    name: 'match',
    component: () => import('./views/MatchView.vue'),
    meta: {
      title: 'Match your profile | Polaris',
      description:
        'Rank scholarships against your profile with explicit criteria, strengths, and gaps for every result.',
    },
  },
  {
    path: '/compare',
    name: 'compare',
    component: () => import('./views/CompareView.vue'),
    meta: {
      title: 'Compare scholarships | Polaris',
      description: 'Compare up to four scholarships side by side on deadline, funding, and requirements.',
    },
  },
  {
    path: '/saved',
    name: 'saved',
    component: () => import('./views/SavedView.vue'),
    meta: {
      title: 'Saved scholarships | Polaris',
      description: 'Your shortlist, stored in this browser only and never linked to an account.',
    },
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('./views/AboutView.vue'),
    meta: {
      title: 'About and method | Polaris',
      description:
        'How Polaris collects scholarships, keeps provenance, treats deadlines it cannot verify, and scores a profile.',
    },
  },
  {
    path: '/privacy',
    name: 'privacy',
    component: () => import('./views/LegalView.vue'),
    meta: {
      title: 'Privacy | Polaris',
      description:
        'What Polaris stores in your browser, what it sends to the server, and the one third-party request the site makes.',
    },
  },
  {
    path: '/terms',
    name: 'terms',
    component: () => import('./views/LegalView.vue'),
    meta: {
      title: 'Terms of use | Polaris',
      description:
        'Polaris is an informational tool: the official provider page is authoritative, matching scores are not admission predictions.',
    },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('./views/ReviewView.vue'),
    meta: {
      title: 'Review queue | Polaris',
      description: 'Operator surface: the human publication gate for the catalogue.',
    },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('./views/NotFoundView.vue'),
    meta: { title: 'Page not found | Polaris', description: 'The page does not exist or has moved.' },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(_to, _from, savedPosition) {
    return savedPosition ?? { top: 0 }
  },
})

function setMetaTag(attribute: 'name' | 'property', key: string, content: string) {
  const tag = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`)
  if (tag) tag.content = content
}

/* The document shell keeps static tags for crawlers and link unfurlers; this
 * keeps them truthful after client-side navigation. */
router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'Polaris'
  const description =
    typeof to.meta.description === 'string' ? to.meta.description : DEFAULT_DESCRIPTION
  document.title = title
  setMetaTag('name', 'description', description)
  setMetaTag('property', 'og:title', title)
  setMetaTag('property', 'og:description', description)
})
