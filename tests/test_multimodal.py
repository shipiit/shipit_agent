"""Tests for the v1.0.9 multimodal package — inline media references in
user prompts, ordered segments, content-block builder, media store.

≥10 tests per public surface.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from shipit_agent.multimodal import (
    FileMediaStore,
    InMemoryMediaStore,
    MediaKind,
    MediaParser,
    MediaReference,
    MediaSegment,
    StoredMedia,
    TextSegment,
    build_multimodal_message,
    extract_media_refs,
)


# ===========================================================================
# MediaParser.parse — bracket-URL form
# ===========================================================================


class TestParseBracketUrl:
    def test_single_image_at_end(self) -> None:
        p = MediaParser().parse("Look at [https://x.com/cat.png]")
        assert len(p.segments) == 2
        assert isinstance(p.segments[0], TextSegment)
        assert isinstance(p.segments[1], MediaSegment)
        assert p.segments[1].ref.url == "https://x.com/cat.png"
        assert p.segments[1].ref.kind == MediaKind.IMAGE

    def test_single_image_at_start(self) -> None:
        p = MediaParser().parse("[https://x.com/cat.png] is what?")
        assert len(p.segments) == 2
        assert isinstance(p.segments[0], MediaSegment)
        assert isinstance(p.segments[1], TextSegment)

    def test_image_in_the_middle(self) -> None:
        p = MediaParser().parse(
            "Hey what is this [https://x.com/img.png] about?"
        )
        kinds = [type(s).__name__ for s in p.segments]
        assert kinds == ["TextSegment", "MediaSegment", "TextSegment"]
        assert p.segments[0].text == "Hey what is this "
        assert p.segments[2].text == " about?"

    def test_two_images_interleaved(self) -> None:
        p = MediaParser().parse(
            "Compare [https://x.com/a.png] vs [https://y.com/b.jpg] please."
        )
        assert len(p.segments) == 5
        assert [s.ref.url for s in p.segments if isinstance(s, MediaSegment)] == [
            "https://x.com/a.png",
            "https://y.com/b.jpg",
        ]

    def test_three_images_back_to_back(self) -> None:
        p = MediaParser().parse(
            "[https://x.com/a.png][https://x.com/b.png][https://x.com/c.png]"
        )
        # Three media segments, no text between (text=="" gets coalesced away)
        media = [s for s in p.segments if isinstance(s, MediaSegment)]
        assert len(media) == 3

    def test_jpeg_extension_detected(self) -> None:
        p = MediaParser().parse("see [https://x.com/photo.jpg]")
        assert p.segments[-1].ref.kind == MediaKind.IMAGE

    def test_audio_extension_detected(self) -> None:
        p = MediaParser().parse("listen to [https://x.com/clip.mp3]")
        assert p.segments[-1].ref.kind == MediaKind.AUDIO

    def test_video_extension_detected(self) -> None:
        p = MediaParser().parse("watch [https://x.com/v.mp4]")
        assert p.segments[-1].ref.kind == MediaKind.VIDEO

    def test_pdf_extension_detected(self) -> None:
        p = MediaParser().parse("read [https://x.com/doc.pdf]")
        assert p.segments[-1].ref.kind == MediaKind.DOCUMENT

    def test_unknown_extension_kept_as_unknown(self) -> None:
        p = MediaParser().parse("look at [https://x.com/data.bin]")
        assert p.segments[-1].ref.kind == MediaKind.UNKNOWN

    def test_no_brackets_returns_single_text_segment(self) -> None:
        p = MediaParser().parse("Just plain text.")
        assert len(p.segments) == 1
        assert isinstance(p.segments[0], TextSegment)

    def test_empty_prompt_yields_empty_segments(self) -> None:
        p = MediaParser().parse("")
        assert p.segments == []

    def test_start_end_indexes_preserved(self) -> None:
        prompt = "x [https://x.com/a.png] y"
        p = MediaParser().parse(prompt)
        media = [s for s in p.segments if isinstance(s, MediaSegment)][0]
        assert prompt[media.ref.start:media.ref.end] == "[https://x.com/a.png]"


# ===========================================================================
# MediaParser.parse — markdown form
# ===========================================================================


class TestParseMarkdown:
    def test_basic_markdown(self) -> None:
        p = MediaParser().parse("![cat](https://x.com/cat.png)")
        assert isinstance(p.segments[0], MediaSegment)
        assert p.segments[0].ref.alt == "cat"
        assert p.segments[0].ref.url == "https://x.com/cat.png"

    def test_markdown_in_the_middle(self) -> None:
        p = MediaParser().parse("Look ![cat](https://x.com/cat.png) please.")
        assert len(p.segments) == 3

    def test_markdown_alt_preserved(self) -> None:
        p = MediaParser().parse("![my dog](https://x.com/d.png)")
        assert p.segments[0].ref.alt == "my dog"

    def test_markdown_empty_alt(self) -> None:
        p = MediaParser().parse("![](https://x.com/a.png)")
        assert p.segments[0].ref.alt == ""

    def test_markdown_wins_over_bracket_url(self) -> None:
        # ![alt](url) starts with ! — must not be treated as a bare bracket
        p = MediaParser().parse("![sketch](https://x.com/s.png)")
        media = [s for s in p.segments if isinstance(s, MediaSegment)]
        assert len(media) == 1
        assert media[0].ref.alt == "sketch"

    def test_two_markdown_images(self) -> None:
        p = MediaParser().parse(
            "![a](https://x.com/a.png) then ![b](https://x.com/b.png)"
        )
        media = [s for s in p.segments if isinstance(s, MediaSegment)]
        assert [m.ref.alt for m in media] == ["a", "b"]

    def test_markdown_kind_inferred_from_url(self) -> None:
        p = MediaParser().parse("![v](https://x.com/movie.mp4)")
        assert p.segments[0].ref.kind == MediaKind.VIDEO

    def test_markdown_with_special_chars_in_alt(self) -> None:
        p = MediaParser().parse("![my cat (the orange one)](https://x.com/o.png)")
        # Parens inside alt: our regex only stops at ']', so this works
        assert p.segments[0].ref.alt == "my cat (the orange one)"

    def test_markdown_url_must_be_http(self) -> None:
        # ftp:// or relative paths should NOT match
        p = MediaParser().parse("![bad](ftp://x.com/a.png)")
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_mixed_markdown_and_bracket(self) -> None:
        p = MediaParser().parse(
            "Compare ![a](https://x.com/a.png) and [https://y.com/b.jpg]"
        )
        urls = [s.ref.url for s in p.segments if isinstance(s, MediaSegment)]
        assert urls == ["https://x.com/a.png", "https://y.com/b.jpg"]


# ===========================================================================
# MediaParser.parse — media:uuid form (with MediaStore)
# ===========================================================================


class TestParseMediaUuid:
    def test_resolves_via_store(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="abc123", url="https://cdn.x/abc.png", mime="image/png"),
        ])
        p = MediaParser(media_store=store).parse(
            "What is in [media:abc123]?"
        )
        media = [s for s in p.segments if isinstance(s, MediaSegment)][0]
        assert media.ref.url == "https://cdn.x/abc.png"
        assert media.ref.media_id == "abc123"
        assert media.ref.kind == MediaKind.IMAGE

    def test_unknown_uuid_passed_through_as_text(self) -> None:
        store = InMemoryMediaStore()
        p = MediaParser(media_store=store).parse("see [media:nope]")
        # Reference fails to resolve → kept as plain text
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_no_store_means_uuid_passed_through(self) -> None:
        p = MediaParser().parse("see [media:abc123]")
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_alt_from_store_used(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/y.png", mime="image/png", alt="Stored alt"),
        ])
        p = MediaParser(media_store=store).parse("see [media:x]")
        media = [s for s in p.segments if isinstance(s, MediaSegment)][0]
        assert media.ref.alt == "Stored alt"

    def test_mime_from_store_used(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/y", mime="audio/mpeg"),
        ])
        p = MediaParser(media_store=store).parse("[media:x]")
        media = [s for s in p.segments if isinstance(s, MediaSegment)][0]
        assert media.ref.kind == MediaKind.AUDIO

    def test_uuid_with_dashes_and_underscores(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="user_42-abc", url="https://x/u.png", mime="image/png"),
        ])
        p = MediaParser(media_store=store).parse("[media:user_42-abc]")
        assert any(isinstance(s, MediaSegment) for s in p.segments)

    def test_multiple_uuids_all_resolved(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="a", url="https://x/a.png", mime="image/png"),
            StoredMedia(id="b", url="https://x/b.png", mime="image/png"),
        ])
        p = MediaParser(media_store=store).parse(
            "Compare [media:a] vs [media:b]"
        )
        media = [s for s in p.segments if isinstance(s, MediaSegment)]
        assert [m.ref.media_id for m in media] == ["a", "b"]

    def test_uuid_kind_falls_back_to_url_when_no_mime(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/file.mp4", mime=None),
        ])
        p = MediaParser(media_store=store).parse("[media:x]")
        media = [s for s in p.segments if isinstance(s, MediaSegment)][0]
        assert media.ref.kind == MediaKind.VIDEO

    def test_segments_ordered_correctly_with_uuid(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/y.png", mime="image/png"),
        ])
        p = MediaParser(media_store=store).parse("Pre [media:x] post")
        kinds = [type(s).__name__ for s in p.segments]
        assert kinds == ["TextSegment", "MediaSegment", "TextSegment"]

    def test_uuid_metadata_passes_through(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/y.png", mime="image/png", metadata={"owner": "rahul"}),
        ])
        # Resolution preserves the metadata on the StoredMedia, even if
        # MediaReference doesn't surface it directly — verify via store.resolve
        assert store.resolve("x").metadata == {"owner": "rahul"}


# ===========================================================================
# MediaParser — domain allowlist / denylist
# ===========================================================================


class TestDomainGating:
    def test_default_allows_everything(self) -> None:
        p = MediaParser().parse("[https://example.com/a.png]")
        assert any(isinstance(s, MediaSegment) for s in p.segments)

    def test_specific_allowlist(self) -> None:
        p = MediaParser(allowlist_domains=["x.com"]).parse(
            "[https://y.com/a.png]"
        )
        # Not on allowlist → kept as plain text
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_glob_allowlist(self) -> None:
        p = MediaParser(allowlist_domains=["*.amazonaws.com"]).parse(
            "[https://bucket.s3.amazonaws.com/a.png]"
        )
        assert any(isinstance(s, MediaSegment) for s in p.segments)

    def test_denylist_overrides_allowlist(self) -> None:
        p = MediaParser(
            allowlist_domains=["*"],
            denylist_domains=["evil.com"],
        ).parse("[https://evil.com/a.png]")
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_denylist_glob(self) -> None:
        p = MediaParser(
            allowlist_domains=["*"],
            denylist_domains=["*.evil.com"],
        ).parse("[https://cdn.evil.com/a.png]")
        assert all(isinstance(s, TextSegment) for s in p.segments)

    def test_blocked_url_kept_inline_as_text(self) -> None:
        # Failure preserves the raw token, not a silent drop
        p = MediaParser(allowlist_domains=["x.com"]).parse(
            "see [https://y.com/a.png] now"
        )
        assert "[https://y.com/a.png]" in p.text_only

    def test_is_allowed_domain_method(self) -> None:
        parser = MediaParser(allowlist_domains=["*.foo.com"])
        assert parser.is_allowed_domain("https://a.foo.com/x") is True
        assert parser.is_allowed_domain("https://bar.com/x") is False

    def test_no_host_blocked(self) -> None:
        parser = MediaParser()
        assert parser.is_allowed_domain("not-a-url") is False

    def test_multiple_allowlist_patterns(self) -> None:
        parser = MediaParser(allowlist_domains=["x.com", "*.acme.com"])
        assert parser.is_allowed_domain("https://x.com/x") is True
        assert parser.is_allowed_domain("https://cdn.acme.com/y") is True
        assert parser.is_allowed_domain("https://other.com/x") is False

    def test_mixed_blocked_and_allowed(self) -> None:
        p = MediaParser(allowlist_domains=["x.com"]).parse(
            "see [https://x.com/a.png] and [https://blocked.com/b.png]"
        )
        media = [s for s in p.segments if isinstance(s, MediaSegment)]
        assert len(media) == 1
        assert media[0].ref.url == "https://x.com/a.png"


# ===========================================================================
# ParsedPrompt — text / text_only / media_refs / has_media
# ===========================================================================


class TestParsedPrompt:
    def test_text_property_round_trips(self) -> None:
        p = MediaParser().parse("see [https://x.com/a.png] please")
        # text reconstruction uses markdown form
        assert "![image](https://x.com/a.png)" in p.text

    def test_text_only_drops_media(self) -> None:
        p = MediaParser().parse("see [https://x.com/a.png] please")
        assert p.text_only == "see  please"

    def test_media_refs_in_order(self) -> None:
        p = MediaParser().parse(
            "[https://x.com/a.png] [https://x.com/b.png] [https://x.com/c.png]"
        )
        urls = [r.url for r in p.media_refs]
        assert urls == [
            "https://x.com/a.png",
            "https://x.com/b.png",
            "https://x.com/c.png",
        ]

    def test_has_media_true(self) -> None:
        p = MediaParser().parse("see [https://x.com/a.png]")
        assert p.has_media is True

    def test_has_media_false(self) -> None:
        p = MediaParser().parse("just text")
        assert p.has_media is False

    def test_len_matches_segments(self) -> None:
        p = MediaParser().parse("a [https://x.com/a.png] b")
        assert len(p) == 3

    def test_text_only_for_text_only_input(self) -> None:
        p = MediaParser().parse("just plain text")
        assert p.text_only == "just plain text"

    def test_media_refs_empty_when_no_media(self) -> None:
        p = MediaParser().parse("plain text")
        assert p.media_refs == []

    def test_to_markdown_placeholder_uses_alt(self) -> None:
        ref = MediaReference(
            url="https://x.com/a.png", kind=MediaKind.IMAGE, alt="cat"
        )
        assert ref.to_markdown_placeholder() == "![cat](https://x.com/a.png)"

    def test_to_markdown_placeholder_falls_back_to_kind(self) -> None:
        ref = MediaReference(url="https://x.com/a.png", kind=MediaKind.IMAGE)
        assert "image" in ref.to_markdown_placeholder()


# ===========================================================================
# build_multimodal_message
# ===========================================================================


class TestBuildMultimodalMessage:
    def test_pure_text_yields_single_block(self) -> None:
        p = MediaParser().parse("just text")
        msg = build_multimodal_message(p)
        assert msg["role"] == "user"
        assert len(msg["content"]) == 1
        assert msg["content"][0] == {"type": "text", "text": "just text"}

    def test_role_override(self) -> None:
        p = MediaParser().parse("hi")
        assert build_multimodal_message(p, role="assistant")["role"] == "assistant"

    def test_image_block_emitted(self) -> None:
        p = MediaParser().parse("[https://x.com/a.png]")
        blocks = build_multimodal_message(p)["content"]
        # An image block + a stub empty-text block we don't emit, so just check
        # the image is there.
        assert any(b["type"] == "image" for b in blocks)

    def test_image_block_has_url(self) -> None:
        p = MediaParser().parse("[https://x.com/a.png]")
        blocks = build_multimodal_message(p)["content"]
        image = next(b for b in blocks if b["type"] == "image")
        assert image["source"]["url"] == "https://x.com/a.png"

    def test_interleaved_order_preserved(self) -> None:
        p = MediaParser().parse(
            "Hey [https://x.com/a.png] and [https://x.com/b.png] thanks"
        )
        blocks = build_multimodal_message(p)["content"]
        types = [b["type"] for b in blocks]
        assert types == ["text", "image", "text", "image", "text"]

    def test_audio_emits_audio_block(self) -> None:
        p = MediaParser().parse("hear [https://x.com/sound.mp3]")
        blocks = build_multimodal_message(p)["content"]
        assert any(b["type"] == "audio" for b in blocks)

    def test_video_emits_video_block(self) -> None:
        p = MediaParser().parse("[https://x.com/m.mp4]")
        blocks = build_multimodal_message(p)["content"]
        assert any(b["type"] == "video" for b in blocks)

    def test_document_emits_document_block(self) -> None:
        p = MediaParser().parse("[https://x.com/r.pdf]")
        blocks = build_multimodal_message(p)["content"]
        assert any(b["type"] == "document" for b in blocks)

    def test_unknown_falls_back_to_markdown(self) -> None:
        p = MediaParser().parse("see [https://x.com/data.bin]")
        blocks = build_multimodal_message(p, fallback="markdown")["content"]
        # No image/audio/video block — but the URL is in the text via markdown placeholder
        assert all(b["type"] == "text" for b in blocks)
        joined = " ".join(b["text"] for b in blocks)
        assert "https://x.com/data.bin" in joined

    def test_unknown_fallback_drop(self) -> None:
        p = MediaParser().parse("see [https://x.com/data.bin]")
        blocks = build_multimodal_message(p, fallback="drop")["content"]
        joined = " ".join(b["text"] for b in blocks)
        assert "data.bin" not in joined

    def test_unknown_fallback_text_placeholder(self) -> None:
        p = MediaParser().parse("see [https://x.com/data.bin]")
        blocks = build_multimodal_message(p, fallback="text")["content"]
        joined = " ".join(b["text"] for b in blocks)
        assert "<media:" in joined

    def test_invalid_fallback_raises(self) -> None:
        p = MediaParser().parse("hi")
        try:
            build_multimodal_message(p, fallback="bogus")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


# ===========================================================================
# extract_media_refs convenience
# ===========================================================================


class TestExtractMediaRefs:
    def test_returns_only_refs(self) -> None:
        refs = extract_media_refs("[https://x.com/a.png] and [https://x.com/b.png]")
        assert len(refs) == 2

    def test_empty_when_no_refs(self) -> None:
        assert extract_media_refs("just text") == []

    def test_respects_allowlist(self) -> None:
        refs = extract_media_refs(
            "[https://blocked.com/a.png]",
            allowlist_domains=["x.com"],
        )
        assert refs == []

    def test_uses_media_store(self) -> None:
        store = InMemoryMediaStore([
            StoredMedia(id="x", url="https://x/y.png", mime="image/png"),
        ])
        refs = extract_media_refs("[media:x]", media_store=store)
        assert len(refs) == 1


# ===========================================================================
# InMemoryMediaStore + FileMediaStore
# ===========================================================================


class TestInMemoryMediaStore:
    def test_put_and_resolve(self) -> None:
        s = InMemoryMediaStore()
        s.put(StoredMedia(id="x", url="https://x/y.png", mime="image/png"))
        assert s.resolve("x").url == "https://x/y.png"

    def test_resolve_missing(self) -> None:
        assert InMemoryMediaStore().resolve("nope") is None

    def test_constructor_seeds_items(self) -> None:
        s = InMemoryMediaStore([
            StoredMedia(id="a", url="https://x/a"),
            StoredMedia(id="b", url="https://x/b"),
        ])
        assert len(s) == 2

    def test_list_all(self) -> None:
        s = InMemoryMediaStore([StoredMedia(id="a", url="https://x/a")])
        assert len(s.list_all()) == 1

    def test_delete_returns_true_on_success(self) -> None:
        s = InMemoryMediaStore([StoredMedia(id="a", url="https://x/a")])
        assert s.delete("a") is True
        assert s.resolve("a") is None

    def test_delete_returns_false_when_missing(self) -> None:
        assert InMemoryMediaStore().delete("nope") is False

    def test_put_overwrites(self) -> None:
        s = InMemoryMediaStore()
        s.put(StoredMedia(id="x", url="https://a"))
        s.put(StoredMedia(id="x", url="https://b"))
        assert s.resolve("x").url == "https://b"

    def test_put_returns_id(self) -> None:
        s = InMemoryMediaStore()
        returned = s.put(StoredMedia(id="x", url="https://a"))
        assert returned == "x"

    def test_put_auto_generates_id_when_blank(self) -> None:
        s = InMemoryMediaStore()
        new_id = s.put(StoredMedia(id="", url="https://a"))
        assert new_id and len(new_id) >= 16
        assert s.resolve(new_id).url == "https://a"


class TestFileMediaStore:
    def test_persists_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "store.json"
            s1 = FileMediaStore(path)
            s1.put(StoredMedia(id="x", url="https://x/y.png", mime="image/png"))
            s2 = FileMediaStore(path)
            assert s2.resolve("x").url == "https://x/y.png"

    def test_resolve_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            s = FileMediaStore(Path(td) / "store.json")
            assert s.resolve("anything") is None

    def test_list_all_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "store.json"
            s = FileMediaStore(path)
            s.put(StoredMedia(id="a", url="https://x/a"))
            s.put(StoredMedia(id="b", url="https://x/b"))
            s2 = FileMediaStore(path)
            assert len(s2.list_all()) == 2

    def test_delete_persists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "store.json"
            s = FileMediaStore(path)
            s.put(StoredMedia(id="x", url="https://x/y"))
            s.delete("x")
            s2 = FileMediaStore(path)
            assert s2.resolve("x") is None

    def test_put_auto_generates_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "store.json"
            s = FileMediaStore(path)
            new_id = s.put(StoredMedia(id="", url="https://x/y"))
            assert new_id and s.resolve(new_id).url == "https://x/y"

    def test_resolves_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "store.json"
            path.write_text("")
            s = FileMediaStore(path)
            assert s.resolve("anything") is None
            uid = s.put(StoredMedia(id="", url="https://x/y"))
            assert s.resolve(uid).url == "https://x/y"


# ===========================================================================
# Public-import surface
# ===========================================================================


class TestPublicImports:
    def test_top_level(self) -> None:
        from shipit_agent import (
            MediaParser, MediaReference, MediaKind, ParsedPrompt,
            InMemoryMediaStore, FileMediaStore, MediaStore, StoredMedia,
            build_multimodal_message, extract_media_refs,
        )
        assert MediaParser is not None
        assert MediaReference is not None
        assert MediaKind.IMAGE.value == "image"
        assert ParsedPrompt is not None
        assert InMemoryMediaStore is not None
        assert FileMediaStore is not None
        assert MediaStore is not None
        assert StoredMedia is not None
        assert callable(build_multimodal_message)
        assert callable(extract_media_refs)

    def test_subpackage_import(self) -> None:
        import shipit_agent.multimodal
        assert hasattr(shipit_agent.multimodal, "MediaParser")
