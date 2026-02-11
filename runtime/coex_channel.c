/**
 * Coex TaskChannel Implementation
 *
 * Lock-free MPSC (Vyukov) queue for values, lock-free Treiber stack for
 * task waiters. Mutex retained only for blocking receive (condvar API).
 *
 * See coex_channel.h for documentation.
 */

#include "coex_channel.h"
#include "coex_scheduler.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ============================================================================
 * MPSC Queue Operations (Vyukov pattern)
 *
 * Lock-free, FIFO, multi-producer single-consumer.
 * - Push: atomic_exchange on tail, then link prev->next (single CAS per push)
 * - Pop: read head->next; if non-NULL, advance head and return value
 *
 * Inconsistent state window: between exchange(tail) and prev->next store,
 * the consumer may see head->next == NULL (false empty). For blocking
 * receive, the condvar while-loop retries. For try_receive, returning
 * false-empty is acceptable (caller retries or suspends).
 * ============================================================================ */

static void mpsc_init(TaskChannel* ch) {
    ch->stub.value = 0;
    atomic_store_explicit(&ch->stub.next, NULL, memory_order_relaxed);
    atomic_store_explicit(&ch->mpsc_head, &ch->stub, memory_order_relaxed);
    atomic_store_explicit(&ch->mpsc_tail, &ch->stub, memory_order_relaxed);
}

static void mpsc_push(TaskChannel* ch, ChannelNode* node) {
    atomic_store_explicit(&node->next, NULL, memory_order_relaxed);
    ChannelNode* prev = atomic_exchange_explicit(&ch->mpsc_tail, node, memory_order_acq_rel);
    /* Linearization point: prev->next = node makes value visible to consumer */
    atomic_store_explicit(&prev->next, node, memory_order_release);
}

static ChannelNode* mpsc_try_pop(TaskChannel* ch) {
    ChannelNode* head = atomic_load_explicit(&ch->mpsc_head, memory_order_acquire);
    ChannelNode* next = atomic_load_explicit(&head->next, memory_order_acquire);
    if (next == NULL) {
        return NULL;  /* Empty (or inconsistent state — producer hasn't linked yet) */
    }
    /* Advance head past the sentinel to the real node */
    atomic_store_explicit(&ch->mpsc_head, next, memory_order_release);
    /* The old head becomes garbage (it was the previous sentinel).
     * If it's the original stub, don't free it (it's embedded in the channel).
     * Otherwise, free the retired sentinel. */
    if (head != &ch->stub) {
        free(head);
    }
    return next;
}

/* ============================================================================
 * Waiter Stack Operations (lock-free Treiber stack)
 * ============================================================================ */

static void waiter_push(TaskChannel* ch, ChannelWaiterNode* node) {
    ChannelWaiterNode* old_head = atomic_load_explicit(&ch->waiter_head, memory_order_relaxed);
    do {
        atomic_store_explicit(&node->next, old_head, memory_order_relaxed);
    } while (!atomic_compare_exchange_weak_explicit(
        &ch->waiter_head, &old_head, node,
        memory_order_release, memory_order_relaxed));
}

static ChannelWaiterNode* waiter_pop(TaskChannel* ch) {
    ChannelWaiterNode* old_head = atomic_load_explicit(&ch->waiter_head, memory_order_acquire);
    while (old_head != NULL) {
        ChannelWaiterNode* next = atomic_load_explicit(&old_head->next, memory_order_relaxed);
        if (atomic_compare_exchange_weak_explicit(
                &ch->waiter_head, &old_head, next,
                memory_order_acquire, memory_order_relaxed)) {
            return old_head;
        }
    }
    return NULL;
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
    memset(channel, 0, sizeof(TaskChannel));

    channel->elem_size = elem_size;

    /* Initialize MPSC queue */
    mpsc_init(channel);

    /* Initialize waiter stack */
    atomic_store_explicit(&channel->waiter_head, NULL, memory_order_relaxed);

    /* Initialize blocking receive support */
    atomic_store_explicit(&channel->blocking_count, 0, memory_order_relaxed);
    pthread_mutex_init(&channel->block_mutex, NULL);
    pthread_cond_init(&channel->block_cond, NULL);

    return channel;
}

void coex_channel_send(TaskChannel* channel, int64_t value) {
    /* Allocate node and push to MPSC queue (lock-free) */
    ChannelNode* node = (ChannelNode*)malloc(sizeof(ChannelNode));
    if (!node) {
        fprintf(stderr, "FATAL: Failed to allocate channel node\n");
        abort();
    }
    node->value = value;
    mpsc_push(channel, node);

    /* Try to wake a task waiter (lock-free Treiber stack pop) */
    ChannelWaiterNode* waiter = waiter_pop(channel);
    if (waiter) {
        struct SchedulerTask* task = waiter->task;
        free(waiter);
        /* Re-derive value for the woken task: it will call try_receive itself
         * after being re-scheduled. Store a sentinel so it knows to retry. */
        coex_scheduler_ready_task(task);
        return;
    }

    /* No task waiters — check if any blocking threads are waiting */
    if (atomic_load_explicit(&channel->blocking_count, memory_order_acquire) > 0) {
        pthread_mutex_lock(&channel->block_mutex);
        pthread_cond_signal(&channel->block_cond);
        pthread_mutex_unlock(&channel->block_mutex);
    }
}

int64_t coex_channel_try_receive(TaskChannel* channel, int64_t* out_value) {
    /* Lock-free pop from MPSC queue */
    ChannelNode* node = mpsc_try_pop(channel);
    if (node) {
        *out_value = node->value;
        /* node is now the new head sentinel — do not free it.
         * mpsc_try_pop sets head = next and frees old head.
         * The returned node's value field has the data we want. */
        return 0;  /* Success */
    }
    return -1;  /* Empty — caller should suspend */
}

int64_t coex_channel_receive(TaskChannel* channel) {
    /* Fast path: lock-free try */
    int64_t value;
    if (coex_channel_try_receive(channel, &value) == 0) {
        return value;
    }

    /* Slow path: block on condvar */
    pthread_mutex_lock(&channel->block_mutex);
    atomic_fetch_add_explicit(&channel->blocking_count, 1, memory_order_release);

    while (coex_channel_try_receive(channel, &value) != 0) {
        pthread_cond_wait(&channel->block_cond, &channel->block_mutex);
    }

    atomic_fetch_sub_explicit(&channel->blocking_count, 1, memory_order_release);
    pthread_mutex_unlock(&channel->block_mutex);

    return value;
}

void coex_channel_add_waiter(TaskChannel* channel, SchedulerTask* task) {
    /* Lock-free Treiber stack push */
    ChannelWaiterNode* node = (ChannelWaiterNode*)malloc(sizeof(ChannelWaiterNode));
    if (!node) {
        fprintf(stderr, "FATAL: Failed to allocate waiter node\n");
        abort();
    }
    node->task = task;
    waiter_push(channel, node);
}

SchedulerTask* coex_channel_wake_waiter(TaskChannel* channel) {
    /* Lock-free Treiber stack pop */
    ChannelWaiterNode* node = waiter_pop(channel);
    if (node) {
        SchedulerTask* task = node->task;
        free(node);
        return task;
    }
    return NULL;
}

int64_t coex_channel_buffer_count(TaskChannel* channel) {
    /* Approximate: check if MPSC queue has any data */
    ChannelNode* head = atomic_load_explicit(&channel->mpsc_head, memory_order_acquire);
    ChannelNode* next = atomic_load_explicit(&head->next, memory_order_acquire);
    return (next != NULL) ? 1 : 0;  /* Approximate — only indicates non-empty */
}
