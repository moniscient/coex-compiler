/**
 * Coex TaskChannel Implementation
 *
 * See coex_channel.h for documentation.
 */

#include "coex_channel.h"
#include "coex_scheduler.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* Initial buffer capacity (must be power of 2) */
#define INITIAL_BUFFER_CAPACITY 16

/* ============================================================================
 * Buffer Operations
 * ============================================================================ */

ChannelBuffer* channel_buffer_new(int64_t initial_capacity) {
    ChannelBuffer* buffer = (ChannelBuffer*)malloc(sizeof(ChannelBuffer));
    if (!buffer) return NULL;

    buffer->data = (int64_t*)malloc(initial_capacity * sizeof(int64_t));
    if (!buffer->data) {
        free(buffer);
        return NULL;
    }

    buffer->capacity = initial_capacity;
    buffer->head = 0;
    buffer->tail = 0;
    buffer->count = 0;

    return buffer;
}

void channel_buffer_push(ChannelBuffer* buffer, int64_t value) {
    /* Grow if full */
    if (buffer->count == buffer->capacity) {
        channel_buffer_grow(buffer);
    }

    /* Add at tail */
    buffer->data[buffer->tail] = value;
    buffer->tail = (buffer->tail + 1) % buffer->capacity;
    buffer->count++;
}

int64_t channel_buffer_pop(ChannelBuffer* buffer) {
    /* Assumes count > 0 */
    int64_t value = buffer->data[buffer->head];
    buffer->head = (buffer->head + 1) % buffer->capacity;
    buffer->count--;
    return value;
}

void channel_buffer_grow(ChannelBuffer* buffer) {
    int64_t new_capacity = buffer->capacity * 2;
    int64_t* new_data = (int64_t*)malloc(new_capacity * sizeof(int64_t));
    if (!new_data) {
        fprintf(stderr, "FATAL: Failed to grow channel buffer\n");
        abort();
    }

    /* Copy data to contiguous region starting at index 0 */
    for (int64_t i = 0; i < buffer->count; i++) {
        int64_t old_idx = (buffer->head + i) % buffer->capacity;
        new_data[i] = buffer->data[old_idx];
    }

    free(buffer->data);
    buffer->data = new_data;
    buffer->capacity = new_capacity;
    buffer->head = 0;
    buffer->tail = buffer->count;
}

/* ============================================================================
 * Wait Queue Operations
 * ============================================================================ */

ChannelWaitQueue* channel_waitqueue_new(void) {
    ChannelWaitQueue* queue = (ChannelWaitQueue*)malloc(sizeof(ChannelWaitQueue));
    if (!queue) return NULL;

    queue->head = NULL;
    queue->tail = NULL;
    queue->count = 0;

    return queue;
}

void channel_waitqueue_push(ChannelWaitQueue* queue, SchedulerTask* task) {
    ChannelWaitNode* node = (ChannelWaitNode*)malloc(sizeof(ChannelWaitNode));
    if (!node) {
        fprintf(stderr, "FATAL: Failed to allocate wait node\n");
        abort();
    }

    node->task = task;
    node->next = NULL;

    if (queue->tail == NULL) {
        queue->head = node;
        queue->tail = node;
    } else {
        queue->tail->next = node;
        queue->tail = node;
    }

    queue->count++;
}

SchedulerTask* channel_waitqueue_pop(ChannelWaitQueue* queue) {
    if (queue->head == NULL) {
        return NULL;
    }

    ChannelWaitNode* node = queue->head;
    SchedulerTask* task = node->task;

    queue->head = node->next;
    if (queue->head == NULL) {
        queue->tail = NULL;
    }

    queue->count--;
    free(node);

    return task;
}

/* ============================================================================
 * Channel Operations
 * ============================================================================ */

TaskChannel* coex_channel_new(int64_t elem_size) {
    TaskChannel* channel = (TaskChannel*)malloc(sizeof(TaskChannel));
    if (!channel) {
        fprintf(stderr, "FATAL: Failed to allocate channel\n");
        abort();
    }

    /* Initialize buffer */
    ChannelBuffer* buffer = channel_buffer_new(INITIAL_BUFFER_CAPACITY);
    if (!buffer) {
        free(channel);
        fprintf(stderr, "FATAL: Failed to allocate channel buffer\n");
        abort();
    }

    /* Initialize wait queue */
    ChannelWaitQueue* waiters = channel_waitqueue_new();
    if (!waiters) {
        free(buffer->data);
        free(buffer);
        free(channel);
        fprintf(stderr, "FATAL: Failed to allocate wait queue\n");
        abort();
    }

    /* Store pointers as i64 for GC compatibility */
    channel->buffer_ptr = (int64_t)(intptr_t)buffer;
    channel->head = 0;
    channel->tail = 0;
    channel->count = 0;
    channel->waiters_ptr = (int64_t)(intptr_t)waiters;
    channel->elem_size = elem_size;

    return channel;
}

void coex_channel_send(TaskChannel* channel, int64_t value) {
    ChannelBuffer* buffer = (ChannelBuffer*)(intptr_t)channel->buffer_ptr;
    ChannelWaitQueue* waiters = (ChannelWaitQueue*)(intptr_t)channel->waiters_ptr;

    /* Check if any receivers are waiting */
    if (waiters->count > 0) {
        /* Direct handoff - wake receiver with value */
        SchedulerTask* task = channel_waitqueue_pop(waiters);
        if (task) {
            /* Store value in task's resolved field */
            task->resolved_value = value;

            /* Add task back to ready queue */
            /* Note: This requires scheduler integration */
            coex_scheduler_ready_task(task);
            return;
        }
    }

    /* No waiters - buffer the value */
    channel_buffer_push(buffer, value);

    /* Update cached counts */
    channel->count = buffer->count;
    channel->head = buffer->head;
    channel->tail = buffer->tail;
}

int64_t coex_channel_try_receive(TaskChannel* channel, int64_t* out_value) {
    ChannelBuffer* buffer = (ChannelBuffer*)(intptr_t)channel->buffer_ptr;

    if (buffer->count > 0) {
        /* Data available - return immediately */
        *out_value = channel_buffer_pop(buffer);

        /* Update cached counts */
        channel->count = buffer->count;
        channel->head = buffer->head;
        channel->tail = buffer->tail;

        return 0;  /* Success */
    }

    /* No data - caller should suspend */
    return -1;  /* Should suspend */
}

int64_t coex_channel_receive(TaskChannel* channel) {
    ChannelBuffer* buffer = (ChannelBuffer*)(intptr_t)channel->buffer_ptr;

    /* Spin wait for data (only for func/thread context, not recommended) */
    while (buffer->count == 0) {
        /* Busy wait - in production, should use condition variable */
        /* This path is for non-task callers only */
    }

    int64_t value = channel_buffer_pop(buffer);

    /* Update cached counts */
    channel->count = buffer->count;
    channel->head = buffer->head;
    channel->tail = buffer->tail;

    return value;
}

void coex_channel_add_waiter(TaskChannel* channel, SchedulerTask* task) {
    ChannelWaitQueue* waiters = (ChannelWaitQueue*)(intptr_t)channel->waiters_ptr;
    channel_waitqueue_push(waiters, task);
}

SchedulerTask* coex_channel_wake_waiter(TaskChannel* channel) {
    ChannelWaitQueue* waiters = (ChannelWaitQueue*)(intptr_t)channel->waiters_ptr;
    return channel_waitqueue_pop(waiters);
}

int64_t coex_channel_buffer_count(TaskChannel* channel) {
    ChannelBuffer* buffer = (ChannelBuffer*)(intptr_t)channel->buffer_ptr;
    return buffer->count;
}
