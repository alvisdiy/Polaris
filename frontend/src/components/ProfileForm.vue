<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { RecommendationRequest } from '../api/types'
import { useProfile } from '../stores/profile'

const props = defineProps<{
  submitting: boolean
  serverFieldErrors: string[]
}>()

const emit = defineEmits<{
  (e: 'submit', profile: RecommendationRequest): void
}>()

const { profile } = useProfile()

const COUNTRIES = [
  'Australia',
  'China',
  'Germany',
  'France',
  'United Kingdom',
  'Indonesia',
  'Japan',
  'South Korea',
  'Singapore',
  'United States',
]

const DEGREES = ['Bachelor', 'Master', 'PhD', 'Exchange', 'Short Course']
const EXPERIENCE_LEVELS = ['Not Required', 'Optional', 'Preferred', 'Required']
const FUNDING = ['Fully Funded', 'Partial Funded', 'Tuition Only']

const form = reactive<RecommendationRequest>({
  ...profile,
  field_of_study: [...profile.field_of_study],
})

const fieldInput = ref('')
const errors = reactive<Record<string, string>>({})
const formError = ref('')

function addField() {
  const value = fieldInput.value.trim()
  if (!value) return
  if (!form.field_of_study.includes(value)) {
    form.field_of_study.push(value)
  }
  fieldInput.value = ''
}

function removeField(field: string) {
  form.field_of_study = form.field_of_study.filter((existing) => existing !== field)
}

function validate(): boolean {
  Object.keys(errors).forEach((key) => delete errors[key])
  formError.value = ''

  if (!form.target_country) errors.target_country = 'Select a target country'
  if (!form.degree) errors.degree = 'Select a degree'
  if (form.field_of_study.length === 0) {
    errors.field_of_study = 'Add at least one field of study'
  }
  if (Number.isNaN(form.current_gpa) || form.current_gpa < 0 || form.current_gpa > 4) {
    errors.current_gpa = 'GPA must be between 0 and 4'
  }
  if (form.ielts_score !== null && (form.ielts_score < 0 || form.ielts_score > 9)) {
    errors.ielts_score = 'IELTS must be between 0 and 9'
  }
  if (form.toefl_score !== null && (form.toefl_score < 0 || form.toefl_score > 120)) {
    errors.toefl_score = 'TOEFL must be between 0 and 120'
  }
  if (!form.research_experience) errors.research_experience = 'Select an option'
  if (!form.work_experience) errors.work_experience = 'Select an option'
  if (!form.publication) errors.publication = 'Select an option'
  if (!form.funding_preference) errors.funding_preference = 'Select a funding preference'

  return Object.keys(errors).length === 0
}

function mapServerErrors(fieldErrors: string[]) {
  let mapped = false
  for (const item of fieldErrors) {
    const [field, ...rest] = item.split(':')
    const key = field.trim().replace(/ ->.*$/, '')
    if (key in form) {
      errors[key] = rest.join(':').trim() || 'Please review this field'
      mapped = true
    } else {
      formError.value = formError.value || item
    }
  }
  if (!mapped && fieldErrors.length && !formError.value) {
    formError.value = fieldErrors[0]
  }
}

function onSubmit() {
  if (props.submitting) return
  if (!validate()) {
    formError.value = 'Please fix the highlighted fields.'
    return
  }
  emit('submit', {
    ...form,
    field_of_study: [...form.field_of_study],
  })
}

defineExpose({ mapServerErrors })
</script>

<template>
  <form class="profile-form" novalidate @submit.prevent="onSubmit">
    <div v-if="formError" class="form-alert" role="alert">{{ formError }}</div>

    <div class="field-group">
      <label class="field-label" for="pf-country">Target country <span class="req">*</span></label>
      <select
        id="pf-country"
        v-model="form.target_country"
        class="field-select"
        :class="{ invalid: errors.target_country }"
        :aria-invalid="Boolean(errors.target_country)"
        aria-describedby="pf-country-hint"
      >
        <option value="" disabled>Select a country</option>
        <option v-for="c in COUNTRIES" :key="c" :value="c">{{ c }}</option>
      </select>
      <p id="pf-country-hint" class="field-hint">Where do you want to study?</p>
      <p v-if="errors.target_country" class="field-error">{{ errors.target_country }}</p>
    </div>

    <fieldset class="fieldset">
      <legend class="field-label">Degree <span class="req">*</span></legend>
      <div class="radio-row">
        <label v-for="d in DEGREES" :key="d" class="radio-option">
          <input v-model="form.degree" type="radio" name="degree" :value="d" />
          {{ d }}
        </label>
      </div>
      <p v-if="errors.degree" class="field-error">{{ errors.degree }}</p>
    </fieldset>

    <div class="field-group">
      <label class="field-label" for="pf-field">Field of study <span class="req">*</span></label>
      <div class="tag-input-row">
        <input
          id="pf-field"
          v-model="fieldInput"
          type="text"
          class="field-input"
          placeholder="e.g. Computer Science"
          @keydown.enter.prevent="addField"
        />
        <button type="button" class="tag-add" @click="addField">Add</button>
      </div>
      <p class="field-hint">Add one or more fields, for example: Computer Science, Public Health.</p>
      <ul v-if="form.field_of_study.length" class="tag-list">
        <li v-for="field in form.field_of_study" :key="field" class="tag">
          {{ field }}
          <button
            type="button"
            class="tag-remove"
            :aria-label="`Remove ${field}`"
            @click="removeField(field)"
          >
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="m2.5 2.5 7 7m0-7-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
          </button>
        </li>
      </ul>
      <p v-if="errors.field_of_study" class="field-error">{{ errors.field_of_study }}</p>
    </div>

    <div class="field-group">
      <label class="field-label" for="pf-gpa">Current GPA (4.0 scale) <span class="req">*</span></label>
      <input
        id="pf-gpa"
        v-model.number="form.current_gpa"
        type="number"
        min="0"
        max="4"
        step="0.01"
        class="field-input"
        :class="{ invalid: errors.current_gpa }"
        :aria-invalid="Boolean(errors.current_gpa)"
      />
      <p v-if="errors.current_gpa" class="field-error">{{ errors.current_gpa }}</p>
    </div>

    <div class="field-pair">
      <div class="field-group">
        <label class="field-label" for="pf-ielts">IELTS score <span class="optional">(optional)</span></label>
        <input
          id="pf-ielts"
          v-model.number="form.ielts_score"
          type="number"
          min="0"
          max="9"
          step="0.5"
          class="field-input"
          :class="{ invalid: errors.ielts_score }"
          aria-describedby="pf-ielts-hint"
        />
        <p id="pf-ielts-hint" class="field-hint">Leave empty if not taken.</p>
        <p v-if="errors.ielts_score" class="field-error">{{ errors.ielts_score }}</p>
      </div>
      <div class="field-group">
        <label class="field-label" for="pf-toefl">TOEFL iBT <span class="optional">(optional)</span></label>
        <input
          id="pf-toefl"
          v-model.number="form.toefl_score"
          type="number"
          min="0"
          max="120"
          step="1"
          class="field-input"
          :class="{ invalid: errors.toefl_score }"
          aria-describedby="pf-toefl-hint"
        />
        <p id="pf-toefl-hint" class="field-hint">Leave empty if not taken.</p>
        <p v-if="errors.toefl_score" class="field-error">{{ errors.toefl_score }}</p>
      </div>
    </div>

    <fieldset v-for="config in [
        { key: 'research_experience', label: 'Research experience' },
        { key: 'work_experience', label: 'Work experience' },
        { key: 'publication', label: 'Publications' },
      ] as const"
      :key="config.key"
      class="fieldset"
    >
      <legend class="field-label">{{ config.label }} <span class="req">*</span></legend>
      <div class="radio-row">
        <label v-for="level in EXPERIENCE_LEVELS" :key="level" class="radio-option">
          <input
            v-model="form[config.key]"
            type="radio"
            :name="config.key"
            :value="level"
          />
          {{ level }}
        </label>
      </div>
      <p v-if="errors[config.key]" class="field-error">{{ errors[config.key] }}</p>
    </fieldset>

    <div class="field-group">
      <label class="checkbox-option">
        <input v-model="form.leadership" type="checkbox" />
        I have leadership experience
      </label>
    </div>

    <fieldset class="fieldset">
      <legend class="field-label">Funding preference <span class="req">*</span></legend>
      <div class="radio-row">
        <label v-for="f in FUNDING" :key="f" class="radio-option">
          <input v-model="form.funding_preference" type="radio" name="funding" :value="f" />
          {{ f }}
        </label>
      </div>
      <p v-if="errors.funding_preference" class="field-error">{{ errors.funding_preference }}</p>
    </fieldset>

    <button type="submit" class="submit-button" :disabled="submitting">
      {{ submitting ? 'Computing matches...' : 'See my matches' }}
    </button>
  </form>
</template>

<style scoped>
.profile-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-alert {
  padding: var(--space-3);
  border: 1px solid var(--color-line-strong);
  border-left: 3px solid var(--color-feedback-error);
  background: var(--color-surface-raised);
  font-size: var(--font-size-sm);
  color: var(--color-feedback-error);
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.field-label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
}

.req {
  color: var(--color-brand);
}

.field-select,
.field-input {
  width: 100%;
  min-height: 44px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface-raised);
  color: var(--color-ink);
  font-size: var(--font-size-sm);
}

.field-hint {
  font-size: var(--font-size-xs);
  color: var(--color-ink-secondary);
}

.field-error {
  font-size: var(--font-size-xs);
  color: var(--color-feedback-error);
}

.fieldset {
  border: 1px solid var(--color-line);
  border-radius: var(--radius-card);
  padding: var(--space-3);
  background: var(--color-surface-raised);
}

.fieldset legend {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  color: var(--color-ink-secondary);
  padding: 0 var(--space-1);
}

.radio-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.radio-option,
.checkbox-option {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-sm);
  color: var(--color-ink);
}

.radio-option input,
.checkbox-option input {
  accent-color: var(--color-brand);
}

.field-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.tag-input-row {
  display: flex;
  gap: var(--space-2);
}

.tag-add {
  min-height: 44px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-control);
  background: transparent;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--color-line-strong);
  background: var(--color-paper);
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: var(--tracking-meta);
}

.tag-remove {
  border: none;
  background: none;
  color: var(--color-ink-secondary);
  padding: 0;
  line-height: 1;
}

.tag-remove:hover {
  color: var(--color-brand);
}

.submit-button {
  min-height: 46px;
  border: 1px solid var(--color-brand);
  background: var(--color-brand);
  color: var(--color-on-brand);
  border-radius: var(--radius-control);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-label);
  margin-top: var(--space-2);
  transition: background var(--motion-fast), transform var(--motion-fast),
    box-shadow var(--motion-fast);
}

.submit-button:hover {
  background: var(--color-brand-ink);
  border-color: var(--color-brand-ink);
  transform: translateY(-1px);
  box-shadow: var(--shadow-brand-glow);
}

.submit-button:active {
  transform: scale(0.98);
}

.submit-button:disabled {
  opacity: 0.6;
  cursor: wait;
  transform: none;
  box-shadow: none;
}

@media (max-width: 560px) {
  .field-pair {
    grid-template-columns: 1fr;
  }
}
</style>
