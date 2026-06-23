import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// Static landing page for survivethetalk.com (Story 10.3 follow-up).
// Outputs a plain dist/ folder of static HTML — rsynced to the VPS and
// served by Caddy (see _bmad-output/planning-artifacts/survivethetalk-landing-page-plan.md).
export default defineConfig({
  site: 'https://survivethetalk.com',
  // global.css owns the base layer (it declares @tailwind base itself) so the
  // @font-face + CSS-var resets load in the right order.
  integrations: [tailwind({ applyBaseStyles: false })],
});
