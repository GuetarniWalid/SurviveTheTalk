"""Test that AudioBufferProcessor is never used in pipeline code."""

from pathlib import Path


def test_no_audio_buffer_processor_in_pipeline() -> None:
    """Verify process-and-discard: AudioBufferProcessor must not appear in pipeline code."""
    pipeline_dir = Path(__file__).parent.parent / "pipeline"
    api_dir = Path(__file__).parent.parent / "api"

    for directory in (pipeline_dir, api_dir):
        for py_file in directory.glob("*.py"):
            content = py_file.read_text()
            assert "AudioBufferProcessor" not in content, (
                f"AudioBufferProcessor found in {py_file.name} — "
                "violates process-and-discard requirement"
            )
