import 'package:client/core/theme/app_colors.dart';
import 'package:client/features/account/widgets/delete_account_tile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const String _kError = "Couldn't delete your account. Try again.";

Widget _host({
  required Future<void> Function() onDelete,
  required VoidCallback onDeleted,
}) {
  return MaterialApp(
    home: Scaffold(
      body: DeleteAccountTile(onDelete: onDelete, onDeleted: onDeleted),
    ),
  );
}

void main() {
  testWidgets('confirm → calls onDelete then onDeleted on success', (
    tester,
  ) async {
    var deleteCalled = false;
    var signedOut = false;
    await tester.pumpWidget(
      _host(
        onDelete: () async => deleteCalled = true,
        onDeleted: () => signedOut = true,
      ),
    );

    await tester.tap(find.text('Delete my account'));
    await tester.pumpAndSettle(); // confirm dialog opens
    expect(find.text('Delete your account?'), findsOneWidget);

    await tester.tap(find.widgetWithText(TextButton, 'Delete'));
    await tester.pump(); // pop dialog + start the (immediate) delete
    await tester.pump(const Duration(milliseconds: 350)); // dialog dismissed

    expect(deleteCalled, isTrue);
    expect(signedOut, isTrue);

    // Dispose the tile (the in-flight spinner ticker) so the test ends clean —
    // in production onDeleted pops the sheet, which disposes it.
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('cancel → does NOT call onDelete', (tester) async {
    var deleteCalled = false;
    await tester.pumpWidget(
      _host(onDelete: () async => deleteCalled = true, onDeleted: () {}),
    );

    await tester.tap(find.text('Delete my account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(deleteCalled, isFalse);
  });

  testWidgets('confirm dialog: Cancel is quiet grey (not accent), Delete is red',
      (tester) async {
    await tester.pumpWidget(_host(onDelete: () async {}, onDeleted: () {}));

    await tester.tap(find.text('Delete my account'));
    await tester.pumpAndSettle();

    Color? fg(String label) => tester
        .widget<TextButton>(find.widgetWithText(TextButton, label))
        .style
        ?.foregroundColor
        ?.resolve({});

    // Walid 2026-06-22: green on the SAFE action of a destructive dialog is
    // confusing — Cancel must read as a quiet grey, Delete stays red.
    expect(fg('Cancel'), AppColors.textSecondary);
    expect(fg('Delete'), AppColors.destructive);
  });

  testWidgets('server failure → inline error, no sign-out', (tester) async {
    var signedOut = false;
    await tester.pumpWidget(
      _host(
        onDelete: () async => throw Exception('boom'),
        onDeleted: () => signedOut = true,
      ),
    );

    await tester.tap(find.text('Delete my account'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Delete'));
    await tester.pumpAndSettle();

    expect(find.text(_kError), findsOneWidget);
    expect(signedOut, isFalse);
  });
}
