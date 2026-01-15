/**
 * Coex Work-Stealing Scheduler
 *
 * Implements a work-stealing scheduler for Coex task coroutines.
 * Uses Chase-Lev deques for efficient work stealing between worker threads.
 *
 * Key concepts:
 * - Tasks are stackless coroutines represented as frames + step functions
 * - Workers execute task steps and handle spawning/completion
 * - Main thread waits on a condition variable for task results
 * - Lazy initialization: workers created on first task spawn
 */

#ifndef COEX_SCHEDULER_H
#define COEX_SCHEDULER_H

#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>

/* Maximum number of workers (2x typical core count) */
#define SCHEDULER_MAX_WORKERS 128

/* Initial deque capacity (power of 2) */
#define DEQUE_INITIAL_CAPACITY 256

/* Task result kinds */
typedef enum {
    TASK_RESULT_DONE = 0,     /* Task completed with result */
    TASK_RESULT_SPAWN = 1,    /* Spawn subtask and suspend */
} TaskResultKind;

/* Result from a task step function */
typedef struct {
    TaskResultKind kind;
    union {
        int64_t value;        /* TASK_RESULT_DONE: return value */
        struct {
            void* frame;      /* TASK_RESULT_SPAWN: child frame */
            void* step_fn;    /* TASK_RESULT_SPAWN: child step function */
        } spawn;
    };
} TaskResult;

/* Step function signature: takes frame, returns TaskResult */
typedef TaskResult (*StepFunction)(void* frame, int64_t resolved_value);

/* Suspended task waiting in scheduler */
typedef struct SchedulerTask {
    void* frame;                      /* Task frame (heap-allocated) */
    StepFunction step_fn;             /* Step function pointer */
    struct SchedulerTask* waiter;     /* Parent task to wake on completion */
    int64_t resolved_value;           /* Value from completed subtask */
    atomic_bool cancelled;            /* Cancellation flag */

    /* For main thread waiting */
    pthread_mutex_t* main_mutex;      /* Non-null if main is waiting */
    pthread_cond_t* main_cond;
    int64_t* main_result;             /* Where to store result for main */
    atomic_bool* main_done;           /* Signal main thread */
} SchedulerTask;

/* Chase-Lev work-stealing deque */
typedef struct {
    atomic_int_fast64_t top;          /* Steal from here (thieves) */
    atomic_int_fast64_t bottom;       /* Push/pop here (owner) */
    atomic_uintptr_t buffer;          /* Pointer to circular buffer */
    int64_t capacity;                 /* Current capacity */
    pthread_mutex_t resize_lock;      /* Lock for buffer resize */
} Deque;

/* ============================================================================
 * Scheduler Lifecycle
 * ============================================================================ */

/**
 * Ensure scheduler is initialized (lazy initialization).
 * Thread-safe; can be called multiple times.
 * Creates worker threads on first call.
 */
void coex_scheduler_ensure_init(void);

/**
 * Check if scheduler has been initialized.
 */
bool coex_scheduler_is_initialized(void);

/**
 * Get number of worker threads.
 */
int coex_scheduler_get_worker_count(void);

/**
 * Shutdown scheduler (called at process exit).
 */
void coex_scheduler_shutdown(void);

/* ============================================================================
 * Task Spawning
 * ============================================================================ */

/**
 * Spawn a new task from main/func context and wait for result.
 * This is the entry point for func -> task calls.
 *
 * @param frame      Initial task frame (heap-allocated)
 * @param step_fn    Task step function
 * @return           Task return value
 */
int64_t coex_scheduler_spawn_and_wait(void* frame, StepFunction step_fn);

/**
 * Spawn a child task from within a task (for internal use by step functions).
 * Returns a SchedulerTask pointer that will be scheduled.
 *
 * @param frame      Child task frame
 * @param step_fn    Child step function
 * @param parent     Parent task to wake on completion
 * @return           New scheduler task (added to ready queue)
 */
SchedulerTask* coex_scheduler_spawn_child(void* frame, StepFunction step_fn,
                                           SchedulerTask* parent);

/**
 * Add a task to the ready queue for execution.
 * Used by channels to wake waiting tasks.
 *
 * @param task       Task to add to ready queue
 */
void coex_scheduler_ready_task(SchedulerTask* task);

/* ============================================================================
 * Worker Operations (internal)
 * ============================================================================ */

/**
 * Worker thread main loop.
 */
void* coex_scheduler_worker_loop(void* arg);

/**
 * Execute a single task step.
 */
void coex_scheduler_run_task(SchedulerTask* task, int worker_id);

/* ============================================================================
 * Deque Operations (Chase-Lev)
 * ============================================================================ */

/**
 * Initialize a deque.
 */
void deque_init(Deque* dq);

/**
 * Destroy a deque.
 */
void deque_destroy(Deque* dq);

/**
 * Push task to bottom (owner only).
 */
void deque_push_bottom(Deque* dq, SchedulerTask* task);

/**
 * Pop task from bottom (owner only).
 * Returns NULL if empty.
 */
SchedulerTask* deque_pop_bottom(Deque* dq);

/**
 * Steal task from top (thieves).
 * Returns NULL if empty or contention.
 */
SchedulerTask* deque_steal(Deque* dq);

/* ============================================================================
 * Debug/Stats
 * ============================================================================ */

/**
 * Dump scheduler statistics.
 */
void coex_scheduler_dump_stats(void);

#endif /* COEX_SCHEDULER_H */
