import 'models/character_identity.dart';

/// Single source of truth for character-level identity data (name, role,
/// circular-avatar JPG). Keyed by the `riveCharacter` enum value carried on
/// every `Scenario` (matches the `character` ViewModel enum cases inside
/// `assets/rive/characters.riv` 1:1).
///
/// Consumed by:
///   - `CharacterAvatar` (renders the circular avatar JPG)
///   - `IncomingCallScreen` (onboarding first-call screen — name + role)
///   - `CallScreen.CallConnecting` (outgoing call dial screen — name + role)
///
/// Adding a new character means: add a new `riveCharacter` enum value in
/// the .riv, drop the avatar JPG into `assets/images/characters/`, and add
/// an entry here. No server change required for MVP scale (5–20 entries).
///
/// **Promotion to server-side** is the natural next step when the catalog
/// grows past ~20 entries OR when content updates need to ship without an
/// app rebuild. At that point this map becomes a `GET /characters` cache,
/// and `CharacterIdentity` keeps the same shape — refactor cost stays in
/// the data-source layer, not in callers.
const Map<String, CharacterIdentity> kCharacterCatalog = {
  'waiter': CharacterIdentity(
    name: 'Tina',
    role: 'Waitress',
    imageAsset: 'assets/images/characters/waiter.jpg',
  ),
  'mugger': CharacterIdentity(
    name: 'Marcus',
    role: 'Mugger',
    imageAsset: 'assets/images/characters/mugger.jpg',
  ),
  'girlfriend': CharacterIdentity(
    name: 'Camille',
    role: 'Girlfriend',
    imageAsset: 'assets/images/characters/girlfriend.jpg',
  ),
  'cop': CharacterIdentity(
    name: 'Diaz',
    role: 'Cop',
    imageAsset: 'assets/images/characters/cop.jpg',
  ),
  'landlord': CharacterIdentity(
    name: 'Frank',
    role: 'Landlord',
    imageAsset: 'assets/images/characters/landlord.jpg',
  ),
};
