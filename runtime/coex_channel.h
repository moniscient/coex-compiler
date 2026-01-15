/**
 * Coex TaskChannel - Lightweight channels for task-to-task communication
 *
 * TaskChannels use scheduler-managed wait queues with no mutex overhead.
 * They are designed for task-to-task communication within the work-stealing scheduler.
 *
 * Features:
 * - Unbounded buffer (send never blocks)
 * - FIFO order preserved
 * - Receive suspends task if buffer empty
 * - GC-managed memory
 */

#ifndef COEX_CHANNEL_H
#define COEX_CHANNEL_H

#include <stdint.h>
#include <stdbool.h>

/* Forward declarations */
struct SchedulerTask;

/* ============================================================================
 * Channel Data Structures
 * ============================================================================ */

/**
 * Wait node for tasks blocked on channel receive.
 */
typedef struct ChannelWaitNode {
    struct SchedulerTask* task;         /* Waiting task */
    struct ChannelWaitNode* next;       /* Next in queue */
} ChannelWaitNode;

/**
 * Wait queue for blocked receivers.
 */
typedef struct {
    ChannelWaitNode* head;              /* First waiter */
    ChannelWaitNode* tail;              /* Last waiter */
    int64_t count;                      /* Number of waiters */
} ChannelWaitQueue;

/**
 * Ring buffer for channel values.
 * Grows dynamically as needed.
 */
typedef struct {
    int64_t* data;                      /* Circular buffer of i64 values */
    int64_t capacity;                   /* Current capacity */
    int64_t head;                       /* Read position */
    int64_t tail;                       /* Write position */
    int64_t count;                      /* Current item count */
} ChannelBuffer;

/**
 * TaskChannel structure.
 *
 * Layout (48 bytes, 6 i64 fields for GC compatibility):
 *   [0] buffer_ptr    - Pointer to ChannelBuffer (stored as i64)
 *   [1] head          - Cached read position for fast access
 *   [2] tail          - Cached write position for fast access
 *   [3] count         - Cached item count for fast access
 *   [4] waiters_ptr   - Pointer to ChannelWaitQueue (traced by GC)
 *   [5] elem_size     - Size of each element (currently always 8 for i64)
 */
typedef struct {
    int64_t buffer_ptr;                 /* Pointer stored as i64 */
    int64_t head;                       /* Cached head position */
    int64_t tail;                       /* Cached tail position */
    int64_t count;                      /* Cached item count */
    int64_t waiters_ptr;                /* Wait queue pointer as i64 */
    int64_t elem_size;                  /* Element size (8 for all types via handles) */
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
 * Send a value to the channel.
 * Never blocks - unbounded buffer grows as needed.
 * If receivers are waiting, wakes exactly one.
 *
 * @param channel    Channel to send to
 * @param value      Value to send (as i64)
 */
void coex_channel_send(TaskChannel* channel, int64_t value);

/**
 * Try to receive a value from the channel.
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
 *
 * @param channel    Channel to receive from
 * @return           Received value
 */
int64_t coex_channel_receive(TaskChannel* channel);

/**
 * Add a task to the wait queue.
 * Called by scheduler when task suspends on receive.
 *
 * @param channel    Channel with wait queue
 * @param task       Task to add
 */
void coex_channel_add_waiter(TaskChannel* channel, struct SchedulerTask* task);

/**
 * Try to wake a waiting receiver.
 * Called after send adds value to buffer.
 *
 * @param channel    Channel with wait queue
 * @return           Woken task, or NULL if no waiters
 */
struct SchedulerTask* coex_channel_wake_waiter(TaskChannel* channel);

/**
 * Get buffer count (for checking if data available).
 *
 * @param channel    Channel to check
 * @return           Number of items in buffer
 */
int64_t coex_channel_buffer_count(TaskChannel* channel);

/* ============================================================================
 * Buffer Operations (internal)
 * ============================================================================ */

/**
 * Initialize channel buffer with given capacity.
 */
ChannelBuffer* channel_buffer_new(int64_t initial_capacity);

/**
 * Push value to buffer, growing if needed.
 */
void channel_buffer_push(ChannelBuffer* buffer, int64_t value);

/**
 * Pop value from buffer (assumes count > 0).
 */
int64_t channel_buffer_pop(ChannelBuffer* buffer);

/**
 * Grow buffer to double capacity.
 */
void channel_buffer_grow(ChannelBuffer* buffer);

/* ============================================================================
 * Wait Queue Operations (internal)
 * ============================================================================ */

/**
 * Initialize wait queue.
 */
ChannelWaitQueue* channel_waitqueue_new(void);

/**
 * Add task to wait queue.
 */
void channel_waitqueue_push(ChannelWaitQueue* queue, struct SchedulerTask* task);

/**
 * Remove and return first task from queue.
 */
struct SchedulerTask* channel_waitqueue_pop(ChannelWaitQueue* queue);

#endif /* COEX_CHANNEL_H */
