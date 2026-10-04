// maplibre-gl 6 looks for its worker next to its own module file
// (`new URL('./maplibre-gl-worker.mjs', import.meta.url)`). After a production build the
// module is renamed and the worker is not emitted, so the map stays blank. Bundle the worker
// with Vite and hand MapLibre its URL before the first map is created.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

export const mapLib = import('maplibre-gl').then((m) => {
  const lib = (m as unknown as { default?: typeof m }).default ?? m
  lib.setWorkerUrl(workerUrl)
  return lib
})
