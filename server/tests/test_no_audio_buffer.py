"""Test that AudioBufferProcessor is never used in pipeline code."""

from pathlib import Path


def test_no_audio_buffer_processor_in_pipeline() -> None:
    """Verify process-and-discard: AudioBufferProcessor must not appear in pipeline code."""
    pipeline_dir = Path(__file__).parent.parent / "pipeline"
    api_dir = Path(__file__).parent.parent / "api"

    for directory in (pipeline_dir, api_dir):
        for py_file in directory.glob("*.py"):
            # Story 6.9b polish — explicit utf-8 (was relying on platform
            # default which is cp1252 on Windows and breaks the moment any
            # docstring contains a non-Latin-1 char like an em-dash).
            content = py_file.read_text(encoding="utf-8")
            assert "AudioBufferProcessor" not in content, (
                f"AudioBufferProcessor found in {py_file.name} — "
                "violates process-and-discard requirement"
            )
