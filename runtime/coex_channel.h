/**
 * Coex TaskChannel - Lightweight channels for task-to-task communication
 *
 * Lock-free MPSC (Vyukov) queue for values, lock-free Treiber stack for
 * task waiters. Mutex retained only for blocking receive (condvar API).
 *
 * Features:
 * - Unbounded buffer (send never blocks)
 * - FIFO order preserved
 * - Receive suspends task if buffer empty
 * - Lock-free send and try_receive
 */

#ifndef COEX_CHANNEL_H
#define COEX_CHANNEL_H

#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdatomic.h>

/* Forward declarations */
struct SchedulerTask;

/* ============================================================================
 * Lock-Free Channel Data Structures
 * ============================================================================ */

/**
 * Node for lock-free MPSC value queue (Vyukov pattern).
 */
typedef struct ChannelNode {
    int64_t value;
    struct ChannelNode* _Atomic next;
} ChannelNode;

/**
 * Lock-free waiter node (Treiber stack).
 */
typedef struct ChannelWaiterNode {
    struct SchedulerTask* task;
    struct ChannelWaiterNode* _Atomic next;
} ChannelWaiterNode;

/**
 * TaskChannel structure.
 *
 * Layout: first 6 i64 fields for GC/codegen compatibility (opaque access).
 * The MPSC queue, waiter stack, and blocking condvar follow.
 *
 * Codegen treats channels as opaque pointers — all access goes through
 * C runtime functions (coex_channel_send, etc.). No GEP into fields.
 */
typedef struct {
    /* --- 6 i64 fields for codegen struct compatibility --- */
    int64_t _reserved0;                 /* Unused (legacy buffer_ptr) */
    int64_t _reserved1;                 /* Unused (legacy head) */
    int64_t _reserved2;                 /* Unused (legacy tail) */
    int64_t _reserved3;                 /* Unused (legacy count) */
    int64_t _reserved4;                 /* Unused (legacy waiters_ptr) */
    int64_t elem_size;                  /* Element size (8 for all types via handles) */

    /* --- Lock-free MPSC value queue (Vyukov) --- */
    ChannelNode stub;                   /* Sentinel node (never dequeued) */
    ChannelNode* _Atomic mpsc_head;     /* Consumer reads here */
    ChannelNode* _Atomic mpsc_tail;     /* Producers append here */

    /* --- Lock-free task waiter stack (Treiber) --- */
    ChannelWaiterNode* _Atomic waiter_head;

    /* --- Blocking receive support (condvar requires mutex) --- */
    atomic_int_fast64_t blocking_count; /* Number of threads blocked in receive */
    pthread_mutex_t block_mutex;        /* Only for condvar API compliance */
    pthread_cond_t block_cond;          /* Only for blocking receive */
} TaskChannel;

/* ============================================================================
 * Channel Operations
 * ============================================================================ */

/**
 * Create a new TaskChannel.
 *
 * @param elem_size  Size of each element (currently ignored, uses i64)
 * @return           Pointer to new channel (heap allocated)
 */
TaskChannel* coex_channel_new(int64_t elem_size);

/**
 * Send a value to the channel (lock-free).
 * Never blocks - unbounded buffer grows as needed.
 * If task receivers are waiting, wakes exactly one via Treiber stack.
 * If blocking receivers exist, signals condvar.
 *
 * @param channel    Channel to send to
 * @param value      Value to send (as i64)
 */
void coex_channel_send(TaskChannel* channel, int64_t value);

/**
 * Try to receive a value from the channel (lock-free).
 * If buffer has data, returns immediately.
 * If buffer empty, returns -1 to indicate task should suspend.
 *
 * @param channel    Channel to receive from
 * @param out_value  Pointer to store received value
 * @return           0 if value received, -1 if should suspend
 */
int64_t coex_channel_try_receive(TaskChannel* channel, int64_t* out_value);

/**
 * Receive a value from the channel (blocking).
 * For use from func/thread context only.
 * Uses condvar for blocking; fast path is lock-free.
 *
 * @param channel    Channel to receive from
 * @return           Received value
 */
int64_t coex_channel_receive(TaskChannel* channel);

/**
 * Add a task to the wait queue (lock-free Treiber stack push).
 * Called by scheduler when task suspends on receive.
 *
 * @param channel    Channel with wait queue
 * @param task       Task to add
 */
void coex_channel_add_waiter(TaskChannel* channel, struct SchedulerTask* task);

/**
 * Try to wake a waiting receiver (lock-free Treiber stack pop).
 * Called after send adds value to buffer.
 *
 * @param channel    Channel with wait queue
 * @return           Woken task, or NULL if no waiters
 */
struct SchedulerTask* coex_channel_wake_waiter(TaskChannel* channel);

/**
 * Get approximate buffer count.
 * Not exact due to lock-free access; sufficient for heuristics.
 *
 * @param channel    Channel to check
 * @return           Approximate number of items in buffer
 */
int64_t coex_channel_buffer_count(TaskChannel* channel);

#endif /* COEX_CHANNEL_H */
