/// Identity data for a character variant in the scenario catalog.
///
/// One entity per `riveCharacter` enum value (`waiter`, `mugger`, …) — these
/// fields are the same across every scenario that reuses the same character
/// (e.g. `waiter_easy_01` and a hypothetical `waiter_hard_01` would share
/// the same name + role + avatar). Co-locating them on the character (not
/// the scenario) is the de-duplication that the per-scenario YAML approach
/// would have failed at.
class CharacterIdentity {
  /// Display name shown above the avatar (e.g. `Tina`).
  final String name;

  /// Display role shown beneath the name (e.g. `Waitress`).
  final String role;

  /// Asset path to the circular-avatar JPG. Must be declared under
  /// `assets/images/characters/` in `pubspec.yaml`.
  final String imageAsset;

  const CharacterIdentity({
    required this.name,
    required this.role,
    required this.imageAsset,
  });
}
