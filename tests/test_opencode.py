"""Unit tests for the pure helpers in companion.opencode (no subprocess/network)."""

import sys

import pytest

from companion import opencode as oc


def test_oneline_collapses_whitespace_and_truncates():
    assert oc._oneline("  a\n b   c ") == "a b c"
    out = oc._oneline("x" * 100, 10)
    assert len(out) == 10 and out.endswith("…")


def test_part_text_skips_thinking_prefers_text():
    assert oc._part_text({"type": "reasoning", "text": "thoughts"}) == ""
    assert oc._part_text({"type": "text", "text": " hello "}) == "hello"


def test_part_text_falls_back_to_tool_output():
    assert oc._part_text({"type": "tool", "state": {"output": "ran ok"}}) == "ran ok"
    assert oc._part_text({"type": "tool", "state": {"title": "Read x"}}) == "Read x"
    assert oc._part_text({"type": "tool", "state": {}}) == ""


def test_think_text_only_for_reasoning():
    assert oc._think_text({"type": "thinking", "text": "hmm"}) == "hmm"
    assert oc._think_text({"type": "text", "text": "answer"}) == ""


def test_tool_activity_detail_priority_and_basename():
    assert oc._tool_activity({"tool": "bash", "state": {"input": {"command": "npm test"}}}) == "bash\tnpm test"
    assert oc._tool_activity({"tool": "grep", "state": {"input": {"pattern": "foo"}}}) == "grep\tfoo"
    assert oc._tool_activity({"tool": "read", "state": {"input": {"filePath": "/a/b/c.py"}}}) == "read\tc.py"
    assert oc._tool_activity({"tool": "noop", "state": {"input": {}}}) == "noop"


def test_parse_skill_inline_description(tmp_path):
    sf = tmp_path / "SKILL.md"
    sf.write_text("---\nname: caveman\ndescription: Talk terse.\n---\nbody\n", encoding="utf-8")
    assert oc._parse_skill(sf, "fallback") == ("caveman", "Talk terse.")


def test_parse_skill_falls_back_to_dirname_without_frontmatter(tmp_path):
    sf = tmp_path / "SKILL.md"
    sf.write_text("no frontmatter here\n", encoding="utf-8")
    assert oc._parse_skill(sf, "mydir") == ("mydir", "")


def test_real_exe_passthrough_for_plain_executable(tmp_path):
    exe = tmp_path / "opencode"
    exe.write_text("x", encoding="utf-8")
    assert oc._real_exe(str(exe)) == str(exe)


@pytest.mark.skipif(sys.platform != "win32", reason="npm .cmd shim resolution is Windows-only")
def test_real_exe_resolves_windows_cmd_shim(tmp_path):
    exe = tmp_path / "opencode.exe"
    exe.write_text("binary", encoding="utf-8")
    cmd = tmp_path / "opencode.cmd"
    cmd.write_text('@ECHO off\n"%~dp0\\opencode.exe"   %*\n', encoding="utf-8")
    from pathlib import Path
    assert Path(oc._real_exe(str(cmd))) == exe
