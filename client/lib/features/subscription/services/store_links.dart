import 'package:flutter/foundation.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import 'in_app_purchase_service.dart';

/// Opens the platform-native "manage subscriptions" screen (Story 8.3, Task 7b).
///
/// `in_app_purchase` 3.3.0 exposes no in-app StoreKit `showManageSubscriptions`
/// sheet, so we hand off to the store via `url_launcher` (external app):
///   - iOS: `https://apps.apple.com/account/subscriptions`, falling back to the
///     `itms-apps://` scheme form (more reliable opener on some iOS versions).
///     UNVERIFIED on-device until Story 10-4 (design R4).
///   - Android: the product-specific deep link with BOTH `sku` + `package`
///     (`sku` alone is ignored); the `applicationId` is read at runtime from
///     `PackageInfo` (never hardcoded), falling back to the generic
///     subscriptions URL only if the deep link launch throws.
///
/// All platform calls are injectable so widget tests assert the per-platform
/// URL without touching real plugins. Returns true on a successful launch.
class StoreLinks {
  final Future<PackageInfo> Function() _packageInfo;
  final Future<bool> Function(Uri, {LaunchMode mode}) _launch;
  final TargetPlatform _platform;

  StoreLinks({
    Future<PackageInfo> Function()? packageInfoProvider,
    Future<bool> Function(Uri, {LaunchMode mode})? launch,
    TargetPlatform? platform,
  }) : _packageInfo = packageInfoProvider ?? PackageInfo.fromPlatform,
       _launch = launch ?? launchUrl,
       _platform = platform ?? defaultTargetPlatform;

  static const String appleSubscriptionsHttps =
      'https://apps.apple.com/account/subscriptions';
  static const String appleSubscriptionsScheme =
      'itms-apps://apps.apple.com/account/subscriptions';
  static const String googleSubscriptionsBase =
      'https://play.google.com/store/account/subscriptions';

  /// True when the target store is Apple's App Store. Drives the manage-drawer
  /// caption copy ("App Store" vs "Play Store") off the SAME resolved platform
  /// the launch path uses, so a test-injected `platform` flows through (never
  /// `Theme.platform`, which is wrong on foldables/desktop).
  bool get isApplePlatform => _platform == TargetPlatform.iOS;

  /// Open the native subscription-management screen. Returns true on a
  /// successful launch; the caller surfaces an inline failure message on false.
  Future<bool> openManageSubscriptions() async {
    if (_platform == TargetPlatform.iOS) {
      return _openIos();
    }
    return _openAndroid();
  }

  Future<bool> _openIos() async {
    if (await _tryLaunch(Uri.parse(appleSubscriptionsHttps))) return true;
    // Scheme fallback — the more reliable opener on some iOS versions.
    return _tryLaunch(Uri.parse(appleSubscriptionsScheme));
  }

  Future<bool> _openAndroid() async {
    Uri deepLink;
    try {
      final package = (await _packageInfo()).packageName;
      deepLink = Uri.parse(
        '$googleSubscriptionsBase?sku=$kIapWeeklyProductId&package=$package',
      );
    } catch (_) {
      deepLink = Uri.parse(googleSubscriptionsBase);
    }
    if (await _tryLaunch(deepLink)) return true;
    // Last-resort generic open if the product-specific deep link threw/failed.
    if (deepLink.toString() != googleSubscriptionsBase) {
      return _tryLaunch(Uri.parse(googleSubscriptionsBase));
    }
    return false;
  }

  Future<bool> _tryLaunch(Uri uri) async {
    try {
      return await _launch(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }
}
