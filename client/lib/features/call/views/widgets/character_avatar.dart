import 'package:flutter/material.dart';

import '../../../../core/theme/call_colors.dart';
import '../../../scenarios/character_catalog.dart';

/// Circular character avatar — a clipped JPG sourced from
/// `kCharacterCatalog`.
///
/// The Rive 0.14.x `Picture` artboard previously used here was retired
/// from the shared `characters.riv` file; the static JPG is now the
/// canonical avatar primitive (same image used by `ScenarioCard`). This
/// makes the widget stateless, removes the `RiveNative.isInitialized`
/// gate, and unifies avatar rendering across the call surfaces.
class CharacterAvatar extends StatelessWidget {
  /// Catalog key — must match a `riveCharacter` enum value carried on
  /// the `Scenario` model (e.g. `'waiter'`, `'cop'`).
  final String character;
  final double size;

  const CharacterAvatar({
    super.key,
    required this.character,
    this.size = 166,
  });

  @override
  Widget build(BuildContext context) {
    final identity = kCharacterCatalog[character];
    assert(
      identity != null,
      'No character identity registered for "$character". Add an entry '
      'to kCharacterCatalog.',
    );
    return ClipOval(
      child: Container(
        width: size,
        height: size,
        color: CallColors.avatarBackground,
        child: identity == null
            ? const SizedBox.shrink()
            : Image.asset(
                identity.imageAsset,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => const SizedBox.shrink(),
              ),
      ),
    );
  }
}
