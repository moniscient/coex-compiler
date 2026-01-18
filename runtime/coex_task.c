/*
 * Coex Task Runtime Implementation
 *
 * Provides pthread-based task spawning, joining, and cancellation
 * for Coex structured concurrency.
 */

/* Enable POSIX features (clock_gettime, etc.) on Linux with -std=c11 */
#define _POSIX_C_SOURCE 199309L

#include "coex_task.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <time.h>

/* ============================================================
 * Internal Structures
 * ============================================================ */

/*
 * Thread start argument - wraps entry function and closure
 * so pthread_create can receive a single void* argument.
 */
typedef struct ThreadStartArg {
    TaskEntryFn entry;
    TaskClosure* closure;
} ThreadStartArg;

/*
 * SharedWaiter - Used by coex_task_wait_any for efficient notification.
 * Multiple closures can register the same SharedWaiter, and any completion
 * will signal it immediately.
 */
typedef struct SharedWaiter {
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int completed_index;  // Index of first completed task, or -1
} SharedWaiter;

/* ============================================================
 * Internal Functions
 * ============================================================ */

/*
 * Thread entry point called by pthread_create.
 * Unwraps arguments and calls the task entry function.
 */
static void* thread_start_routine(void* arg) {
    ThreadStartArg* start_arg = (ThreadStartArg*)arg;
    TaskEntryFn entry = start_arg->entry;
    TaskClosure* closure = start_arg->closure;

    /* Free the start argument - no longer needed */
    free(start_arg);

    /* Call the task entry function (compiler-generated trampoline) */
    entry(closure);

    return NULL;
}

/* ============================================================
 * Core Task Functions
 * ============================================================ */

TaskClosure* coex_task_closure_alloc(size_t params_size) {
    /* Allocate closure */
    TaskClosure* closure = (TaskClosure*)malloc(sizeof(TaskClosure));
    if (!closure) {
        fprintf(stderr, "coex_task: failed to allocate TaskClosure\n");
        abort();
    }

    /* Allocate params buffer if needed */
    if (params_size > 0) {
        closure->params = malloc(params_size);
        if (!closure->params) {
            fprintf(stderr, "coex_task: failed to allocate params buffer\n");
            free(closure);
            abort();
        }
        memset(closure->params, 0, params_size);
    } else {
        closure->params = NULL;
    }

    /* Initialize fields */
    closure->result = NULL;
    closure->exception = NULL;
    atomic_store(&closure->cancelled, false);
    atomic_store(&closure->completed, false);

    /* Initialize synchronization primitives */
    pthread_mutex_init(&closure->mutex, NULL);
    pthread_cond_init(&closure->cond, NULL);
    closure->shared_waiter = NULL;

    return closure;
}

void coex_task_closure_free(TaskClosure* closure) {
    if (!closure) return;

    /* Destroy synchronization primitives */
    pthread_mutex_destroy(&closure->mutex);
    pthread_cond_destroy(&closure->cond);

    /* Free params buffer */
    if (closure->params) {
        free(closure->params);
    }

    /* Free closure */
    free(closure);
}

CoexThreadHandle coex_task_spawn(TaskEntryFn entry, TaskClosure* closure) {
    pthread_t thread;

    /* Allocate start argument */
    ThreadStartArg* start_arg = (ThreadStartArg*)malloc(sizeof(ThreadStartArg));
    if (!start_arg) {
        fprintf(stderr, "coex_task: failed to allocate thread start arg\n");
        abort();
    }
    start_arg->entry = entry;
    start_arg->closure = closure;

    /* Create thread */
    int rc = pthread_create(&thread, NULL, thread_start_routine, start_arg);
    if (rc != 0) {
        fprintf(stderr, "coex_task: pthread_create failed with error %d\n", rc);
        free(start_arg);
        abort();
    }

    return thread;
}

void coex_task_join(CoexThreadHandle thread) {
    int rc = pthread_join(thread, NULL);
    if (rc != 0) {
        fprintf(stderr, "coex_task: pthread_join failed with error %d\n", rc);
        /* Don't abort - thread may have already exited */
    }
}

/* ============================================================
 * Cancellation
 * ============================================================ */

void coex_task_cancel(TaskClosure* closure) {
    atomic_store(&closure->cancelled, true);
}

bool coex_task_is_cancelled(TaskClosure* closure) {
    return atomic_load(&closure->cancelled);
}

/* ============================================================
 * Completion Signaling
 * ============================================================ */

void coex_task_signal_complete(TaskClosure* closure) {
    pthread_mutex_lock(&closure->mutex);
    atomic_store(&closure->completed, true);
    pthread_cond_broadcast(&closure->cond);

    /* Also signal shared waiter if present (for wait_any) */
    SharedWaiter* waiter = closure->shared_waiter;
    pthread_mutex_unlock(&closure->mutex);

    if (waiter != NULL) {
        pthread_mutex_lock(&waiter->mutex);
        pthread_cond_signal(&waiter->cond);
        pthread_mutex_unlock(&waiter->mutex);
    }
}

void coex_task_wait_complete(TaskClosure* closure) {
    pthread_mutex_lock(&closure->mutex);
    while (!atomic_load(&closure->completed)) {
        pthread_cond_wait(&closure->cond, &closure->mutex);
    }
    pthread_mutex_unlock(&closure->mutex);
}

/* ============================================================
 * Collection Operations
 * ============================================================ */

int coex_task_wait_any(TaskClosure** closures, int count) {
    if (count <= 0) {
        return -1;
    }

    /* First check if any task is already complete */
    for (int i = 0; i < count; i++) {
        if (atomic_load(&closures[i]->completed)) {
            return i;
        }
    }

    /*
     * No task complete yet - set up a shared waiter so any completion
     * will wake us immediately.
     */
    SharedWaiter waiter;
    pthread_mutex_init(&waiter.mutex, NULL);
    pthread_cond_init(&waiter.cond, NULL);
    waiter.completed_index = -1;

    /* Register shared waiter with all closures */
    for (int i = 0; i < count; i++) {
        pthread_mutex_lock(&closures[i]->mutex);
        closures[i]->shared_waiter = &waiter;
        pthread_mutex_unlock(&closures[i]->mutex);
    }

    int result = -1;

    /* Wait loop - any completion signals our shared waiter */
    pthread_mutex_lock(&waiter.mutex);
    while (result == -1) {
        /* Check for completions */
        for (int i = 0; i < count; i++) {
            if (atomic_load(&closures[i]->completed)) {
                result = i;
                break;
            }
        }

        if (result == -1) {
            /* Wait for signal from any completing task */
            pthread_cond_wait(&waiter.cond, &waiter.mutex);
        }
    }
    pthread_mutex_unlock(&waiter.mutex);

    /* Unregister shared waiter from all closures */
    for (int i = 0; i < count; i++) {
        pthread_mutex_lock(&closures[i]->mutex);
        closures[i]->shared_waiter = NULL;
        pthread_mutex_unlock(&closures[i]->mutex);
    }

    /* Clean up */
    pthread_mutex_destroy(&waiter.mutex);
    pthread_cond_destroy(&waiter.cond);

    return result;
}

void coex_task_wait_all(TaskClosure** closures, int count) {
    for (int i = 0; i < count; i++) {
        coex_task_wait_complete(closures[i]);
    }
}

/* ============================================================
 * Safepoint Support (TLS-based)
 * ============================================================ */

/*
 * Thread-local storage for current task's closure.
 * NULL when not executing within a task context.
 */
static __thread TaskClosure* current_task_closure = NULL;

void coex_task_set_current(TaskClosure* closure) {
    current_task_closure = closure;
}

TaskClosure* coex_task_get_current(void) {
    return current_task_closure;
}

int coex_task_check_safepoint(void) {
    TaskClosure* closure = current_task_closure;
    if (closure == NULL) {
        /* Not in a task context - no cancellation possible */
        return 0;
    }
    return atomic_load(&closure->cancelled) ? 1 : 0;
}
