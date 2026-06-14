// Story 7.3 — Debrief model parsing tests (story Task 1.4).
//
// Reference payload mirrors server/tests/test_routes_debriefs.py (the
// LOCKED DebriefOut wire contract).

import 'package:client/features/debrief/models/debrief.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> fullPayload() {
  return <String, dynamic>{
    'survival_pct': 73,
    'character_name': 'The Mugger',
    'scenario_title': 'Give me your wallet',
    'attempt_number': 2,
    'previous_best': 67,
    'errors': [
      {
        'user_said': 'I am agree',
        'correction': 'I agree',
        'context': 'Responding to the demand',
        'count': 3,
      },
    ],
    'hesitations': [
      {'duration_sec': 4.2, 'context': 'After the threat escalated'},
    ],
    'idioms': [
      {
        'expression': 'Pull the other one',
        'meaning': "I don't believe you",
        'context': 'When you claimed to have no wallet',
      },
    ],
    'areas_to_work_on': [
      "Negative sentence structure (don't/doesn't)",
      'Articles (a/an/the)',
    ],
    'inappropriate_behavior': null,
    'encouraging_framing': {
      'proximity': '27% away from surviving The Mugger',
      'improvement': '+6% since last attempt',
    },
  };
}

void main() {
  group('Debrief.tryParse — full payload', () {
    test('parses every field of the reference payload', () {
      final debrief = Debrief.tryParse(fullPayload());

      expect(debrief, isNotNull);
      expect(debrief!.survivalPct, 73);
      expect(debrief.characterName, 'The Mugger');
      expect(debrief.scenarioTitle, 'Give me your wallet');
      expect(debrief.attemptNumber, 2);
      expect(debrief.previousBest, 67);

      expect(debrief.errors, hasLength(1));
      expect(debrief.errors.first.userSaid, 'I am agree');
      expect(debrief.errors.first.correction, 'I agree');
      expect(debrief.errors.first.context, 'Responding to the demand');
      expect(debrief.errors.first.count, 3);

      expect(debrief.hesitations, hasLength(1));
      expect(debrief.hesitations.first.durationSec, 4.2);
      expect(debrief.hesitations.first.context, 'After the threat escalated');

      expect(debrief.idioms, hasLength(1));
      expect(debrief.idioms.first.expression, 'Pull the other one');
      expect(debrief.idioms.first.meaning, "I don't believe you");
      expect(
        debrief.idioms.first.context,
        'When you claimed to have no wallet',
      );

      expect(debrief.areasToWorkOn, hasLength(2));
      expect(debrief.areasToWorkOn.first, startsWith('Negative sentence'));

      expect(debrief.inappropriateBehavior, isNull);
      expect(debrief.encouragingFraming, isNotNull);
      expect(
        debrief.encouragingFraming!.proximity,
        '27% away from surviving The Mugger',
      );
      expect(debrief.encouragingFraming!.improvement, '+6% since last attempt');
    });

    test('parses inappropriate_behavior when non-null (FR37)', () {
      final payload = fullPayload()
        ..['inappropriate_behavior'] =
            'The character ended the call because of inappropriate language.';
      final debrief = Debrief.tryParse(payload);
      expect(
        debrief!.inappropriateBehavior,
        'The character ended the call because of inappropriate language.',
      );
    });
  });

  group('Debrief.tryParse — minimal payload', () {
    Map<String, dynamic> minimalPayload() {
      return <String, dynamic>{
        'survival_pct': 0,
        'character_name': 'The Waiter',
        'scenario_title': 'Order your dinner',
        'attempt_number': 1,
        'previous_best': null,
        'errors': <Object?>[],
        'hesitations': <Object?>[],
        'idioms': <Object?>[],
        'areas_to_work_on': <Object?>[],
        'inappropriate_behavior': null,
        // encouraging_framing key OMITTED entirely (server <= 40% rule).
      };
    }

    test('empty arrays + nulls + absent framing key parse cleanly', () {
      final debrief = Debrief.tryParse(minimalPayload());

      expect(debrief, isNotNull);
      expect(debrief!.previousBest, isNull);
      expect(debrief.errors, isEmpty);
      expect(debrief.hesitations, isEmpty);
      expect(debrief.idioms, isEmpty);
      expect(debrief.areasToWorkOn, isEmpty);
      expect(debrief.inappropriateBehavior, isNull);
      expect(debrief.encouragingFraming, isNull);
    });

    test('framing with a null value reads the same as an absent key', () {
      final payload = minimalPayload()..['encouraging_framing'] = null;
      expect(Debrief.tryParse(payload)!.encouragingFraming, isNull);
    });

    test('framing without improvement leaves it null', () {
      final payload = minimalPayload()
        ..['encouraging_framing'] = {'proximity': '5% away'};
      final framing = Debrief.tryParse(payload)!.encouragingFraming;
      expect(framing, isNotNull);
      expect(framing!.proximity, '5% away');
      expect(framing.improvement, isNull);
    });
  });

  group('Debrief.tryParse — structural failure → null', () {
    test('null input → null', () {
      expect(Debrief.tryParse(null), isNull);
    });

    test('missing required scalar → null', () {
      for (final key in [
        'survival_pct',
        'character_name',
        'scenario_title',
        'attempt_number',
      ]) {
        final payload = fullPayload()..remove(key);
        expect(Debrief.tryParse(payload), isNull, reason: 'missing $key');
      }
    });

    test('mistyped required scalar → null', () {
      expect(
        Debrief.tryParse(fullPayload()..['survival_pct'] = '73'),
        isNull,
      );
      expect(
        Debrief.tryParse(fullPayload()..['character_name'] = 12),
        isNull,
      );
      expect(
        Debrief.tryParse(fullPayload()..['attempt_number'] = 1.5),
        isNull,
      );
    });
  });

  group('Debrief.tryParse — defensive array handling', () {
    test('malformed array value → empty list (parse still succeeds)', () {
      final payload = fullPayload()..['errors'] = 'not-a-list';
      final debrief = Debrief.tryParse(payload);
      expect(debrief, isNotNull);
      expect(debrief!.errors, isEmpty);
    });

    test('absent array key → empty list', () {
      final payload = fullPayload()..remove('idioms');
      expect(Debrief.tryParse(payload)!.idioms, isEmpty);
    });

    test('malformed items are skipped, valid ones kept', () {
      final payload = fullPayload()
        ..['errors'] = [
          {'user_said': 'I am agree', 'correction': 'I agree'}, // no context
          'garbage',
          {
            'user_said': 'He go',
            'correction': 'He goes',
            'context': 'Describing the waiter',
            'count': 1,
          },
        ]
        ..['areas_to_work_on'] = ['Articles', 42, null, 'Past tense'];
      final debrief = Debrief.tryParse(payload)!;
      expect(debrief.errors, hasLength(1));
      expect(debrief.errors.first.userSaid, 'He go');
      expect(debrief.areasToWorkOn, ['Articles', 'Past tense']);
    });

    test('error count defaults to 1 when absent and floors at 1', () {
      final payload = fullPayload()
        ..['errors'] = [
          {'user_said': 'a', 'correction': 'b', 'context': 'c'},
          {'user_said': 'd', 'correction': 'e', 'context': 'f', 'count': 0},
        ];
      final errors = Debrief.tryParse(payload)!.errors;
      expect(errors[0].count, 1);
      expect(errors[1].count, 1);
    });

    test('whole-second hesitation duration (JSON int) parses as double', () {
      final payload = fullPayload()
        ..['hesitations'] = [
          {'duration_sec': 4, 'context': 'After the threat'},
        ];
      expect(Debrief.tryParse(payload)!.hesitations.first.durationSec, 4.0);
    });

    test('hesitations sort longest-first regardless of wire order', () {
      final payload = fullPayload()
        ..['hesitations'] = [
          {'duration_sec': 3.1, 'context': 'short'},
          {'duration_sec': 6.3, 'context': 'longest'},
          {'duration_sec': 4.8, 'context': 'middle'},
        ];
      final hesitations = Debrief.tryParse(payload)!.hesitations;
      expect(
        hesitations.map((h) => h.durationSec).toList(),
        [6.3, 4.8, 3.1],
      );
      expect(hesitations.first.context, 'longest');
    });
  });

  group('Debrief.tryParse — Story 7.5 v2 additive fields', () {
    Map<String, dynamic> v2Payload() {
      return fullPayload()
        ..['debrief_version'] = 2
        ..['errors'] = [
          {
            'user_said': 'I am agree',
            'correction': 'I agree',
            'context': 'Responding to the demand',
            'count': 3,
            'explanation': "'agree' takes no 'be': subject + agree.",
            'examples': ['I agree with you.', 'She agrees it is late.'],
          },
        ]
        ..['hesitations'] = [
          {
            'duration_sec': 6.0,
            'context': 'After the threat escalated',
            'id': 'h1',
            'resolved': false,
            'source': 'device',
          },
        ]
        ..['better_phrasings'] = [
          {
            'original': 'I will not give you the wallet',
            'suggestion': "You're not getting my wallet",
            'reason': 'More natural under pressure',
          },
        ]
        ..['checkpoints'] = [
          {'id': 'greet', 'hint': 'Greet the mugger', 'met': true},
          {'id': 'refuse', 'hint': 'Refuse to comply', 'met': false},
        ]
        ..['areas'] = [
          {
            'title': 'Negative sentence structure',
            'evidence': 'You said "I am not want"',
            'practice_prompt': 'You are an English coach...',
            'is_focus': true,
          },
          {
            'title': 'Articles',
            'evidence': 'You dropped "a" before "wallet"',
            'practice_prompt': 'Drill articles...',
          },
        ];
    }

    test('parses every v2 field', () {
      final d = Debrief.tryParse(v2Payload())!;
      expect(d.debriefVersion, 2);
      expect(
        d.errors.first.explanation,
        "'agree' takes no 'be': subject + agree.",
      );
      expect(d.errors.first.examples, [
        'I agree with you.',
        'She agrees it is late.',
      ]);
      expect(d.hesitations.first.id, 'h1');
      expect(d.hesitations.first.resolved, isFalse);
      expect(d.hesitations.first.source, 'device');
      expect(d.betterPhrasings, hasLength(1));
      expect(d.betterPhrasings.first.original, 'I will not give you the wallet');
      expect(d.betterPhrasings.first.suggestion, "You're not getting my wallet");
      expect(d.checkpoints, hasLength(2));
      expect(d.checkpoints.first.id, 'greet');
      expect(d.checkpoints.first.met, isTrue);
      expect(d.checkpoints[1].met, isFalse);
      expect(d.areas, hasLength(2));
      expect(d.areas.first.title, 'Negative sentence structure');
      expect(d.areas.first.evidence, 'You said "I am not want"');
      expect(d.areas.first.isFocus, isTrue);
      expect(d.areas[1].isFocus, isFalse);
      expect(d.areas[1].practicePrompt, 'Drill articles...');
    });

    test('a v1 payload defaults every v2 field (back-compat AC2)', () {
      final d = Debrief.tryParse(fullPayload())!;
      expect(d.debriefVersion, 1);
      expect(d.checkpoints, isEmpty);
      expect(d.betterPhrasings, isEmpty);
      expect(d.areas, isEmpty);
      expect(d.errors.first.explanation, isNull);
      expect(d.errors.first.examples, isEmpty);
      expect(d.hesitations.first.id, isNull);
      expect(d.hesitations.first.resolved, isTrue);
      expect(d.hesitations.first.source, 'server');
    });

    test('malformed v2 items are skipped defensively', () {
      final payload = v2Payload()
        ..['checkpoints'] = [
          {'id': 'greet', 'hint': 'Greet', 'met': true},
          {'id': 'x', 'hint': 'no met flag'}, // missing met → skipped
          'garbage',
        ]
        ..['better_phrasings'] = [
          {'original': 'a', 'suggestion': 'b'}, // missing reason → skipped
          {'original': 'c', 'suggestion': 'd', 'reason': 'e'},
        ]
        ..['areas'] = [
          {'evidence': 'no title'}, // missing title → skipped
          {'title': 'Kept'},
        ];
      final d = Debrief.tryParse(payload)!;
      expect(d.checkpoints, hasLength(1));
      expect(d.checkpoints.first.id, 'greet');
      expect(d.betterPhrasings, hasLength(1));
      expect(d.betterPhrasings.first.reason, 'e');
      expect(d.areas, hasLength(1));
      expect(d.areas.first.title, 'Kept');
      // an area with only a title keeps the defensive defaults
      expect(d.areas.first.evidence, '');
      expect(d.areas.first.practicePrompt, '');
      expect(d.areas.first.isFocus, isFalse);
    });

    test('hesitation resolved/source default when absent', () {
      final payload = fullPayload()
        ..['hesitations'] = [
          {'duration_sec': 5.0, 'context': 'x', 'id': 'h9'},
        ];
      final h = Debrief.tryParse(payload)!.hesitations.first;
      expect(h.id, 'h9');
      expect(h.resolved, isTrue);
      expect(h.source, 'server');
    });
  });
}
