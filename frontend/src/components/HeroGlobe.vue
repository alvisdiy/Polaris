<script setup lang="ts">
/*
 * A decorative wireframe globe for the home hero, drawn as inline SVG.
 *
 * It replaces a Three.js scene that shipped a 753 kB chunk for one aria-hidden
 * element. The shape is the same idea in the interface's own material: hairlines
 * for the graticule, a shell of vermilion points, one tilted orbit. Nothing here
 * carries information, nothing animates, and it costs no dependency and no
 * runtime frames.
 *
 * The dot field is a Fibonacci sphere projected orthographically; depth is
 * expressed as opacity and radius so the near face reads closer than the far one.
 */
</script>

<template>
  <svg
    class="globe"
    viewBox="0 0 200 200"
    role="presentation"
    aria-hidden="true"
    focusable="false"
  >
    <g class="graticule">
          <ellipse rx="0" ry="74" />
          <ellipse rx="20" ry="74" />
          <ellipse rx="39" ry="74" />
          <ellipse rx="55" ry="74" />
          <ellipse rx="68" ry="74" />
          <ellipse rx="76" ry="74" />
          <ellipse cx="100" cy="42" rx="47" ry="8.9" />
          <ellipse cx="100" cy="60" rx="63" ry="12.0" />
          <ellipse cx="100" cy="80" rx="72" ry="13.7" />
          <ellipse cx="100" cy="100" rx="76" ry="14.4" />
          <ellipse cx="100" cy="120" rx="72" ry="13.7" />
          <ellipse cx="100" cy="140" rx="63" ry="12.0" />
          <ellipse cx="100" cy="158" rx="47" ry="8.9" />
    </g>

    <g class="orbit">
      <ellipse cx="100" cy="100" rx="96" ry="34" />
    </g>

    <path class="pole" d="M100 9c.9 5.6 2.3 7.9 3.4 9 1.1 1.1 3.4 2.5 9 3.4v.6c-5.6.9-7.9 2.3-9 3.4-1.1 1.1-2.5 3.4-3.4 9h-.6c-.9-5.6-2.3-7.9-3.4-9-1.1-1.1-3.4-2.5-9-3.4v-.6c5.6-.9 7.9-2.3 9-3.4 1.1-1.1 2.5-3.4 3.4-9Z" />

    <g class="points">
        <circle cx="76.80" cy="56.83" r="0.93" opacity="0.36" />
        <circle cx="97.57" cy="47.86" r="0.94" opacity="0.37" />
        <circle cx="142.91" cy="129.71" r="0.94" opacity="0.37" />
        <circle cx="66.57" cy="142.05" r="0.95" opacity="0.38" />
        <circle cx="153.89" cy="106.17" r="0.95" opacity="0.38" />
        <circle cx="128.61" cy="53.47" r="0.96" opacity="0.38" />
        <circle cx="144.85" cy="68.05" r="0.96" opacity="0.38" />
        <circle cx="55.44" cy="65.80" r="0.96" opacity="0.39" />
        <circle cx="50.82" cy="127.47" r="0.96" opacity="0.39" />
        <circle cx="43.55" cy="89.35" r="0.97" opacity="0.39" />
        <circle cx="83.00" cy="156.62" r="0.98" opacity="0.40" />
        <circle cx="126.94" cy="153.26" r="0.98" opacity="0.41" />
        <circle cx="158.64" cy="82.62" r="0.99" opacity="0.42" />
        <circle cx="112.49" cy="38.89" r="1.00" opacity="0.42" />
        <circle cx="108.03" cy="162.23" r="1.00" opacity="0.43" />
        <circle cx="38.14" cy="112.89" r="1.01" opacity="0.43" />
        <circle cx="73.38" cy="42.26" r="1.01" opacity="0.43" />
        <circle cx="146.51" cy="144.29" r="1.01" opacity="0.44" />
        <circle cx="161.11" cy="120.74" r="1.02" opacity="0.44" />
        <circle cx="56.99" cy="151.02" r="1.03" opacity="0.46" />
        <circle cx="54.32" cy="51.23" r="1.04" opacity="0.46" />
        <circle cx="38.11" cy="74.77" r="1.04" opacity="0.46" />
        <circle cx="137.43" cy="44.50" r="1.04" opacity="0.46" />
        <circle cx="91.69" cy="33.29" r="1.04" opacity="0.46" />
        <circle cx="168.07" cy="97.20" r="1.05" opacity="0.47" />
        <circle cx="154.58" cy="59.08" r="1.05" opacity="0.47" />
        <circle cx="41.27" cy="136.44" r="1.06" opacity="0.48" />
        <circle cx="77.54" cy="165.59" r="1.06" opacity="0.48" />
        <circle cx="30.26" cy="98.32" r="1.07" opacity="0.49" />
        <circle cx="120.55" cy="167.83" r="1.08" opacity="0.50" />
        <circle cx="161.76" cy="135.32" r="1.09" opacity="0.50" />
        <circle cx="97.02" cy="171.20" r="1.09" opacity="0.51" />
        <circle cx="140.34" cy="158.86" r="1.09" opacity="0.51" />
        <circle cx="114.47" cy="29.92" r="1.09" opacity="0.51" />
        <circle cx="166.69" cy="73.65" r="1.09" opacity="0.51" />
        <circle cx="39.68" cy="60.20" r="1.11" opacity="0.52" />
        <circle cx="64.64" cy="36.65" r="1.11" opacity="0.53" />
        <circle cx="30.81" cy="121.86" r="1.11" opacity="0.53" />
        <circle cx="171.81" cy="111.77" r="1.12" opacity="0.53" />
        <circle cx="134.12" cy="35.53" r="1.12" opacity="0.54" />
        <circle cx="58.47" cy="159.98" r="1.12" opacity="0.54" />
        <circle cx="88.43" cy="27.68" r="1.13" opacity="0.55" />
        <circle cx="28.36" cy="83.74" r="1.14" opacity="0.55" />
        <circle cx="154.16" cy="50.11" r="1.14" opacity="0.56" />
        <circle cx="154.36" cy="149.89" r="1.15" opacity="0.57" />
        <circle cx="41.73" cy="145.41" r="1.16" opacity="0.57" />
        <circle cx="172.96" cy="88.23" r="1.16" opacity="0.57" />
        <circle cx="108.84" cy="173.44" r="1.17" opacity="0.58" />
        <circle cx="49.85" cy="45.62" r="1.17" opacity="0.58" />
        <circle cx="109.09" cy="26.56" r="1.18" opacity="0.59" />
        <circle cx="26.36" cy="107.29" r="1.18" opacity="0.59" />
        <circle cx="73.19" cy="168.95" r="1.18" opacity="0.60" />
        <circle cx="169.12" cy="126.35" r="1.18" opacity="0.60" />
        <circle cx="136.09" cy="164.47" r="1.19" opacity="0.61" />
        <circle cx="73.55" cy="31.05" r="1.20" opacity="0.61" />
        <circle cx="164.81" cy="64.68" r="1.20" opacity="0.61" />
        <circle cx="33.02" cy="69.17" r="1.20" opacity="0.62" />
        <circle cx="33.42" cy="130.83" r="1.22" opacity="0.63" />
        <circle cx="143.80" cy="41.14" r="1.22" opacity="0.63" />
        <circle cx="172.94" cy="102.80" r="1.23" opacity="0.64" />
        <circle cx="91.23" cy="172.32" r="1.23" opacity="0.64" />
        <circle cx="51.73" cy="154.38" r="1.24" opacity="0.65" />
        <circle cx="118.48" cy="170.08" r="1.24" opacity="0.65" />
        <circle cx="159.77" cy="140.92" r="1.24" opacity="0.65" />
        <circle cx="124.95" cy="32.17" r="1.24" opacity="0.66" />
        <circle cx="28.24" cy="92.71" r="1.25" opacity="0.66" />
        <circle cx="44.33" cy="54.59" r="1.25" opacity="0.66" />
        <circle cx="101.76" cy="28.80" r="1.26" opacity="0.67" />
        <circle cx="167.88" cy="79.26" r="1.27" opacity="0.68" />
        <circle cx="62.51" cy="40.02" r="1.27" opacity="0.68" />
        <circle cx="143.76" cy="155.50" r="1.27" opacity="0.68" />
        <circle cx="69.04" cy="163.35" r="1.27" opacity="0.68" />
        <circle cx="153.82" cy="55.71" r="1.28" opacity="0.69" />
        <circle cx="32.43" cy="116.26" r="1.29" opacity="0.70" />
        <circle cx="166.75" cy="117.38" r="1.29" opacity="0.70" />
        <circle cx="45.06" cy="139.80" r="1.30" opacity="0.71" />
        <circle cx="36.11" cy="78.14" r="1.31" opacity="0.72" />
        <circle cx="84.21" cy="34.41" r="1.31" opacity="0.72" />
        <circle cx="99.15" cy="166.71" r="1.32" opacity="0.72" />
        <circle cx="121.45" cy="161.11" r="1.33" opacity="0.74" />
        <circle cx="136.42" cy="46.74" r="1.33" opacity="0.74" />
        <circle cx="116.97" cy="37.77" r="1.33" opacity="0.74" />
        <circle cx="164.16" cy="93.83" r="1.33" opacity="0.74" />
        <circle cx="155.16" cy="131.95" r="1.34" opacity="0.75" />
        <circle cx="49.08" cy="63.56" r="1.35" opacity="0.76" />
        <circle cx="37.97" cy="101.68" r="1.35" opacity="0.76" />
        <circle cx="153.99" cy="70.29" r="1.35" opacity="0.76" />
        <circle cx="65.66" cy="48.98" r="1.36" opacity="0.76" />
        <circle cx="63.01" cy="148.77" r="1.36" opacity="0.76" />
        <circle cx="139.48" cy="146.53" r="1.36" opacity="0.77" />
        <circle cx="82.97" cy="157.74" r="1.36" opacity="0.77" />
        <circle cx="47.25" cy="125.23" r="1.37" opacity="0.78" />
        <circle cx="93.88" cy="43.38" r="1.38" opacity="0.79" />
        <circle cx="154.69" cy="108.41" r="1.39" opacity="0.80" />
        <circle cx="109.90" cy="152.14" r="1.40" opacity="0.81" />
        <circle cx="48.85" cy="87.11" r="1.40" opacity="0.81" />
        <circle cx="134.12" cy="61.32" r="1.41" opacity="0.81" />
        <circle cx="146.95" cy="84.86" r="1.42" opacity="0.82" />
        <circle cx="112.43" cy="52.35" r="1.42" opacity="0.82" />
        <circle cx="141.01" cy="122.98" r="1.43" opacity="0.83" />
        <circle cx="67.93" cy="134.20" r="1.43" opacity="0.83" />
        <circle cx="79.39" cy="57.95" r="1.43" opacity="0.83" />
        <circle cx="63.40" cy="72.53" r="1.43" opacity="0.83" />
        <circle cx="56.01" cy="110.65" r="1.43" opacity="0.84" />
        <circle cx="125.19" cy="137.56" r="1.43" opacity="0.84" />
        <circle cx="90.40" cy="143.17" r="1.44" opacity="0.84" />
        <circle cx="134.75" cy="99.44" r="1.46" opacity="0.86" />
        <circle cx="124.32" cy="75.89" r="1.46" opacity="0.86" />
        <circle cx="100.32" cy="66.92" r="1.47" opacity="0.87" />
        <circle cx="69.33" cy="96.08" r="1.47" opacity="0.87" />
        <circle cx="103.82" cy="128.59" r="1.47" opacity="0.88" />
        <circle cx="79.31" cy="119.62" r="1.47" opacity="0.88" />
        <circle cx="119.55" cy="114.02" r="1.48" opacity="0.88" />
        <circle cx="84.96" cy="81.50" r="1.48" opacity="0.88" />
        <circle cx="110.14" cy="90.47" r="1.49" opacity="0.89" />
        <circle cx="94.26" cy="105.05" r="1.50" opacity="0.90" />
    </g>
  </svg>
</template>

<style scoped>
.globe {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.graticule ellipse {
  fill: none;
  stroke: var(--color-ink);
  stroke-width: 0.5;
  opacity: 0.14;
}

/* The single asymmetric element: an orbit tilted against a calm grid. */
.orbit ellipse {
  fill: none;
  stroke: var(--color-brand);
  stroke-width: 0.7;
  opacity: 0.55;
  transform: rotate(-17deg);
  transform-origin: 100px 100px;
}

.points {
  animation: drift 140s linear infinite;
  transform-origin: 100px 100px;
}

.points circle {
  fill: var(--color-star);
}

/* Polaris itself: one brighter star at the pole that does not move. */
.pole {
  fill: var(--color-star);
}

@keyframes drift {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

[data-theme='dark'] .graticule ellipse {
  opacity: 0.2;
}
</style>
