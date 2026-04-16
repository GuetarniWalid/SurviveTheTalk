// NOTE: Minimal dark theme. Full token system (8 colors, 10 text styles,
// 8px spacing) arrives in Story 4.1b. Do not expand scope here.

import 'package:flutter/material.dart';

class AppTheme {
  const AppTheme._();

  static ThemeData dark() {
    return ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      scaffoldBackgroundColor: const Color(0xFF1E1F23),
      colorScheme: const ColorScheme.dark(
        surface: Color(0xFF1E1F23),
        primary: Color(0xFF00E5A0),
      ),
    );
  }
}
