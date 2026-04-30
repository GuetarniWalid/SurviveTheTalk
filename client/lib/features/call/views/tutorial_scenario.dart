/// Hardcoded identity for the tutorial call (Story 4.5).
///
/// `id` + `riveCharacter` are the only fields needed at the onboarding
/// boundary — the display fields (name, role, avatar) live in
/// `kCharacterCatalog` and are looked up by `riveCharacter`.
///
/// Story 6.1 will replace these constants with values pulled from the
/// scenarios API (Story 5.1). Kept in a dedicated file so the refactor
/// point is easy to find later.
abstract final class TutorialScenario {
  static const String id = 'waiter_easy_01';

  /// Catalog key — must match an entry in `kCharacterCatalog` and a
  /// `character` ViewModel enum case inside `assets/rive/characters.riv`.
  static const String riveCharacter = 'waiter';
}
