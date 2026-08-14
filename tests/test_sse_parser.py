"""Spec §19 items 3 and 5 — SSE parsing and the [DONE] marker."""

from __future__ import annotations

from pipeline.hermes import HermesSSEChunk, parse_chat_chunk, parse_sse_lines


async def _collect(lines) -> list[HermesSSEChunk]:
    return [chunk async for chunk in parse_sse_lines(lines)]


async def _collect_async(source) -> list[HermesSSEChunk]:
    async def _source():
        for line in source:
            yield line

    return [chunk async for chunk in parse_sse_lines(_source())]


async def test_simple_data_frame():
    chunks = await _collect(['data: {"a": 1}', ""])
    assert len(chunks) == 1
    assert chunks[0].event is None
    assert chunks[0].data == '{"a": 1}'


async def test_event_and_data_pairing():
    chunks = await _collect(
        ['event: hermes.tool.progress', 'data: {"tool_name":"bash"}', ""]
    )
    assert len(chunks) == 1
    assert chunks[0].event == "hermes.tool.progress"
    assert chunks[0].data == '{"tool_name":"bash"}'


async def test_keepalive_comments_are_ignored():
    chunks = await _collect(
        ['data: {"n":1}', "", ": keepalive", "", 'data: {"n":2}', ""]
    )
    assert [c.data for c in chunks] == ['{"n":1}', '{"n":2}']


async def test_multiline_data_is_joined():
    chunks = await _collect(["data: line1", "data: line2", ""])
    assert chunks[0].data == "line1\nline2"


async def test_trailing_frame_without_blank_line_is_flushed():
    chunks = await _collect(['data: {"n":1}'])
    assert [c.data for c in chunks] == ['{"n":1}']


async def test_empty_input_yields_nothing():
    assert await _collect([]) == []


async def test_async_line_source_is_supported():
    chunks = await _collect_async(['data: {"n":1}', ""])
    assert [c.data for c in chunks] == ['{"n":1}']


def test_done_marker_parses_as_done():
    chunk = parse_chat_chunk(HermesSSEChunk(data="[DONE]"))
    assert chunk.done is True
    assert chunk.text_delta is None
    assert chunk.tool_progress is None


def test_text_delta_is_extracted():
    chunk = parse_chat_chunk(
        HermesSSEChunk(
            data='{"choices":[{"index":0,"delta":{"content":"Olá"},"finish_reason":null}]}'
        )
    )
    assert chunk.text_delta == "Olá"
    assert chunk.finish_reason is None


def test_role_only_chunk_has_no_text():
    chunk = parse_chat_chunk(
        HermesSSEChunk(
            data='{"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}'
        )
    )
    assert chunk.text_delta is None
    assert not chunk.done


def test_unparseable_data_is_skipped_not_raised():
    chunk = parse_chat_chunk(HermesSSEChunk(data="this is not json"))
    assert chunk.text_delta is None
    assert chunk.tool_progress is None
    assert not chunk.done
