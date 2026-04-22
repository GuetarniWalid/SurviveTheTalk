import 'package:permission_handler/permission_handler.dart';

class PermissionService {
  Future<PermissionStatus> checkMicPermission() =>
      Permission.microphone.status;

  Future<PermissionStatus> requestMicPermission() =>
      Permission.microphone.request();

  Future<bool> openSettings() => openAppSettings();
}
