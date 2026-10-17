/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Completed RAW DMA ownership. Sensor input, 153 processing, 151 side
 * output and compression can overlap; a global latest-frame number cannot
 * identify an earlier RAM buffer. Metadata is published only after DMA. */
static int raw_owned_find(const Z8OwnedRaw *records, unsigned count, uint64_t address,
                          unsigned width, unsigned height, unsigned stride, unsigned format)
{
    for (unsigned i = 0; i < count; i++) {
        const Z8OwnedRaw *r = &records[i];
        if (r->generation && r->address == address && r->width == width &&
            r->height == height && r->stride == stride && r->format == format &&
            r->bytes == (uint64_t)stride * height) { return i; }
    }
    return -1;
}

static bool raw_owned_overlap(const Z8OwnedRaw *a, const Z8OwnedRaw *b)
{
    return a->address < b->address+b->bytes && b->address < a->address+a->bytes;
}

static int raw_owned_slot(const Z8OwnedRaw *records, unsigned count, const Z8OwnedRaw *next)
{
    int slot = -1;
    for (unsigned i = 0; i < count; i++) {
        const Z8OwnedRaw *r = &records[i];
        if (r->generation && !r->consumed && raw_owned_overlap(r, next)) { return -1; }
        if (!r->generation || r->consumed) { slot = i; }
    }
    return slot;
}

static void raw_owned_publish(Z8OwnedRaw *records, unsigned count,
                              const Z8OwnedRaw *next, int slot)
{
    assert(slot >= 0 && (unsigned)slot < count);
    for (unsigned i = 0; i < count; i++) {
        if (records[i].generation && raw_owned_overlap(&records[i], next)) {
            assert(records[i].consumed);
            memset(&records[i], 0, sizeof(records[i]));
        }
    }
    records[slot] = *next;
}
