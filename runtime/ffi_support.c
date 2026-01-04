/*
 * Coex FFI Support Library Implementation
 *
 * Provides runtime support for foreign function interface.
 * See ffi_support.h for API documentation.
 */

#include "ffi_support.h"
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

/* ========================================================================
 * Configuration
 * ======================================================================== */

/* Maximum concurrent FFI instances */
#define MAX_FFI_INSTANCES 1024

/* Maximum handles per instance */
#define MAX_HANDLES_PER_INSTANCE 4096

/* Arena block size */
#define ARENA_BLOCK_SIZE (64 * 1024)  /* 64KB blocks */

/* Maximum total FFI memory (for backpressure) */
#define MAX_FFI_MEMORY (256 * 1024 * 1024)  /* 256MB */


/* ========================================================================
 * Internal Structures
 * ======================================================================== */

/* Arena block for temporary allocations */
typedef struct ArenaBlock {
    struct ArenaBlock* next;
    size_t size;
    size_t used;
    char data[];  /* Flexible array member */
} ArenaBlock;

/* Handle table entry */
typedef struct {
    void* ptr;
    int in_use;
} HandleEntry;

/* FFI instance */
typedef struct {
    int in_use;
    char library_name[64];

    /* Handle table */
    HandleEntry handles[MAX_HANDLES_PER_INSTANCE];
    int64_t next_handle;

    /* Arena allocator */
    ArenaBlock* arena_head;
    ArenaBlock* arena_current;

    /* GC coordination */
    int in_foreign_code;

    /* Thread that owns this instance */
    pthread_t owner_thread;
} FFIInstance;


/* ========================================================================
 * Global State
 * ======================================================================== */

/* Instance table */
static FFIInstance instances[MAX_FFI_INSTANCES];
static pthread_mutex_t instances_lock = PTHREAD_MUTEX_INITIALIZER;
static int64_t active_instance_count = 0;
static size_t total_ffi_memory = 0;

/* Thread-local state for tracking if we're in FFI */
static __thread int64_t current_instance_id = 0;
static __thread int in_ffi = 0;


/* ========================================================================
 * Internal Helpers
 * ======================================================================== */

static FFIInstance* get_instance(int64_t instance_id) {
    if (instance_id <= 0 || instance_id > MAX_FFI_INSTANCES) {
        return NULL;
    }
    FFIInstance* inst = &instances[instance_id - 1];
    if (!inst->in_use) {
        return NULL;
    }
    return inst;
}

static ArenaBlock* arena_new_block(size_t min_size) {
    size_t block_size = min_size > ARENA_BLOCK_SIZE ? min_size : ARENA_BLOCK_SIZE;
    ArenaBlock* block = (ArenaBlock*)malloc(sizeof(ArenaBlock) + block_size);
    if (!block) return NULL;

    block->next = NULL;
    block->size = block_size;
    block->used = 0;

    __atomic_add_fetch(&total_ffi_memory, sizeof(ArenaBlock) + block_size, __ATOMIC_SEQ_CST);

    return block;
}

static void arena_free_all(ArenaBlock* head) {
    while (head) {
        ArenaBlock* next = head->next;
        __atomic_sub_fetch(&total_ffi_memory, sizeof(ArenaBlock) + head->size, __ATOMIC_SEQ_CST);
        free(head);
        head = next;
    }
}


/* ========================================================================
 * FFI Instance Management
 * ======================================================================== */

int64_t coex_ffi_instance_create(const char* library_name) {
    /* Check backpressure */
    if (coex_ffi_can_allocate(ARENA_BLOCK_SIZE) != 0) {
        return COEX_FFI_RESOURCE_EXHAUSTED;
    }

    pthread_mutex_lock(&instances_lock);

    /* Find free slot */
    int64_t slot = -1;
    for (int i = 0; i < MAX_FFI_INSTANCES; i++) {
        if (!instances[i].in_use) {
            slot = i;
            break;
        }
    }

    if (slot < 0) {
        pthread_mutex_unlock(&instances_lock);
        return -1;  /* Max instances reached */
    }

    FFIInstance* inst = &instances[slot];
    memset(inst, 0, sizeof(FFIInstance));
    inst->in_use = 1;
    inst->next_handle = 1;
    inst->owner_thread = pthread_self();

    /* Copy library name */
    if (library_name) {
        strncpy(inst->library_name, library_name, sizeof(inst->library_name) - 1);
    }

    /* Initialize arena */
    inst->arena_head = arena_new_block(ARENA_BLOCK_SIZE);
    inst->arena_current = inst->arena_head;

    if (!inst->arena_head) {
        inst->in_use = 0;
        pthread_mutex_unlock(&instances_lock);
        return -2;  /* Memory allocation failed */
    }

    active_instance_count++;
    pthread_mutex_unlock(&instances_lock);

    return slot + 1;  /* Instance IDs are 1-based */
}

void coex_ffi_instance_destroy(int64_t instance_id) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst) return;

    pthread_mutex_lock(&instances_lock);

    /* Free arena */
    arena_free_all(inst->arena_head);

    /* Free any remaining handles that have pointers */
    for (int i = 0; i < MAX_HANDLES_PER_INSTANCE; i++) {
        if (inst->handles[i].in_use && inst->handles[i].ptr) {
            /* Note: We don't free the pointer - caller is responsible */
            inst->handles[i].in_use = 0;
            inst->handles[i].ptr = NULL;
        }
    }

    inst->in_use = 0;
    active_instance_count--;

    pthread_mutex_unlock(&instances_lock);
}

void* coex_ffi_instance_get_arena(int64_t instance_id) {
    FFIInstance* inst = get_instance(instance_id);
    return inst ? inst->arena_current : NULL;
}

int coex_ffi_instance_valid(int64_t instance_id) {
    return get_instance(instance_id) != NULL;
}


/* ========================================================================
 * Handle Table
 * ======================================================================== */

int64_t coex_ffi_handle_alloc(int64_t instance_id, void* ptr) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst) return -1;
    if (!ptr) return -3;

    /* Find free handle slot */
    for (int i = 0; i < MAX_HANDLES_PER_INSTANCE; i++) {
        int64_t handle = inst->next_handle;
        int slot = (handle - 1) % MAX_HANDLES_PER_INSTANCE;

        if (!inst->handles[slot].in_use) {
            inst->handles[slot].ptr = ptr;
            inst->handles[slot].in_use = 1;
            inst->next_handle = handle + 1;
            return handle;
        }

        inst->next_handle++;
    }

    return -2;  /* Handle table full */
}

void* coex_ffi_handle_get(int64_t instance_id, int64_t handle) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst || handle <= 0) return NULL;

    int slot = (handle - 1) % MAX_HANDLES_PER_INSTANCE;
    if (!inst->handles[slot].in_use) return NULL;

    return inst->handles[slot].ptr;
}

void coex_ffi_handle_free(int64_t instance_id, int64_t handle) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst || handle <= 0) return;

    int slot = (handle - 1) % MAX_HANDLES_PER_INSTANCE;
    inst->handles[slot].in_use = 0;
    inst->handles[slot].ptr = NULL;
}

void coex_ffi_handle_free_ptr(int64_t instance_id, int64_t handle) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst || handle <= 0) return;

    int slot = (handle - 1) % MAX_HANDLES_PER_INSTANCE;
    if (inst->handles[slot].in_use && inst->handles[slot].ptr) {
        free(inst->handles[slot].ptr);
    }
    inst->handles[slot].in_use = 0;
    inst->handles[slot].ptr = NULL;
}


/* ========================================================================
 * GC Coordination
 * ======================================================================== */

void coex_ffi_enter(int64_t instance_id) {
    FFIInstance* inst = get_instance(instance_id);
    if (inst) {
        inst->in_foreign_code = 1;
    }
    current_instance_id = instance_id;
    in_ffi = 1;
}

void coex_ffi_exit(int64_t instance_id) {
    FFIInstance* inst = get_instance(instance_id);
    if (inst) {
        inst->in_foreign_code = 0;
    }
    in_ffi = 0;
}

int coex_ffi_in_foreign_code(void) {
    return in_ffi;
}


/* ========================================================================
 * Resource Backpressure
 * ======================================================================== */

int coex_ffi_can_allocate(size_t estimated_size) {
    size_t current = __atomic_load_n(&total_ffi_memory, __ATOMIC_SEQ_CST);
    if (current + estimated_size > MAX_FFI_MEMORY) {
        return COEX_FFI_RESOURCE_EXHAUSTED;
    }
    return 0;
}

int64_t coex_ffi_instance_count(void) {
    return __atomic_load_n(&active_instance_count, __ATOMIC_SEQ_CST);
}


/* ========================================================================
 * Arena Allocation
 * ======================================================================== */

void* coex_ffi_arena_alloc(int64_t instance_id, size_t size) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst || size == 0) return NULL;

    /* Align size to 8 bytes */
    size = (size + 7) & ~7;

    ArenaBlock* block = inst->arena_current;

    /* Check if current block has space */
    if (block && block->used + size <= block->size) {
        void* ptr = block->data + block->used;
        block->used += size;
        return ptr;
    }

    /* Need new block */
    ArenaBlock* new_block = arena_new_block(size);
    if (!new_block) return NULL;

    /* Link to chain */
    if (block) {
        block->next = new_block;
    } else {
        inst->arena_head = new_block;
    }
    inst->arena_current = new_block;

    void* ptr = new_block->data;
    new_block->used = size;
    return ptr;
}

void coex_ffi_arena_reset(int64_t instance_id) {
    FFIInstance* inst = get_instance(instance_id);
    if (!inst) return;

    /* Keep first block, free the rest */
    ArenaBlock* head = inst->arena_head;
    if (head) {
        arena_free_all(head->next);
        head->next = NULL;
        head->used = 0;
        inst->arena_current = head;
    }
}
