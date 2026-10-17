/* Narrow, opt-in functional-model hypothesis; not measured hardware semantics. */
#ifndef Z8_COMPLETED_HOLD_CONTRACT_H
#define Z8_COMPLETED_HOLD_CONTRACT_H
#include <stdbool.h>
#include <stdint.h>

typedef struct Z8CompletedHoldEvidence {
    bool enabled, capture_model, capture_control_model, ready, loose;
    bool active, held, requested, failed;
    unsigned bank;
    uint64_t value;
    uint32_t previous_control;
    uint64_t requests, jobs, starts, cancels, retired_job, ack_job, active_job, held_job;
    uint32_t input_ack, receiver_ack, source_ack;
    uint32_t input_pending, receiver_pending, source_pending;
    uint64_t jpeg_consumed[3];
} Z8CompletedHoldEvidence;

static bool z8_completed_hold_can_reconfigure(const Z8CompletedHoldEvidence *e)
{
    if (!e->enabled || !e->capture_model || !e->capture_control_model ||
        !e->ready || e->loose || e->bank != 1 || e->value != 0x103 ||
        !e->active || !e->held || e->previous_control != 0x102 ||
        e->requested || e->failed || !e->jobs || e->jobs != e->requests ||
        e->jobs != e->starts || e->active_job != e->jobs || e->held_job != e->jobs ||
        e->cancels || e->retired_job >= e->jobs ||
        e->ack_job != e->jobs || e->input_ack != 0x11 ||
        e->receiver_ack != 0x20 || e->source_ack != (1u << 20) ||
        e->input_pending || e->receiver_pending || e->source_pending) {
        return false;
    }
    for (unsigned i = 0; i < 3; i++) {
        if (e->jpeg_consumed[i] != e->jobs) {
            return false;
        }
    }
    return true;
}
#endif
