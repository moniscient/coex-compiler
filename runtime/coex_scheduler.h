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

/* Completion type constants */
#define COMPLETION_NORMAL 0
#define COMPLETION_FIRST  1
#define COMPLETION_MOST   2

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

    /* For first/most completion */
    void* completion_context;         /* FirstContext* or MostContext* */
    int completion_type;              /* COMPLETION_NORMAL, COMPLETION_FIRST, COMPLETION_MOST */
    int64_t completion_index;         /* Index for first tasks */
} SchedulerTask;

/* Chase-Lev work-stealing deque */
typedef struct {
    atomic_int_fast64_t top;          /* Steal from here (thieves) */
    atomic_int_fast64_t bottom;       /* Push/pop here (owner) */
    atomic_uintptr_t buffer;          /* Pointer to circular buffer */
    int64_t capacity;                 /* Current capacity */
    pthread_mutex_t resize_lock;      /* Lock for buffer resize */
} Deque;

/**
 * Context for 'first' structured concurrency.
 * Tracks multiple spawned tasks, returns first result.
 */
typedef struct FirstContext {
    pthread_mutex_t mutex;        /* Protects result fields */
    pthread_cond_t cond;          /* Signal main when done */
    atomic_bool has_winner;       /* True when first task completes */
    int64_t winner_value;         /* Result from winning task */
    int64_t task_count;           /* Number of spawned tasks */
    atomic_int_fast64_t completed; /* Number of tasks done/cancelled */
    SchedulerTask** tasks;        /* Array of task pointers for cancellation */
} FirstContext;

/**
 * Context for 'most' structured concurrency.
 * Collects all results from spawned tasks.
 */
typedef struct MostContext {
    pthread_mutex_t mutex;        /* Protects result arrays */
    pthread_cond_t cond;          /* Signal main when all done */
    int64_t task_count;           /* Number of spawned tasks */
    atomic_int_fast64_t remaining; /* Tasks still running */
    int64_t* results;             /* Array of results */
    int64_t result_count;         /* Number of collected results */
    int64_t capacity;             /* Capacity of results array */
} MostContext;

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
 * Batch Task Spawning (for first/most)
 * ============================================================================ */

/**
 * Create a FirstContext for batch spawning with first-wins semantics.
 *
 * @param count    Number of tasks to spawn
 * @return         Initialized FirstContext
 */
FirstContext* coex_scheduler_first_context_create(int64_t count);

/**
 * Destroy a FirstContext and free resources.
 */
void coex_scheduler_first_context_destroy(FirstContext* ctx);

/**
 * Add a task to a FirstContext and start it.
 *
 * @param ctx       The FirstContext
 * @param index     Task index (0 to count-1)
 * @param frame     Task frame
 * @param step_fn   Task step function
 */
void coex_scheduler_first_spawn_task(FirstContext* ctx, int64_t index,
                                      void* frame, StepFunction step_fn);

/**
 * Wait for first task to complete in FirstContext.
 *
 * @param ctx       The FirstContext
 * @return          Result from first completing task
 */
int64_t coex_scheduler_first_wait(FirstContext* ctx);

/**
 * Create a MostContext for batch spawning with all-results semantics.
 *
 * @param count    Number of tasks to spawn
 * @return         Initialized MostContext
 */
MostContext* coex_scheduler_most_context_create(int64_t count);

/**
 * Destroy a MostContext and free resources.
 */
void coex_scheduler_most_context_destroy(MostContext* ctx);

/**
 * Add a task to a MostContext and start it.
 *
 * @param ctx       The MostContext
 * @param frame     Task frame
 * @param step_fn   Task step function
 */
void coex_scheduler_most_spawn_task(MostContext* ctx,
                                     void* frame, StepFunction step_fn);

/**
 * Wait for all tasks to complete in MostContext.
 *
 * @param ctx           The MostContext
 * @param out_results   Pointer to receive results array
 * @param out_count     Pointer to receive result count
 */
void coex_scheduler_most_wait(MostContext* ctx,
                               int64_t** out_results, int64_t* out_count);

/* ============================================================================
 * Debug/Stats
 * ============================================================================ */

/**
 * Dump scheduler statistics.
 */
void coex_scheduler_dump_stats(void);

#endif /* COEX_SCHEDULER_H */
