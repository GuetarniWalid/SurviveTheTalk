import 'package:bloc_test/bloc_test.dart';
import 'package:client/core/api/api_exception.dart';
import 'package:client/core/onboarding/consent_storage.dart';
import 'package:client/core/onboarding/vibration_service.dart';
import 'package:client/features/call/bloc/incoming_call_bloc.dart';
import 'package:client/features/call/bloc/incoming_call_event.dart';
import 'package:client/features/call/bloc/incoming_call_state.dart';
import 'package:client/features/call/models/call_session.dart';
import 'package:client/features/call/repositories/call_repository.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockCallRepository extends Mock implements CallRepository {}

class MockConsentStorage extends Mock implements ConsentStorage {}

class MockVibrationService extends Mock implements VibrationService {}

const _session = CallSession(
  callId: 1,
  roomName: 'call-xyz',
  token: 'user-token',
  livekitUrl: 'wss://livekit.example.com',
);

void main() {
  late MockCallRepository mockCallRepository;
  late MockConsentStorage mockConsentStorage;
  late MockVibrationService mockVibrationService;

  setUpAll(() {
    registerFallbackValue(const AcceptCallEvent());
    registerFallbackValue(const DeclineCallEvent());
  });

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    mockCallRepository = MockCallRepository();
    mockConsentStorage = MockConsentStorage();
    mockVibrationService = MockVibrationService();

    when(() => mockVibrationService.stop()).thenAnswer((_) async {});
    when(() => mockVibrationService.startRingPattern())
        .thenAnswer((_) async {});
    when(() => mockConsentStorage.saveFirstCallShown())
        .thenAnswer((_) async {});
  });

  IncomingCallBloc buildBloc() => IncomingCallBloc(
        callRepository: mockCallRepository,
        consentStorage: mockConsentStorage,
        vibrationService: mockVibrationService,
      );

  group('AcceptCallEvent', () {
    blocTest<IncomingCallBloc, IncomingCallState>(
      'happy path emits [Accepting, Connected] and saves first-call flag',
      setUp: () {
        when(() => mockCallRepository.initiateCall())
            .thenAnswer((_) async => _session);
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const AcceptCallEvent()),
      expect: () => [
        isA<IncomingCallAccepting>(),
        isA<IncomingCallConnected>()
            .having((s) => s.session.callId, 'callId', 1),
      ],
      verify: (_) {
        verify(() => mockVibrationService.stop()).called(greaterThanOrEqualTo(1));
        verify(() => mockConsentStorage.saveFirstCallShown()).called(1);
      },
    );

    blocTest<IncomingCallBloc, IncomingCallState>(
      'ApiException emits [Accepting, Error]',
      setUp: () {
        when(() => mockCallRepository.initiateCall()).thenThrow(
          const ApiException(
            code: 'NETWORK_ERROR',
            message: 'No connection.',
          ),
        );
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const AcceptCallEvent()),
      expect: () => [
        isA<IncomingCallAccepting>(),
        isA<IncomingCallError>().having(
          (s) => s.message,
          'message',
          'No connection.',
        ),
      ],
      verify: (_) {
        // AC5 spirit: persist the one-time gate once the user has SEEN the
        // screen, regardless of outcome — error loops otherwise.
        verify(() => mockConsentStorage.saveFirstCallShown()).called(1);
      },
    );

    blocTest<IncomingCallBloc, IncomingCallState>(
      'unexpected error emits generic Error message',
      setUp: () {
        when(() => mockCallRepository.initiateCall())
            .thenThrow(StateError('boom'));
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const AcceptCallEvent()),
      expect: () => [
        isA<IncomingCallAccepting>(),
        isA<IncomingCallError>().having(
          (s) => s.message,
          'message',
          'Call setup failed.',
        ),
      ],
      verify: (_) {
        verify(() => mockConsentStorage.saveFirstCallShown()).called(1);
      },
    );
  });

  group('DeclineCallEvent', () {
    blocTest<IncomingCallBloc, IncomingCallState>(
      'emits [Declined] and saves first-call flag',
      build: buildBloc,
      act: (bloc) => bloc.add(const DeclineCallEvent()),
      expect: () => [isA<IncomingCallDeclined>()],
      verify: (_) {
        verify(() => mockVibrationService.stop()).called(greaterThanOrEqualTo(1));
        verify(() => mockConsentStorage.saveFirstCallShown()).called(1);
        verifyNever(() => mockCallRepository.initiateCall());
      },
    );
  });

  group('vibration stop invariants', () {
    blocTest<IncomingCallBloc, IncomingCallState>(
      'stops vibration on Accept transition',
      setUp: () {
        when(() => mockCallRepository.initiateCall())
            .thenAnswer((_) async => _session);
      },
      build: buildBloc,
      act: (bloc) => bloc.add(const AcceptCallEvent()),
      verify: (_) {
        verify(() => mockVibrationService.stop()).called(greaterThanOrEqualTo(1));
      },
    );

    test('close() stops vibration defensively', () async {
      final bloc = buildBloc();
      await bloc.close();
      verify(() => mockVibrationService.stop()).called(greaterThanOrEqualTo(1));
    });
  });

  group('vibrationService getter', () {
    test('exposes the injected VibrationService instance', () {
      final bloc = buildBloc();
      expect(bloc.vibrationService, same(mockVibrationService));
    });
  });
}
