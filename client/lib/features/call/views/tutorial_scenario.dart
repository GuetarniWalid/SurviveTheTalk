/// Hardcoded identity for the tutorial call (Story 4.5).
///
/// Story 6.1 will replace these constants with values pulled from the
/// scenarios API (Story 5.1). Kept in a dedicated file so the refactor
/// point is easy to find later.
abstract final class TutorialScenario {
  static const String id = 'waiter_easy_01';
  static const String characterName = 'Tina';
  static const String characterRole = 'Waitress';

  /// Rive `character` enum value on `ViewModel1` inside `characters.riv`.
  /// This same string drives the avatar on the incoming-call screen and
  /// (later) the full-body character on the in-call screen (Epic 6).
  static const String riveCharacter = 'waiter';
}
