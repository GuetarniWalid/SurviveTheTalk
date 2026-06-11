"""Story 6.17 — interactive "new scenario" wizard (double-click friendly).

Run it by double-clicking `scripts\new-scenario.cmd` (Windows). It asks you, in
plain language, for: the character (shows the 5 available faces + what each looks
like), your idea (one or two sentences), and a short name. Then it builds the
WHOLE scenario (story + 20 steps + matching voice), checks it, and writes it —
optionally deploying it to the app. No need to type the long command. (Story
6.28 — scenarios carry no authored difficulty; the learner's global setting
drives it at runtime.)

Live generation needs `GROQ_API_KEY` (in server/.env); voice selection also uses
`CARTESIA_API_KEY` if present (else the default voice is kept).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from dotenv import load_dotenv  # noqa: E402

import scripts.calibration_engine as engine  # noqa: E402
import scripts.scenario_builder as builder  # noqa: E402
from scripts.build_scenario import _deploy_to_vps  # noqa: E402


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except EOFError:
        return default
    return val or default


async def _amain() -> int:
    try:
        settings = engine.load_llm_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[config error] {exc}")
        return 2

    from pipeline import scenarios

    print("\n=== Nouveau scénario ===\n")
    print(
        "Choisis le PERSONNAGE (son visage à l'écran est FIXE — on ne peut pas en créer un nouveau) :\n"
    )
    chars = list(builder.RIVE_CHARACTERS)
    for i, c in enumerate(chars, 1):
        print(f"  {i}. {c} — {builder.CHARACTER_PROFILES[c]['look']}")

    character = ""
    while not character:
        sel = _ask("\nNuméro du personnage (1-5) : ")
        if sel.isdigit() and 1 <= int(sel) <= len(chars):
            character = chars[int(sel) - 1]
        else:
            print("  -> entre un nombre entre 1 et 5.")
    print(f"  → {character}\n")

    description = ""
    while not description:
        description = _ask("Ton idée de scénario (1-2 phrases) : ")
        if not description:
            print("  -> écris au moins une phrase.")

    name = ""
    while not name:
        raw = _ask("Un mot-clé court pour nommer le scénario (ex: loyer) : ")
        slug = builder.slugify(raw, fallback="")
        if slug:
            name = slug
        else:
            print("  -> un mot (lettres/chiffres).")

    base_id = f"{character}_{name}"
    scenario_id = f"{base_id}_01"
    k = 1
    while scenario_id in scenarios._SCENARIO_INDEX:
        k += 1
        scenario_id = f"{base_id}_{k:02d}"

    print(
        f"\nGénération + vérification automatique de « {scenario_id} » "
        f"({character})...\n"
        "  L'IA écrit l'histoire + les 20 étapes, choisit la voix, PUIS vérifie que les\n"
        "  réponses hors-sujet sont bien refusées — et corrige toute seule si besoin.\n"
        "  ⏳ Sur le forfait Groq gratuit, ça peut prendre plusieurs minutes (sois patient).\n"
    )
    chat_llm, judge = engine.build_live_clients(settings)
    chat_llm = engine.ResilientChat(chat_llm)
    judge = engine.ResilientJudge(judge)
    try:
        try:
            validated = await builder.build_and_validate_scenario(
                description,
                scenario_id=scenario_id,
                rive_character=character,
                cartesia_api_key=(settings.cartesia_api_key or None),
                max_repair_rounds=10,
                llm=chat_llm,
                judge=judge,
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "rate limit" in msg or "tokens per" in msg or "rate_limit" in msg:
                print(
                    "\n❌ Limite Groq atteinte (souvent le quota JOURNALIER du forfait gratuit).\n"
                    "   Réessaie plus tard, ou passe au Dev tier. Scénario non finalisé."
                )
                return 3
            raise

        result = validated.result
        if result.structural_problems:
            print("\n❌ Problème de structure — non écrit :")
            for p in result.structural_problems:
                print(f"   - {p}")
            return 1

        out_path = builder.default_scenario_path(scenario_id)
        out_path.write_text(result.yaml_text, encoding="utf-8")

        # Pretty, readable recap so you can review the whole scenario here.
        print("\n" + builder.format_build_summary(result))

        # Verdict of the automatic validation (the off-topic-rejection net).
        # INCONCLUSIVE is checked FIRST: a rate-limited judge returns "unsure"
        # everywhere → zero failures → golden.passed would be a FALSE pass. Many
        # "unsure" verdicts = the daily Groq cap, not a genuine pass.
        g = validated.golden
        inconclusive = g.negative_warnings and len(g.negative_warnings) >= max(
            1, g.negative_total // 2
        )
        if inconclusive:
            print(
                "\n  ⚠️ Vérification INCONCLUSIVE — le juge a sûrement atteint la limite Groq "
                "(quota journalier). Le scénario est écrit ; relance la vérif plus tard."
            )
        elif g.passed:
            fixed = (
                f" (corrigé automatiquement en {validated.repair_rounds} passe·s)"
                if validated.repair_rounds
                else ""
            )
            print(
                f"\n  ✅ VALIDÉ — aucune réponse hors-sujet n'est acceptée sur les "
                f"{len(result.checkpoints)} étapes{fixed}."
            )
        else:
            print(
                f"\n  ⚠️ Après {validated.repair_rounds} correction·s (max 10), il reste "
                f"{len(g.negative_failures)} étape·s qui acceptent du hors-sujet — vrai souci à revoir."
            )

        if result.overlap_pairs:
            print("\n  ⚠️  Étapes au libellé proche (à vérifier) :")
            for a, b, jac in result.overlap_pairs:
                print(f"      {a} ~ {b}  (proximité {jac})")
        print(f"\n  📄 Fichier écrit : {out_path}")

        if (
            _ask(
                "\nDéployer sur le VPS maintenant (pour le voir dans l'appli) ? [y/N] : ",
                "n",
            )
            .lower()
            .startswith("y")
        ):
            print("   déploiement (scp + redémarrage)...")
            if _deploy_to_vps(out_path):
                print(
                    "   ✅ déployé — il devrait apparaître dans ta liste de scénarios."
                )
            else:
                print("   ❌ déploiement échoué (voir au-dessus).")
            print(
                "   ⚠️ Rappel : pour que la VOIX choisie marche, le code 6.17 doit aussi "
                "être déployé une fois (via /commit)."
            )
    finally:
        await chat_llm.aclose()
        await judge.close()

    print("\n=== Fini. ===")
    return 0


def main() -> None:
    engine.force_utf8_stdio()
    load_dotenv(dotenv_path=_HERE.parent / ".env")
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
