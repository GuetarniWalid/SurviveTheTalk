/** @type {import('tailwindcss').Config} */
// Brand tokens = the single source of truth from the app
// (client/lib/core/theme/app_colors.dart). Two-ink discipline is enforced by
// simply not defining off-brand colors. GUARD (review): `accent` may only
// appear as `bg-accent`, never `text-accent`; `survived`/`failed` only inside
// the Debrief mock.
module.exports = {
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      bg: '#1E1F23',
      surface: '#414143',
      'text-primary': '#F0F0F0',
      'text-secondary': '#8A8A95',
      accent: '#00E5A0', // FILL ONLY — never text-*
      survived: '#2ECC40', // data viz only
      failed: '#FF6B6B', // data viz only
      destructive: '#E74C3C',
      warning: '#F59E0B',
      'gauge-track': '#2A2B30',
      'paywall-error': '#C0392B',
    },
    extend: {
      fontFamily: {
        display: ['Frijole', 'serif'], // weight 400 only, caps
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        hero: ['clamp(40px,8vw,96px)', { lineHeight: '0.95' }],
        h2: ['24px', { lineHeight: '1.2', fontWeight: '700' }],
        headline: ['18px', { lineHeight: '1.3', fontWeight: '600' }],
        body: ['16px', { lineHeight: '1.5' }],
        caption: ['13px', { lineHeight: '1.4' }],
        eyebrow: ['12px', { lineHeight: '1', letterSpacing: '1px' }],
      },
      borderColor: { hairline: 'rgba(255,255,255,0.08)' },
      ringColor: { focus: '#00E5A0' },
      maxWidth: { rail: '640px' },
    },
  },
  plugins: [],
};
