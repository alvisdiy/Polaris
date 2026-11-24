import { ref } from 'vue'

/*
 * Operator credentials for the review surface: the shared admin token
 * and the reviewer's actor name. Both live in localStorage on the
 * operator's own browser — there are no accounts or sessions in
 * Polaris, and the token identifies an operator, not a person; the
 * actor string is what lands on the audit trail as "who claimed to
 * review". Signing out clears both.
 */

const TOKEN_KEY = 'polaris.review.token'
const ACTOR_KEY = 'polaris.review.actor'

function read(key: string): string {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

export const reviewToken = ref(read(TOKEN_KEY))
export const reviewActor = ref(read(ACTOR_KEY))

export const isSignedIn = () => reviewToken.value.trim() !== '' && reviewActor.value.trim() !== ''

export function signIn(token: string, actor: string) {
  reviewToken.value = token.trim()
  reviewActor.value = actor.trim()
  try {
    localStorage.setItem(TOKEN_KEY, reviewToken.value)
    localStorage.setItem(ACTOR_KEY, reviewActor.value)
  } catch {
    /* storage unavailable: the refs still hold the values for this session */
  }
}

export function signOut() {
  reviewToken.value = ''
  reviewActor.value = ''
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ACTOR_KEY)
  } catch {
    /* nothing to clear */
  }
}
