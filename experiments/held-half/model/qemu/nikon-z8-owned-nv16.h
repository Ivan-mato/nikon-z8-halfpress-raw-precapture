/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Provenance for actual completed NV16 RAM writes. Native shooting and JPEG
 * workers overlap. Retaining metadata must not turn old RAM into a fresh
 * generation, copy pixels out of band, or release unconsumed storage. */
static bool capture_owned_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
    return a < b + m && b < a + n;
}

static bool capture_owned_conflict(const Z8OwnedNV16 *a, const Z8OwnedNV16 *b)
{
    uint64_t n = (uint64_t)a->stride * a->height;
    uint64_t m = (uint64_t)b->stride * b->height;
    return capture_owned_overlap(a->y, n, b->y, m) ||
        capture_owned_overlap(a->y, n, b->uv, m) ||
        capture_owned_overlap(a->uv, n, b->y, m) ||
        capture_owned_overlap(a->uv, n, b->uv, m);
}

static bool capture_owned_available(NikonZ8State *s, const Z8OwnedNV16 *next, unsigned count)
{
    if (!s->capture_stream_rearm_model) { return true; }
    unsigned free_slots = 0;
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_owned_nv16); i++) {
        const Z8OwnedNV16 *old = &s->capture_owned_nv16[i];
        free_slots += !old->generation || old->consumed;
        if (!old->generation || old->consumed) { continue; }
        for (unsigned j = 0; j < count; j++) {
            if (capture_owned_conflict(old, &next[j])) { return false; }
        }
    }
    return free_slots >= count;
}

/* Caller validates the entire batch before any output DMA, then publishes
 * only after all actual writes succeed. No device runs between these steps. */
static void capture_owned_publish(NikonZ8State *s, const Z8OwnedNV16 *next, unsigned count)
{
    if (!s->capture_stream_rearm_model) { return; }
    assert(capture_owned_available(s, next, count));
    for (unsigned j = 0; j < count; j++) {
        for (unsigned i = 0; i < ARRAY_SIZE(s->capture_owned_nv16); i++) {
            Z8OwnedNV16 *old = &s->capture_owned_nv16[i];
            if (old->generation && capture_owned_conflict(old, &next[j])) {
                assert(old->consumed);
                memset(old, 0, sizeof(*old));
            }
        }
        int slot = -1;
        for (unsigned i = 0; i < ARRAY_SIZE(s->capture_owned_nv16); i++) {
            if (!s->capture_owned_nv16[i].generation) { slot = i; break; }
            if (s->capture_owned_nv16[i].consumed) { slot = i; }
        }
        assert(slot >= 0);
        s->capture_owned_nv16[slot] = next[j];
    }
}

static int capture_owned_find(NikonZ8State *s, uint64_t y, uint64_t uv,
                              unsigned w, unsigned h, unsigned stride, bool padded)
{
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_owned_nv16); i++) {
        const Z8OwnedNV16 *r = &s->capture_owned_nv16[i];
        if (!r->generation || r->width != w || r->stride != stride) { continue; }
        unsigned pad = 0;
        if (padded && r->kind == 3) {
            if (h < r->height || h-r->height > 32 || ((h-r->height) & 1)) { continue; }
            pad = (h-r->height)/2;
        } else if (h != r->height) { continue; }
        uint64_t head = (uint64_t)pad*stride;
        if (r->y >= head && r->uv >= head && y == r->y-head && uv == r->uv-head) {
            return i;
        }
    }
    return -1;
}

static int capture_owned_jpeg(NikonZ8State *s, unsigned bank)
{
    const uint32_t *c = s->engine15e2_config[bank];
    return capture_owned_find(s, (uint64_t)c[0x430/4]<<4, (uint64_t)c[0x434/4]<<4,
        c[0x418/4], c[0x41c/4], c[0x410/4], true);
}
