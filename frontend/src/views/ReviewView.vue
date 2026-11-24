<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  approveRecord,
  getReviewMetrics,
  getReviewPacket,
  getReviewQueue,
  patchRecord,
  rejectRecord,
  requestCorrection,
  type ReviewItemSummary,
  type ReviewMetrics,
  type ReviewPacket,
} from '../api/review'
import { ApiError } from '../api/client'
import { isSignedIn, reviewActor, reviewToken, signIn, signOut } from '../stores/reviewAuth'
import { formatDate } from '../lib/format'

/*
 * The reviewer surface. Until now curation ran through the API or CLI
 * only, which made human review — the publication gate the whole
 * catalogue depends on — the slowest step in the pipeline. This view is
 * a thin client over the existing review API: queue, packet, quality
 * report, corrections and decisions all come from the server, and every
 * rule (what blocks publication, what may be overridden) is enforced
 * there. Nothing here re-implements the gate.
 */

const DEGREES = ['Bachelor', 'Master', 'PhD', 'Exchange', 'Short Course']
const FUNDING_TYPES = ['Fully Funded', 'Partial Funded', 'Tuition Only']

const signedIn = ref(isSignedIn())
const tokenInput = ref('')
const actorInput = ref(reviewActor.value)

const queue = ref<ReviewItemSummary[]>([])
const queueTotal = ref(0)
const metrics = ref<ReviewMetrics | null>(null)
const packet = ref<ReviewPacket | null>(null)
const selectedId = ref<string | null>(null)

const loading = ref(false)
const detailLoading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')

const reason = ref('')
const evidenceUrl = ref('')
const overrideQuality = ref(false)

/* Correction form: prefilled from the packet, only diffs are sent. */
const fix = ref({ deadline: '', degree: '', funding_type: '', official_page_url: '', minimum_gpa: '' })
const fixReason = ref('')

const countryField = computed(() => packet.value?.quality.fields['country'])
const countryUnconfirmed = computed(
  () =>
    Boolean(packet.value?.identity.country_id) &&
    countryField.value?.quality === 'UNKNOWN',
)

function fail(err: unknown) {
  error.value = err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

async function loadQueue() {
  loading.value = true
  error.value = ''
  try {
    const [list, m] = await Promise.all([
      getReviewQueue(reviewToken.value, 'pending_review', 50, 0),
      getReviewMetrics(reviewToken.value),
    ])
    queue.value = list.results
    queueTotal.value = list.total
    metrics.value = m
  } catch (err) {
    fail(err)
  } finally {
    loading.value = false
  }
}

async function openRecord(id: string) {
  selectedId.value = id
  detailLoading.value = true
  error.value = ''
  notice.value = ''
  reason.value = ''
  evidenceUrl.value = ''
  overrideQuality.value = false
  fixReason.value = ''
  try {
    packet.value = await getReviewPacket(reviewToken.value, id)
    fix.value = {
      deadline: packet.value.timeline.application_deadline ?? '',
      degree: packet.value.eligibility.degree ?? '',
      funding_type: packet.value.eligibility.funding_type ?? '',
      official_page_url: packet.value.identity.official_url ?? '',
      minimum_gpa:
        packet.value.eligibility.minimum_gpa != null
          ? String(packet.value.eligibility.minimum_gpa)
          : '',
    }
  } catch (err) {
    packet.value = null
    fail(err)
  } finally {
    detailLoading.value = false
  }
}

async function afterAction(message: string) {
  notice.value = message
  packet.value = null
  selectedId.value = null
  await loadQueue()
}

async function doApprove() {
  if (!packet.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const outcome = await approveRecord(reviewToken.value, packet.value.scholarship_id, {
      actor: reviewActor.value,
      reason: reason.value.trim() || null,
      evidence_url: evidenceUrl.value.trim() || null,
      override_quality: overrideQuality.value,
    })
    await afterAction(`Published. The record is now live in the public catalogue (${outcome.new_state}).`)
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function doReject() {
  if (!packet.value || busy.value) return
  if (!reason.value.trim()) {
    error.value = 'A reason is required to reject a record.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await rejectRecord(reviewToken.value, packet.value.scholarship_id, {
      actor: reviewActor.value,
      reason: reason.value.trim(),
      evidence_url: evidenceUrl.value.trim() || null,
    })
    await afterAction('Rejected. The record stays out of the public catalogue.')
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function doRequestCorrection() {
  if (!packet.value || busy.value) return
  if (!reason.value.trim()) {
    error.value = 'A reason is required to send a record back for correction.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await requestCorrection(reviewToken.value, packet.value.scholarship_id, {
      actor: reviewActor.value,
      reason: reason.value.trim(),
      evidence_url: evidenceUrl.value.trim() || null,
    })
    await afterAction('Sent back for correction with your note attached.')
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function doConfirmCountry() {
  if (!packet.value?.identity.country_id || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await patchRecord(reviewToken.value, packet.value.scholarship_id, {
      actor: reviewActor.value,
      reason: 'Country confirmed against the official source page during review.',
      evidence_url: packet.value.identity.official_url,
      changes: { country_id: packet.value.identity.country_id },
      requeue: false,
    })
    notice.value = `Country confirmed as ${packet.value.identity.country}.`
    await openRecord(packet.value.scholarship_id)
    await loadQueue()
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function doSaveCorrection() {
  if (!packet.value || busy.value) return
  if (!fixReason.value.trim()) {
    error.value = 'A reason is required for a correction — it goes on the audit trail.'
    return
  }
  const p = packet.value
  const changes: Record<string, unknown> = {}
  if (fix.value.deadline !== (p.timeline.application_deadline ?? '')) {
    changes.deadline = fix.value.deadline || null
  }
  if (fix.value.degree !== (p.eligibility.degree ?? '')) changes.degree = fix.value.degree || null
  if (fix.value.funding_type !== (p.eligibility.funding_type ?? '')) {
    changes.funding_type = fix.value.funding_type || null
  }
  if (fix.value.official_page_url !== (p.identity.official_url ?? '')) {
    changes.official_page_url = fix.value.official_page_url || null
  }
  const gpa = fix.value.minimum_gpa.trim() === '' ? null : Number(fix.value.minimum_gpa)
  if (gpa !== p.eligibility.minimum_gpa) changes.minimum_gpa = gpa

  if (!Object.keys(changes).length) {
    error.value = 'Nothing changed yet — edit a field first.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await patchRecord(reviewToken.value, p.scholarship_id, {
      actor: reviewActor.value,
      reason: fixReason.value.trim(),
      evidence_url: evidenceUrl.value.trim() || null,
      changes,
    })
    notice.value = 'Correction saved. The record is re-queued for a second look.'
    await openRecord(p.scholarship_id)
    await loadQueue()
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

function submitSignIn() {
  if (!tokenInput.value.trim() || !actorInput.value.trim()) {
    error.value = 'Both the operator token and your reviewer name are required.'
    return
  }
  signIn(tokenInput.value, actorInput.value)
  signedIn.value = true
  void loadQueue()
}

function doSignOut() {
  signOut()
  signedIn.value = false
  queue.value = []
  packet.value = null
  metrics.value = null
}

function qualityClass(quality: string): string {
  if (quality === 'KNOWN') return 'q-known'
  if (quality === 'MISSING' || quality === 'CONFLICTING') return 'q-bad'
  if (quality === 'UNKNOWN') return 'q-unknown'
  return 'q-na'
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ') || '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

onMounted(() => {
  if (signedIn.value) void loadQueue()
})
</script>

<template>
  <main class="review-page">
    <header class="review-head">
      <div>
        <h1>Review queue</h1>
        <p class="lede">
          The publication gate. Nothing reaches the public catalogue until a reviewer approves it
          here — check the record against its official source, correct what is wrong, then decide.
        </p>
      </div>
      <div v-if="signedIn" class="head-actions">
        <span class="actor">Reviewing as <strong>{{ reviewActor }}</strong></span>
        <button type="button" class="button-secondary" @click="doSignOut">Sign out</button>
      </div>
    </header>

    <section v-if="!signedIn" class="signin card">
      <h2>Operator sign-in</h2>
      <p>
        Paste the operator token (the server's <code>POLARIS_ADMIN_TOKEN</code>) and your reviewer
        name. The name is recorded on the audit trail for every decision you make. Both are kept
        only in this browser.
      </p>
      <form @submit.prevent="submitSignIn">
        <label>
          Operator token
          <input v-model="tokenInput" type="password" autocomplete="off" required />
        </label>
        <label>
          Reviewer name
          <input v-model="actorInput" type="text" autocomplete="name" required />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button type="submit" class="button-primary">Open the queue</button>
      </form>
    </section>

    <template v-else>
      <section v-if="metrics" class="metrics" aria-label="Curation metrics">
        <div class="metric"><strong>{{ metrics.pending_review }}</strong><span>awaiting review</span></div>
        <div class="metric"><strong>{{ metrics.approved }}</strong><span>published</span></div>
        <div class="metric"><strong>{{ metrics.rejected }}</strong><span>rejected</span></div>
        <div class="metric"><strong>{{ metrics.needs_correction }}</strong><span>need correction</span></div>
        <div class="metric">
          <strong>{{ metrics.approval_rate != null ? `${Math.round(metrics.approval_rate * 100)}%` : '—' }}</strong>
          <span>approval rate</span>
        </div>
      </section>

      <p v-if="error" class="error banner" role="alert">
        {{ error }}
        <button type="button" class="button-secondary" @click="loadQueue">Retry</button>
      </p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>

      <div class="layout">
        <section class="queue card" aria-label="Records awaiting review">
          <h2>Pending <span class="count">{{ queueTotal }}</span></h2>
          <p v-if="loading" class="muted">Loading the queue…</p>
          <p v-else-if="!queue.length" class="muted">The queue is empty. Nothing awaits review.</p>
          <ul v-else class="queue-list">
            <li v-for="item in queue" :key="item.scholarship_id">
              <button
                type="button"
                class="queue-item"
                :class="{ selected: item.scholarship_id === selectedId }"
                @click="openRecord(item.scholarship_id)"
              >
                <span class="q-name">{{ item.scholarship_name }}</span>
                <span class="q-meta">
                  {{ item.provider_name ?? 'Unknown provider' }} · {{ item.country ?? 'Unknown country' }}
                </span>
                <span class="q-flags">
                  <span class="flag origin">{{ item.provenance_origin ?? 'unknown origin' }}</span>
                  <span v-if="item.extraction_confidence != null" class="flag">
                    {{ Math.round(item.extraction_confidence * 100) }}% confidence
                  </span>
                  <span v-for="f in item.blocking_fields" :key="`b-${f}`" class="flag blocking">
                    blocks: {{ f }}
                  </span>
                  <span v-for="f in item.conflicting_fields" :key="`c-${f}`" class="flag conflict">
                    conflict: {{ f }}
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        <section class="detail card" aria-label="Record under review">
          <p v-if="detailLoading" class="muted">Loading the reviewer packet…</p>
          <p v-else-if="!packet" class="muted">
            Pick a record from the queue to see its full packet: extracted facts, per-field quality,
            provenance and history.
          </p>

          <template v-else>
            <h2>{{ packet.identity.scholarship_name }}</h2>
            <p class="meta">
              {{ packet.identity.provider_name ?? 'Unknown provider' }} ·
              {{ packet.identity.country ?? 'Unknown country'
              }}<span v-if="packet.identity.university"> · {{ packet.identity.university }}</span>
              · status: {{ packet.extraction_status }}
            </p>
            <p class="meta">
              Source: {{ packet.identity.source_name ?? packet.identity.source_id }} ({{
                packet.identity.source_verification_state ?? 'unverified'
              }})
              ·
              <a
                v-if="packet.identity.official_url"
                :href="packet.identity.official_url"
                target="_blank"
                rel="noopener"
              >
                Open the official page
              </a>
            </p>

            <div class="verdict" :class="packet.quality.publishable ? 'ok' : 'blocked'">
              <strong>{{ packet.quality.publishable ? 'Publishable' : 'Blocked from publishing' }}</strong>
              <span v-if="packet.quality.blocking.length">
                Blocking: {{ packet.quality.blocking.join(', ') }}
              </span>
              <span v-if="packet.quality.conflicting.length">
                Conflicting: {{ packet.quality.conflicting.join(', ') }}
              </span>
            </div>

            <h3>Per-field quality</h3>
            <table class="fields">
              <tbody>
                <tr v-for="(fq, name) in packet.quality.fields" :key="name">
                  <th scope="row">{{ name }}</th>
                  <td><span class="quality" :class="qualityClass(fq.quality)">{{ fq.quality }}</span></td>
                  <td class="f-value">{{ displayValue(fq.value) }}</td>
                  <td class="f-detail">{{ fq.detail }}</td>
                </tr>
              </tbody>
            </table>

            <div v-if="countryUnconfirmed" class="confirm-country">
              <p>
                The country was inferred from the source, not stated by it, so it cannot pass the
                gate as a fact. If the official page confirms this programme is in
                <strong>{{ packet.identity.country }}</strong>, confirm it:
              </p>
              <button type="button" class="button-secondary" :disabled="busy" @click="doConfirmCountry">
                Confirm country: {{ packet.identity.country }}
              </button>
            </div>

            <h3>Extracted facts</h3>
            <dl class="facts">
              <div><dt>Degree</dt><dd>{{ displayValue(packet.eligibility.degree) }}</dd></div>
              <div><dt>Funding</dt><dd>{{ displayValue(packet.eligibility.funding_type) }}</dd></div>
              <div><dt>Fields</dt><dd>{{ displayValue(packet.eligibility.field_of_study) }}</dd></div>
              <div><dt>Minimum GPA</dt><dd>{{ displayValue(packet.eligibility.minimum_gpa) }}</dd></div>
              <div>
                <dt>IELTS</dt>
                <dd>
                  {{ packet.eligibility.ielts_required == null ? 'Not mentioned in the source' : packet.eligibility.ielts_required ? `Required, min ${packet.eligibility.minimum_ielts ?? '—'}` : 'Not required' }}
                </dd>
              </div>
              <div>
                <dt>TOEFL</dt>
                <dd>
                  {{ packet.eligibility.toefl_required == null ? 'Not mentioned in the source' : packet.eligibility.toefl_required ? `Required, min ${packet.eligibility.minimum_toefl ?? '—'}` : 'Not required' }}
                </dd>
              </div>
              <div><dt>Deadline</dt><dd>{{ formatDate(packet.timeline.application_deadline) ?? 'Not stated' }}</dd></div>
              <div><dt>Opens</dt><dd>{{ formatDate(packet.timeline.application_open) ?? 'Not stated' }}</dd></div>
              <div><dt>Cycle</dt><dd>{{ displayValue(packet.timeline.application_cycle) }}</dd></div>
              <div><dt>Study start</dt><dd>{{ formatDate(packet.timeline.study_start) ?? 'Not stated' }}</dd></div>
            </dl>

            <h3>Correct a field</h3>
            <div class="fix-grid">
              <label>
                Deadline
                <input v-model="fix.deadline" type="date" />
              </label>
              <label>
                Degree
                <select v-model="fix.degree">
                  <option value="">Not stated</option>
                  <option v-for="d in DEGREES" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label>
                Funding
                <select v-model="fix.funding_type">
                  <option value="">Not stated</option>
                  <option v-for="f in FUNDING_TYPES" :key="f" :value="f">{{ f }}</option>
                </select>
              </label>
              <label>
                Minimum GPA
                <input v-model="fix.minimum_gpa" type="number" step="0.01" min="0" max="4" placeholder="e.g. 3.00" />
              </label>
              <label class="wide">
                Official page URL
                <input v-model="fix.official_page_url" type="url" />
              </label>
              <label class="wide">
                Why is this correction right? (required, goes on the audit trail)
                <input v-model="fixReason" type="text" placeholder="e.g. official page states the 2027 deadline is 1 May" />
              </label>
            </div>
            <button type="button" class="button-secondary" :disabled="busy" @click="doSaveCorrection">
              Save correction
            </button>

            <h3>Decision</h3>
            <div class="fix-grid">
              <label class="wide">
                Reason (required to reject or send back; required to override the gate)
                <input v-model="reason" type="text" placeholder="Why this decision?" />
              </label>
              <label class="wide">
                Evidence URL (the official page you checked)
                <input v-model="evidenceUrl" type="url" placeholder="https://…" />
              </label>
            </div>
            <label v-if="!packet.quality.publishable" class="override">
              <input v-model="overrideQuality" type="checkbox" />
              Publish anyway, overriding the quality gate (identity and provenance failures cannot
              be overridden; the server will refuse those)
            </label>
            <div class="decisions">
              <button type="button" class="button-primary" :disabled="busy" @click="doApprove">
                Approve &amp; publish
              </button>
              <button type="button" class="button-secondary danger" :disabled="busy" @click="doReject">
                Reject
              </button>
              <button type="button" class="button-secondary" :disabled="busy" @click="doRequestCorrection">
                Send back for correction
              </button>
            </div>

            <template v-if="packet.history.length">
              <h3>History</h3>
              <ul class="history">
                <li v-for="h in packet.history" :key="h.review_action_id">
                  <strong>{{ h.action }}</strong> by {{ h.actor }} ·
                  {{ formatDate(h.occurred_at.slice(0, 10)) }}
                  <span v-if="h.reason"> — {{ h.reason }}</span>
                </li>
              </ul>
            </template>
          </template>
        </section>
      </div>
    </template>
  </main>
</template>

<style scoped>
.review-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
}
.review-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  flex-wrap: wrap;
}
.lede {
  color: var(--color-ink-secondary);
  max-width: 44rem;
}
.head-actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-line);
  border-radius: 12px;
  padding: 1.25rem;
}
.signin {
  max-width: 34rem;
  margin-top: 1.5rem;
}
.signin form,
.signin label {
  display: grid;
  gap: 0.6rem;
}
.signin form {
  gap: 1rem;
  margin-top: 1rem;
}
input,
select {
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--color-line-strong);
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-ink);
  font: inherit;
}
.metrics {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  margin: 1.5rem 0 1rem;
}
.metric {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-line);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  display: grid;
}
.metric strong {
  font-size: 1.4rem;
}
.metric span {
  color: var(--color-ink-secondary);
  font-size: 0.85rem;
}
.error {
  color: var(--color-feedback-error);
}
.error.banner {
  display: flex;
  gap: 1rem;
  align-items: center;
}
.notice {
  color: var(--color-feedback-success);
  font-weight: 600;
}
.layout {
  display: grid;
  grid-template-columns: minmax(280px, 380px) 1fr;
  gap: 1rem;
  align-items: start;
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
.count {
  color: var(--color-ink-secondary);
  font-size: 0.9rem;
}
.muted {
  color: var(--color-ink-secondary);
}
.queue-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.5rem;
}
.queue-item {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.25rem;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--color-line);
  border-radius: 10px;
  background: var(--color-surface);
  color: var(--color-ink);
  cursor: pointer;
  font: inherit;
}
.queue-item:hover {
  border-color: var(--color-line-strong);
}
.queue-item.selected {
  border-color: var(--color-brand);
  background: var(--color-brand-soft);
}
.q-name {
  font-weight: 600;
}
.q-meta {
  color: var(--color-ink-secondary);
  font-size: 0.85rem;
}
.q-flags {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.flag {
  font-size: 0.72rem;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-line);
}
.flag.blocking {
  color: var(--color-feedback-error);
  border-color: var(--color-feedback-error);
}
.flag.conflict {
  color: var(--color-sem-unknown);
  border-color: var(--color-sem-unknown);
}
.meta {
  color: var(--color-ink-secondary);
  margin: 0.25rem 0;
}
.verdict {
  display: grid;
  gap: 0.2rem;
  padding: 0.8rem 1rem;
  border-radius: 10px;
  margin: 1rem 0;
}
.verdict.ok {
  background: var(--color-evidence-soft);
  color: var(--color-evidence);
}
.verdict.blocked {
  background: #fbe9e7;
  color: var(--color-feedback-error);
}
.fields {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.fields th,
.fields td {
  text-align: left;
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid var(--color-line);
  vertical-align: top;
}
.quality {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  border: 1px solid currentColor;
}
.q-known {
  color: var(--color-sem-active);
}
.q-bad {
  color: var(--color-feedback-error);
}
.q-unknown {
  color: var(--color-sem-unknown);
}
.q-na {
  color: var(--color-sem-legacy);
}
.f-detail {
  color: var(--color-ink-secondary);
}
.confirm-country {
  border: 1px dashed var(--color-sem-unknown);
  border-radius: 10px;
  padding: 0.8rem 1rem;
  margin: 1rem 0;
}
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.6rem 1.2rem;
}
.facts dt {
  color: var(--color-ink-secondary);
  font-size: 0.8rem;
}
.facts dd {
  margin: 0;
  font-weight: 500;
}
.fix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.8rem;
  margin-bottom: 0.8rem;
}
.fix-grid label {
  display: grid;
  gap: 0.35rem;
  font-size: 0.9rem;
}
.fix-grid .wide {
  grid-column: 1 / -1;
}
.override {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  margin: 0.5rem 0 1rem;
  font-size: 0.9rem;
}
.decisions {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.danger {
  color: var(--color-feedback-error);
  border-color: var(--color-feedback-error);
}
.history {
  padding-left: 1.1rem;
  color: var(--color-ink-secondary);
}
</style>
