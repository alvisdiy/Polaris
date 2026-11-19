<script setup lang="ts">
/*
 * A restrained Three.js accent for the home hero: a wireframe globe with a slow
 * constellation of points, drawn in the interface's own ink and vermilion.
 *
 * Why this and not a ThreeUI landing template: Polaris is a search product, and
 * its first screen has to stay readable and fast. The scene is therefore
 * decorative only — it carries no information, it is hidden from assistive
 * technology, it never intercepts pointer events, and it is skipped entirely for
 * people who ask for reduced motion or who are on a small screen. three.js is
 * imported dynamically so it never lands in the initial bundle.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

const host = ref<HTMLDivElement | null>(null)

let cleanup: (() => void) | undefined

onMounted(async () => {
  const element = host.value
  if (!element) return

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const narrow = window.matchMedia('(max-width: 900px)').matches
  if (reduced || narrow) return

  const THREE = await import('three')

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)
  camera.position.set(0, 0, 6.4)

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  element.appendChild(renderer.domElement)
  renderer.domElement.setAttribute('aria-hidden', 'true')
  renderer.domElement.style.width = '100%'
  renderer.domElement.style.height = '100%'
  renderer.domElement.style.display = 'block'

  const styles = getComputedStyle(document.documentElement)
  const ink = new THREE.Color(styles.getPropertyValue('--color-ink').trim() || '#1a1512')
  const accent = new THREE.Color(styles.getPropertyValue('--color-brand').trim() || '#b8402a')

  const group = new THREE.Group()
  scene.add(group)

  // Latitude/longitude wireframe: the "ledger" reading of a globe.
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(1.9, 24, 16),
    new THREE.MeshBasicMaterial({
      color: ink,
      wireframe: true,
      transparent: true,
      opacity: 0.16,
    }),
  )
  group.add(sphere)

  // Fixed points: a constellation, not a random cloud, so it reads as a map.
  const positions: number[] = []
  for (let index = 0; index < 140; index += 1) {
    const phi = Math.acos(1 - (2 * (index + 0.5)) / 140)
    const theta = Math.PI * (1 + Math.sqrt(5)) * index
    const radius = 1.93
    positions.push(
      radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.sin(theta),
    )
  }
  const cloudGeometry = new THREE.BufferGeometry()
  cloudGeometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  const cloud = new THREE.Points(
    cloudGeometry,
    new THREE.PointsMaterial({ color: accent, size: 0.045, transparent: true, opacity: 0.85 }),
  )
  group.add(cloud)

  // An orbit ring, tilted: the one asymmetric element in an otherwise calm scene.
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(2.55, 0.006, 8, 120),
    new THREE.MeshBasicMaterial({ color: ink, transparent: true, opacity: 0.28 }),
  )
  ring.rotation.x = Math.PI / 2.35
  ring.rotation.y = 0.35
  group.add(ring)

  group.rotation.z = -0.18

  const resize = () => {
    const { clientWidth, clientHeight } = element
    if (!clientWidth || !clientHeight) return
    renderer.setSize(clientWidth, clientHeight, false)
    camera.aspect = clientWidth / clientHeight
    camera.updateProjectionMatrix()
  }
  resize()

  const observer = new ResizeObserver(resize)
  observer.observe(element)

  let frame = 0
  let visible = true
  const tick = () => {
    if (visible) {
      group.rotation.y += 0.0016
      cloud.rotation.y += 0.0006
      renderer.render(scene, camera)
    }
    frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)

  const intersection = new IntersectionObserver(
    (entries) => {
      visible = entries[0]?.isIntersecting ?? true
    },
    { threshold: 0.05 },
  )
  intersection.observe(element)

  cleanup = () => {
    cancelAnimationFrame(frame)
    observer.disconnect()
    intersection.disconnect()
    sphere.geometry.dispose()
    ;(sphere.material as InstanceType<typeof THREE.MeshBasicMaterial>).dispose()
    cloudGeometry.dispose()
    ;(cloud.material as InstanceType<typeof THREE.PointsMaterial>).dispose()
    ring.geometry.dispose()
    ;(ring.material as InstanceType<typeof THREE.MeshBasicMaterial>).dispose()
    renderer.dispose()
    renderer.domElement.remove()
  }
})

onBeforeUnmount(() => cleanup?.())
</script>

<template>
  <div ref="host" class="hero-globe" aria-hidden="true"></div>
</template>

<style scoped>
.hero-globe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  opacity: 0.95;
  mask-image: radial-gradient(circle at 50% 50%, #000 60%, transparent 80%);
}

@media (max-width: 900px) {
  .hero-globe {
    display: none;
  }
}
</style>
