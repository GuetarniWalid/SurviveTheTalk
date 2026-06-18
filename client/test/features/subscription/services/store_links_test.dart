import 'package:client/features/subscription/services/store_links.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

PackageInfo _fakePackageInfo() => PackageInfo(
  appName: 'surviveTheTalk',
  packageName: 'com.surviveTheTalk.client',
  version: '1.0.0',
  buildNumber: '1',
);

void main() {
  test('iOS opens the Apple subscriptions HTTPS URL', () async {
    final launched = <Uri>[];
    final links = StoreLinks(
      platform: TargetPlatform.iOS,
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async {
        launched.add(uri);
        return true;
      },
    );

    final ok = await links.openManageSubscriptions();

    expect(ok, isTrue);
    expect(launched.single.toString(), StoreLinks.appleSubscriptionsHttps);
  });

  test('iOS falls back to the itms-apps scheme when HTTPS launch fails',
      () async {
    final launched = <Uri>[];
    final links = StoreLinks(
      platform: TargetPlatform.iOS,
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async {
        launched.add(uri);
        return uri.scheme == 'itms-apps'; // https returns false
      },
    );

    final ok = await links.openManageSubscriptions();

    expect(ok, isTrue);
    expect(launched.length, 2);
    expect(launched.last.scheme, 'itms-apps');
  });

  test('Android opens the Play deep link with BOTH sku and package', () async {
    final launched = <Uri>[];
    final links = StoreLinks(
      platform: TargetPlatform.android,
      packageInfoProvider: () async => _fakePackageInfo(),
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async {
        launched.add(uri);
        return true;
      },
    );

    final ok = await links.openManageSubscriptions();

    expect(ok, isTrue);
    final uri = launched.single;
    expect(uri.toString(), startsWith(StoreLinks.googleSubscriptionsBase));
    expect(uri.queryParameters['sku'], 'stt_weekly_199');
    expect(uri.queryParameters['package'], 'com.surviveTheTalk.client');
  });

  test('Android launches with externalApplication mode', () async {
    LaunchMode? capturedMode;
    final links = StoreLinks(
      platform: TargetPlatform.android,
      packageInfoProvider: () async => _fakePackageInfo(),
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async {
        capturedMode = mode;
        return true;
      },
    );

    await links.openManageSubscriptions();

    expect(capturedMode, LaunchMode.externalApplication);
  });

  test('returns false when every launch fails (iOS)', () async {
    final links = StoreLinks(
      platform: TargetPlatform.iOS,
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async =>
          false,
    );

    expect(await links.openManageSubscriptions(), isFalse);
  });

  test('returns false when launch throws (Android)', () async {
    final links = StoreLinks(
      platform: TargetPlatform.android,
      packageInfoProvider: () async => _fakePackageInfo(),
      launch: (uri, {LaunchMode mode = LaunchMode.platformDefault}) async =>
          throw Exception('no handler'),
    );

    expect(await links.openManageSubscriptions(), isFalse);
  });
}
