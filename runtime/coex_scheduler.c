/**
 * Coex Work-Stealing Scheduler Implementation
 *
 * Implements Chase-Lev work-stealing deques and a fixed-size worker pool.
 */

#include "coex_scheduler.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <sys/time.h>

/* External GC functions (defined in coex_gc runtime) */
extern void coex_gc_register_thread(void);
extern void coex_gc_unregister_thread(void);

/* ============================================================================
 * Global Scheduler State
 * ============================================================================ */

static atomic_bool scheduler_initialized = false;
static atomic_bool scheduler_shutdown_flag = false;
static pthread_mutex_t scheduler_init_mutex = PTHREAD_MUTEX_INITIALIZER;

static int worker_count = 0;
static pthread_t workers[SCHEDULER_MAX_WORKERS];
static Deque worker_deques[SCHEDULER_MAX_WORKERS];

/* Parking: workers sleep here when no work */
static pthread_mutex_t parking_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t parking_cond = PTHREAD_COND_INITIALIZER;
static atomic_int parked_workers = 0;

/* Global queue for tasks from main thread */
static Deque global_queue;
static pthread_mutex_t global_queue_mutex = PTHREAD_MUTEX_INITIALIZER;

/* Statistics */
static atomic_uint_fast64_t tasks_executed = 0;
static atomic_uint_fast64_t tasks_stolen = 0;

/* ============================================================================
 * Chase-Lev Deque Implementation
 * ============================================================================ */

/* Circular buffer for deque */
typedef struct {
    int64_t capacity;
    SchedulerTask* tasks[];  /* Flexible array member */
} DequeBuffer;

static DequeBuffer* deque_buffer_alloc(int64_t capacity) {
    DequeBuffer* buf = malloc(sizeof(DequeBuffer) + capacity * sizeof(SchedulerTask*));
    if (buf) {
        buf->capacity = capacity;
        memset(buf->tasks, 0, capacity * sizeof(SchedulerTask*));
    }
    return buf;
}

void deque_init(Deque* dq) {
    atomic_store(&dq->top, 0);
    atomic_store(&dq->bottom, 0);
    DequeBuffer* buf = deque_buffer_alloc(DEQUE_INITIAL_CAPACITY);
    atomic_store(&dq->buffer, (uintptr_t)buf);
    dq->capacity = DEQUE_INITIAL_CAPACITY;
    pthread_mutex_init(&dq->resize_lock, NULL);
}

void deque_destroy(Deque* dq) {
    DequeBuffer* buf = (DequeBuffer*)atomic_load(&dq->buffer);
    if (buf) free(buf);
    pthread_mutex_destroy(&dq->resize_lock);
}

/* Grow the deque buffer (called under resize_lock) */
static void deque_grow(Deque* dq) {
    DequeBuffer* old_buf = (DequeBuffer*)atomic_load(&dq->buffer);
    int64_t old_cap = old_buf->capacity;
    int64_t new_cap = old_cap * 2;

    DequeBuffer* new_buf = deque_buffer_alloc(new_cap);

    /* Copy existing elements */
    int64_t t = atomic_load_explicit(&dq->top, memory_order_relaxed);
    int64_t b = atomic_load_explicit(&dq->bottom, memory_order_relaxed);
    for (int64_t i = t; i < b; i++) {
        new_buf->tasks[i % new_cap] = old_buf->tasks[i % old_cap];
    }

    atomic_store(&dq->buffer, (uintptr_t)new_buf);
    dq->capacity = new_cap;

    /* Old buffer will be freed eventually (could use epoch-based reclamation) */
    /* For simplicity, we leak it here - in practice use hazard pointers */
}

void deque_push_bottom(Deque* dq, SchedulerTask* task) {
    int64_t b = atomic_load_explicit(&dq->bottom, memory_order_relaxed);
    int64_t t = atomic_load_explicit(&dq->top, memory_order_acquire);
    DequeBuffer* buf = (DequeBuffer*)atomic_load_explicit(&dq->buffer, memory_order_relaxed);

    /* Check if we need to grow */
    if (b - t >= buf->capacity - 1) {
        pthread_mutex_lock(&dq->resize_lock);
        deque_grow(dq);
        buf = (DequeBuffer*)atomic_load(&dq->buffer);
        pthread_mutex_unlock(&dq->resize_lock);
    }

    buf->tasks[b % buf->capacity] = task;
    atomic_thread_fence(memory_order_release);
    atomic_store_explicit(&dq->bottom, b + 1, memory_order_relaxed);
}

SchedulerTask* deque_pop_bottom(Deque* dq) {
    int64_t b = atomic_load_explicit(&dq->bottom, memory_order_relaxed) - 1;
    DequeBuffer* buf = (DequeBuffer*)atomic_load_explicit(&dq->buffer, memory_order_relaxed);
    atomic_store_explicit(&dq->bottom, b, memory_order_relaxed);
    atomic_thread_fence(memory_order_seq_cst);

    int64_t t = atomic_load_explicit(&dq->top, memory_order_relaxed);

    if (t <= b) {
        /* Non-empty */
        SchedulerTask* task = buf->tasks[b % buf->capacity];
        if (t == b) {
            /* Last element - compete with stealers */
            if (!atomic_compare_exchange_strong_explicit(
                    &dq->top, &t, t + 1,
                    memory_order_seq_cst, memory_order_relaxed)) {
                /* Lost race with stealer */
                task = NULL;
            }
            atomic_store_explicit(&dq->bottom, b + 1, memory_order_relaxed);
        }
        return task;
    } else {
        /* Empty */
        atomic_store_explicit(&dq->bottom, b + 1, memory_order_relaxed);
        return NULL;
    }
}

SchedulerTask* deque_steal(Deque* dq) {
    int64_t t = atomic_load_explicit(&dq->top, memory_order_acquire);
    atomic_thread_fence(memory_order_seq_cst);
    int64_t b = atomic_load_explicit(&dq->bottom, memory_order_acquire);

    if (t < b) {
        /* Non-empty */
        DequeBuffer* buf = (DequeBuffer*)atomic_load_explicit(&dq->buffer, memory_order_relaxed);
        SchedulerTask* task = buf->tasks[t % buf->capacity];

        if (!atomic_compare_exchange_strong_explicit(
                &dq->top, &t, t + 1,
                memory_order_seq_cst, memory_order_relaxed)) {
            /* Lost race */
            return NULL;
        }
        return task;
    }
    return NULL;
}

/* ============================================================================
 * Worker Thread Pool
 * ============================================================================ */

static void wake_one_worker(void) {
    pthread_mutex_lock(&parking_mutex);
    pthread_cond_signal(&parking_cond);
    pthread_mutex_unlock(&parking_mutex);
}

static void wake_all_workers(void) {
    pthread_mutex_lock(&parking_mutex);
    pthread_cond_broadcast(&parking_cond);
    pthread_mutex_unlock(&parking_mutex);
}

static void park_worker(int worker_id) {
    (void)worker_id;  /* Unused parameter */
    pthread_mutex_lock(&parking_mutex);
    atomic_fetch_add(&parked_workers, 1);

    /* Wait with timeout to allow periodic stealing attempts */
    struct timespec ts;
    struct timeval tv;
    gettimeofday(&tv, NULL);
    ts.tv_sec = tv.tv_sec;
    ts.tv_nsec = tv.tv_usec * 1000 + 1000000;  /* Add 1ms timeout */
    if (ts.tv_nsec >= 1000000000) {
        ts.tv_sec += 1;
        ts.tv_nsec -= 1000000000;
    }

    pthread_cond_timedwait(&parking_cond, &parking_mutex, &ts);
    atomic_fetch_sub(&parked_workers, 1);
    pthread_mutex_unlock(&parking_mutex);
}

/* Try to steal from other workers */
static SchedulerTask* try_steal(int worker_id) {
    /* Try global queue first */
    pthread_mutex_lock(&global_queue_mutex);
    SchedulerTask* task = deque_steal(&global_queue);
    pthread_mutex_unlock(&global_queue_mutex);
    if (task) {
        atomic_fetch_add(&tasks_stolen, 1);
        return task;
    }

    /* Try other workers */
    for (int i = 0; i < worker_count; i++) {
        if (i != worker_id) {
            task = deque_steal(&worker_deques[i]);
            if (task) {
                atomic_fetch_add(&tasks_stolen, 1);
                return task;
            }
        }
    }
    return NULL;
}

void* coex_scheduler_worker_loop(void* arg) {
    int worker_id = (int)(intptr_t)arg;

    /* Register with GC */
    coex_gc_register_thread();

    while (!atomic_load(&scheduler_shutdown_flag)) {
        SchedulerTask* task = NULL;

        /* Try own deque first (LIFO for locality) */
        task = deque_pop_bottom(&worker_deques[worker_id]);

        /* If empty, try stealing */
        if (!task) {
            task = try_steal(worker_id);
        }

        /* If still no work, park */
        if (!task) {
            park_worker(worker_id);
            continue;
        }

        /* Execute the task */
        coex_scheduler_run_task(task, worker_id);
    }

    coex_gc_unregister_thread();
    return NULL;
}

/* ============================================================================
 * Task Execution
 * ============================================================================ */

/* Forward declaration of first/most completion handlers */
static void handle_first_completion(SchedulerTask* task, int64_t value);
static void handle_most_completion(SchedulerTask* task, int64_t value);

void coex_scheduler_run_task(SchedulerTask* task, int worker_id) {
    /* Check cancellation */
    if (atomic_load(&task->cancelled)) {
        /* For first/most, still need to track completion */
        if (task->completion_type == COMPLETION_FIRST) {
            /* First task - cancelled, track completion but don't store result */
            FirstContext* ctx = (FirstContext*)task->completion_context;
            atomic_fetch_add(&ctx->completed, 1);
        } else if (task->completion_type == COMPLETION_MOST) {
            /* Most task - cancelled, track completion */
            MostContext* ctx = (MostContext*)task->completion_context;
            int64_t remaining = atomic_fetch_sub(&ctx->remaining, 1) - 1;
            if (remaining == 0) {
                pthread_mutex_lock(&ctx->mutex);
                pthread_cond_signal(&ctx->cond);
                pthread_mutex_unlock(&ctx->mutex);
            }
        }
        free(task);
        return;
    }

    /* Call step function */
    TaskResult result = task->step_fn(task->frame, task->resolved_value);
    atomic_fetch_add(&tasks_executed, 1);

    /* Check cancellation again */
    if (atomic_load(&task->cancelled)) {
        /* For first/most, still need to track completion */
        if (task->completion_type == COMPLETION_FIRST) {
            FirstContext* ctx = (FirstContext*)task->completion_context;
            atomic_fetch_add(&ctx->completed, 1);
        } else if (task->completion_type == COMPLETION_MOST) {
            MostContext* ctx = (MostContext*)task->completion_context;
            int64_t remaining = atomic_fetch_sub(&ctx->remaining, 1) - 1;
            if (remaining == 0) {
                pthread_mutex_lock(&ctx->mutex);
                pthread_cond_signal(&ctx->cond);
                pthread_mutex_unlock(&ctx->mutex);
            }
        }
        free(task);
        return;
    }

    switch (result.kind) {
        case TASK_RESULT_DONE: {
            /* Task completed - check for first/most handlers */
            if (task->completion_type == COMPLETION_FIRST) {
                handle_first_completion(task, result.value);
            } else if (task->completion_type == COMPLETION_MOST) {
                handle_most_completion(task, result.value);
            } else if (task->main_mutex) {
                /* Waiting main thread */
                pthread_mutex_lock(task->main_mutex);
                *task->main_result = result.value;
                atomic_store(task->main_done, true);
                pthread_cond_signal(task->main_cond);
                pthread_mutex_unlock(task->main_mutex);
            } else if (task->waiter) {
                /* Wake parent task */
                task->waiter->resolved_value = result.value;
                deque_push_bottom(&worker_deques[worker_id], task->waiter);
                wake_one_worker();
            }
            free(task);
            break;
        }

        case TASK_RESULT_SPAWN: {
            /* Spawn child task */
            SchedulerTask* child = malloc(sizeof(SchedulerTask));
            memset(child, 0, sizeof(SchedulerTask));
            child->frame = result.spawn.frame;
            child->step_fn = (StepFunction)result.spawn.step_fn;
            child->waiter = task;  /* Child will wake this task */
            atomic_store(&child->cancelled, false);
            child->completion_type = COMPLETION_NORMAL;

            /* Push child to ready queue */
            deque_push_bottom(&worker_deques[worker_id], child);
            wake_one_worker();
            /* Parent task stays suspended (not freed) */
            break;
        }
    }
}

/* Handle completion of a first-wins task */
static void handle_first_completion(SchedulerTask* task, int64_t value) {
    FirstContext* ctx = (FirstContext*)task->completion_context;

    /* Try to claim winner slot */
    bool expected = false;
    if (atomic_compare_exchange_strong(&ctx->has_winner, &expected, true)) {
        /* We won! */
        pthread_mutex_lock(&ctx->mutex);
        ctx->winner_value = value;

        /* Cancel siblings */
        for (int64_t i = 0; i < ctx->task_count; i++) {
            if (i != task->completion_index && ctx->tasks[i]) {
                atomic_store(&ctx->tasks[i]->cancelled, true);
            }
        }

        /* Signal main thread */
        pthread_cond_signal(&ctx->cond);
        pthread_mutex_unlock(&ctx->mutex);
    }

    /* Track completion */
    atomic_fetch_add(&ctx->completed, 1);
}

/* Handle completion of a most task */
static void handle_most_completion(SchedulerTask* task, int64_t value) {
    MostContext* ctx = (MostContext*)task->completion_context;

    /* Add result to list */
    pthread_mutex_lock(&ctx->mutex);
    if (ctx->result_count < ctx->capacity) {
        ctx->results[ctx->result_count++] = value;
    }
    pthread_mutex_unlock(&ctx->mutex);

    /* Check if we're the last one */
    int64_t remaining = atomic_fetch_sub(&ctx->remaining, 1) - 1;
    if (remaining == 0) {
        /* Wake main thread */
        pthread_mutex_lock(&ctx->mutex);
        pthread_cond_signal(&ctx->cond);
        pthread_mutex_unlock(&ctx->mutex);
    }
}

/* ============================================================================
 * Scheduler Lifecycle
 * ============================================================================ */

void coex_scheduler_ensure_init(void) {
    if (atomic_load(&scheduler_initialized)) {
        return;
    }

    pthread_mutex_lock(&scheduler_init_mutex);
    if (!atomic_load(&scheduler_initialized)) {
        /* Determine worker count: 2x physical cores */
        int cores = (int)sysconf(_SC_NPROCESSORS_ONLN);
        if (cores < 1) cores = 1;
        worker_count = cores * 2;
        if (worker_count > SCHEDULER_MAX_WORKERS) {
            worker_count = SCHEDULER_MAX_WORKERS;
        }

        /* Initialize global queue */
        deque_init(&global_queue);

        /* Initialize worker deques */
        for (int i = 0; i < worker_count; i++) {
            deque_init(&worker_deques[i]);
        }

        /* Spawn worker threads */
        for (int i = 0; i < worker_count; i++) {
            int rc = pthread_create(&workers[i], NULL,
                                    coex_scheduler_worker_loop,
                                    (void*)(intptr_t)i);
            if (rc != 0) {
                fprintf(stderr, "Failed to create worker %d: %s\n", i, strerror(rc));
            }
        }

        atomic_store(&scheduler_initialized, true);
    }
    pthread_mutex_unlock(&scheduler_init_mutex);
}

bool coex_scheduler_is_initialized(void) {
    return atomic_load(&scheduler_initialized);
}

int coex_scheduler_get_worker_count(void) {
    return worker_count;
}

void coex_scheduler_shutdown(void) {
    if (!atomic_load(&scheduler_initialized)) {
        return;
    }

    /* Signal shutdown */
    atomic_store(&scheduler_shutdown_flag, true);
    wake_all_workers();

    /* Wait for workers to finish */
    for (int i = 0; i < worker_count; i++) {
        pthread_join(workers[i], NULL);
    }

    /* Cleanup deques */
    deque_destroy(&global_queue);
    for (int i = 0; i < worker_count; i++) {
        deque_destroy(&worker_deques[i]);
    }
}

/* ============================================================================
 * Task Spawning
 * ============================================================================ */

int64_t coex_scheduler_spawn_and_wait(void* frame, StepFunction step_fn) {
    /* Ensure scheduler is running */
    coex_scheduler_ensure_init();

    /* Create task */
    SchedulerTask* task = malloc(sizeof(SchedulerTask));
    memset(task, 0, sizeof(SchedulerTask));
    task->frame = frame;
    task->step_fn = step_fn;
    task->waiter = NULL;
    task->resolved_value = 0;
    atomic_store(&task->cancelled, false);

    /* Setup main thread waiting */
    pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
    pthread_cond_t cond = PTHREAD_COND_INITIALIZER;
    int64_t result = 0;
    atomic_bool done = false;

    task->main_mutex = &mutex;
    task->main_cond = &cond;
    task->main_result = &result;
    task->main_done = &done;

    /* Submit to global queue */
    pthread_mutex_lock(&global_queue_mutex);
    deque_push_bottom(&global_queue, task);
    pthread_mutex_unlock(&global_queue_mutex);

    /* Wake a worker */
    wake_one_worker();

    /* Wait for completion */
    pthread_mutex_lock(&mutex);
    while (!atomic_load(&done)) {
        pthread_cond_wait(&cond, &mutex);
    }
    pthread_mutex_unlock(&mutex);

    pthread_mutex_destroy(&mutex);
    pthread_cond_destroy(&cond);

    return result;
}

SchedulerTask* coex_scheduler_spawn_child(void* frame, StepFunction step_fn,
                                           SchedulerTask* parent) {
    SchedulerTask* task = malloc(sizeof(SchedulerTask));
    memset(task, 0, sizeof(SchedulerTask));
    task->frame = frame;
    task->step_fn = step_fn;
    task->waiter = parent;
    task->resolved_value = 0;
    atomic_store(&task->cancelled, false);
    return task;
}

void coex_scheduler_ready_task(SchedulerTask* task) {
    /* Add task to global queue and wake a worker */
    pthread_mutex_lock(&global_queue_mutex);
    deque_push_bottom(&global_queue, task);
    pthread_mutex_unlock(&global_queue_mutex);
    wake_one_worker();
}

/* ============================================================================
 * Batch Task Spawning (for first/most)
 * ============================================================================ */

FirstContext* coex_scheduler_first_context_create(int64_t count) {
    FirstContext* ctx = malloc(sizeof(FirstContext));
    if (!ctx) return NULL;

    pthread_mutex_init(&ctx->mutex, NULL);
    pthread_cond_init(&ctx->cond, NULL);
    atomic_store(&ctx->has_winner, false);
    ctx->winner_value = 0;
    ctx->task_count = count;
    atomic_store(&ctx->completed, 0);
    ctx->tasks = calloc(count, sizeof(SchedulerTask*));

    return ctx;
}

void coex_scheduler_first_context_destroy(FirstContext* ctx) {
    if (!ctx) return;
    pthread_mutex_destroy(&ctx->mutex);
    pthread_cond_destroy(&ctx->cond);
    free(ctx->tasks);
    free(ctx);
}

void coex_scheduler_first_spawn_task(FirstContext* ctx, int64_t index,
                                      void* frame, StepFunction step_fn) {
    coex_scheduler_ensure_init();

    /* Create task with first completion type */
    SchedulerTask* task = malloc(sizeof(SchedulerTask));
    memset(task, 0, sizeof(SchedulerTask));

    task->frame = frame;
    task->step_fn = step_fn;
    task->waiter = NULL;
    task->resolved_value = 0;
    atomic_store(&task->cancelled, false);
    task->completion_context = ctx;
    task->completion_type = COMPLETION_FIRST;
    task->completion_index = index;

    /* Store in context for cancellation */
    ctx->tasks[index] = task;

    /* Submit to global queue */
    pthread_mutex_lock(&global_queue_mutex);
    deque_push_bottom(&global_queue, task);
    pthread_mutex_unlock(&global_queue_mutex);

    wake_one_worker();
}

int64_t coex_scheduler_first_wait(FirstContext* ctx) {
    pthread_mutex_lock(&ctx->mutex);
    while (!atomic_load(&ctx->has_winner)) {
        pthread_cond_wait(&ctx->cond, &ctx->mutex);
    }
    int64_t result = ctx->winner_value;
    pthread_mutex_unlock(&ctx->mutex);
    return result;
}

MostContext* coex_scheduler_most_context_create(int64_t count) {
    MostContext* ctx = malloc(sizeof(MostContext));
    if (!ctx) return NULL;

    pthread_mutex_init(&ctx->mutex, NULL);
    pthread_cond_init(&ctx->cond, NULL);
    ctx->task_count = count;
    atomic_store(&ctx->remaining, count);
    ctx->results = calloc(count, sizeof(int64_t));
    ctx->result_count = 0;
    ctx->capacity = count;

    return ctx;
}

void coex_scheduler_most_context_destroy(MostContext* ctx) {
    if (!ctx) return;
    pthread_mutex_destroy(&ctx->mutex);
    pthread_cond_destroy(&ctx->cond);
    free(ctx->results);
    free(ctx);
}

void coex_scheduler_most_spawn_task(MostContext* ctx,
                                     void* frame, StepFunction step_fn) {
    coex_scheduler_ensure_init();

    /* Create task with most completion type */
    SchedulerTask* task = malloc(sizeof(SchedulerTask));
    memset(task, 0, sizeof(SchedulerTask));

    task->frame = frame;
    task->step_fn = step_fn;
    task->waiter = NULL;
    task->resolved_value = 0;
    atomic_store(&task->cancelled, false);
    task->completion_context = ctx;
    task->completion_type = COMPLETION_MOST;
    task->completion_index = 0;  /* Not used for most */

    /* Submit to global queue */
    pthread_mutex_lock(&global_queue_mutex);
    deque_push_bottom(&global_queue, task);
    pthread_mutex_unlock(&global_queue_mutex);

    wake_one_worker();
}

void coex_scheduler_most_wait(MostContext* ctx,
                               int64_t** out_results, int64_t* out_count) {
    pthread_mutex_lock(&ctx->mutex);
    while (atomic_load(&ctx->remaining) > 0) {
        pthread_cond_wait(&ctx->cond, &ctx->mutex);
    }
    *out_results = ctx->results;
    *out_count = ctx->result_count;
    pthread_mutex_unlock(&ctx->mutex);
}

/* ============================================================================
 * Debug/Stats
 * ============================================================================ */

void coex_scheduler_dump_stats(void) {
    printf("=== Scheduler Stats ===\n");
    printf("Initialized: %s\n", atomic_load(&scheduler_initialized) ? "yes" : "no");
    printf("Worker count: %d\n", worker_count);
    printf("Tasks executed: %llu\n", (unsigned long long)atomic_load(&tasks_executed));
    printf("Tasks stolen: %llu\n", (unsigned long long)atomic_load(&tasks_stolen));
    printf("Parked workers: %d\n", atomic_load(&parked_workers));
    printf("=======================\n");
}
