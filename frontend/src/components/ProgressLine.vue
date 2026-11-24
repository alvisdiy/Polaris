<template>
  <div class="progress-line" role="progressbar" aria-label="Loading">
    <div class="progress-fill" />
  </div>
</template>

<style scoped>
.progress-line {
  position: relative;
  height: 2px;
  border-radius: 1px;
  overflow: hidden;
  background: var(--color-line);
}

.progress-fill {
  position: absolute;
  inset: 0;
  width: 40%;
  background: var(--color-brand);
  animation: slide 1.1s ease-in-out infinite;
}

@keyframes slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(260%);
  }
}
</style>
