// ignore_for_file: unused_import
//
// Compile-only smoke test: importing each new MVP dependency here catches
// broken or missing package declarations at test compile time, before any
// feature story tries to use them.

import 'package:dio/dio.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:go_router/go_router.dart';
import 'package:livekit_client/livekit_client.dart';
import 'package:rive/rive.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('all MVP dependencies import cleanly', () {
    expect(true, isTrue);
  });
}
