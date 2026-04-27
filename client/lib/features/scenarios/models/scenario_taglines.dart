// Launch content. Move server-side (scenarios.tagline column) post-MVP — see
// tech-debt note in Story 5.2.
//
// Each value should stay <= 40 chars to avoid wrapping a third line on
// 320-px screens (UX-DR18). The keys match the seeded scenario ids from
// Story 5.1 (server/db/seed_scenarios.py).

const Map<String, String> kScenarioTaglines = {
  'waiter_easy_01': 'Order before she loses it',
  'mugger_medium_01': 'Give me your wallet',
  'girlfriend_medium_01': "You're cheating on me, aren't you?",
  'cop_hard_01': 'Step out of the vehicle',
  'landlord_hard_01': "Rent's overdue. Again.",
};
