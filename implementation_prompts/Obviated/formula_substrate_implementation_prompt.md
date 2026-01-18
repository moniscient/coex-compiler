# Implementation Prompt: Formula Execution Substrate (CPU)

## Overview

Implement the CPU-based parallel execution substrate for Coex formulas. This system provides a work-stealing thread pool that executes formula invocations in parallel, with stubs for future GPU offload integration.

The substrate is invisible to Coex programmers—formulas execute in parallel automatically when mapped over collections. The implementation lives entirely in the runtime, with codegen emitting calls to substrate functions rather than direct formula invocations for parallelizable operations.

## Context

Coex formulas have properties that enable safe parallel execution:

1. **Purity**: Formulas cannot perform IO, send/receive on channels, or mutate shared state. Their only effects are computing return values.

2. **Termination**: The compiler guarantees formulas terminate via manifest loop bounds and acyclic call graphs.

3. **DAG structure**: Formulas cannot recurse or mutually recurse. The call graph is a directed acyclic graph with statically bounded depth.

These properties mean formula invocations can be parallelized without synchronization beyond the work queue itself, and nested parallelism cannot deadlock.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Submission API                           │
│  formula_parallel_map(formula_id, inputs, outputs, count)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Global Queue                             │
│  Lock-free MPMC queue for initial work submission               │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Worker 0 │   │ Worker 1 │   │ Worker N │
        │  Deque   │   │  Deque   │   │  Deque   │
        └──────────┘   └──────────┘   └──────────┘
              │               │               │
              └───────────────┴───────────────┘
                    Work Stealing Network
```

## File Organization

Create a new file `coex_formula_runtime.py` alongside `coex_gc.py`. This file generates LLVM IR for the formula execution substrate, following the same patterns as the GC implementation.

```python
"""
Coex Formula Execution Substrate

Provides parallel execution of formulas via a work-stealing thread pool.
Formulas are pure, terminating functions that can safely execute in parallel.

Design:
- Work items are (formula_id, arguments_handle, result_slot, completion_counter)
- Workers are OS threads running a dequeue-execute-signal loop
- Work stealing enables load balancing across workers
- GC integration via shadow stack registration per worker
"""
```

## Data Structures

### Work Item

```
WorkItem (32 bytes, cache-line friendly):
    formula_id    : i64          # Index into formula table
    arguments     : i64          # Handle to argument tuple
    result_slot   : i64*         # Pointer to result handle location
    completion    : i64*         # Pointer to atomic completion counter
```

The work item is a passive data structure. It contains everything needed to execute one formula invocation and signal completion.

### Work Deque (per worker)

```
WorkDeque:
    items         : WorkItem[DEQUE_CAPACITY]  # Circular buffer
    top           : atomic i64                 # Push/pop end (LIFO, owner only)
    bottom        : atomic i64                 # Steal end (FIFO, thieves)
```

Each worker owns one deque. The owner pushes and pops from `top` (LIFO for cache locality). Thieves steal from `bottom` (FIFO for fairness).

### Global Queue

```
GlobalQueue:
    items         : WorkItem[GLOBAL_CAPACITY]  # Circular buffer
    head          : atomic i64                  # Dequeue position
    tail          : atomic i64                  # Enqueue position
```

Initial submissions go to the global queue. Workers check global queue when local deque and stealing both fail.

### Worker State

```
WorkerState:
    id            : i64                # Worker index (0..N-1)
    local_deque   : WorkDeque*         # Pointer to this worker's deque
    rng_state     : i64                # For random victim selection
    is_active     : atomic i64         # 1 if running, 0 if parked
```

### Substrate Global State

```
FormulaSubstrate:
    workers       : WorkerState[MAX_WORKERS]
    worker_deques : WorkDeque[MAX_WORKERS]
    global_queue  : GlobalQueue
    worker_count  : i64                # Actual number of workers
    formula_table : (fn(i64) -> i64)[MAX_FORMULAS]  # formula_id -> function pointer
    shutdown      : atomic i64         # 1 to signal shutdown
    
    # Synchronization for parking
    park_mutex    : pthread_mutex_t
    park_cond     : pthread_cond_t
    parked_count  : atomic i64
```

## Constants

```python
# Sizing
DEQUE_CAPACITY = 1024          # Work items per local deque
GLOBAL_CAPACITY = 4096         # Work items in global queue
MAX_WORKERS = 64               # Maximum worker threads
MAX_FORMULAS = 4096            # Maximum registered formulas

# Thresholds
MIN_PARALLEL_SIZE = 64         # Don't parallelize smaller batches
STEAL_ATTEMPTS = 3             # Random victims to try before parking

# Cache optimization
CACHE_LINE_SIZE = 64           # Bytes per cache line
```

## LLVM IR Generation

### Type Definitions

```python
def _define_substrate_types(self):
    """Define LLVM types for formula substrate structures."""
    
    # WorkItem: {formula_id: i64, arguments: i64, result_slot: i64*, completion: i64*}
    self.work_item_type = ir.LiteralStructType([
        self.i64,      # formula_id
        self.i64,      # arguments (handle)
        self.i64_ptr,  # result_slot
        self.i64_ptr   # completion
    ])
    
    # WorkDeque: {items: [CAPACITY x WorkItem], top: i64, bottom: i64}
    self.work_deque_type = ir.LiteralStructType([
        ir.ArrayType(self.work_item_type, DEQUE_CAPACITY),
        self.i64,  # top (atomic)
        self.i64   # bottom (atomic)
    ])
    
    # GlobalQueue: {items: [CAPACITY x WorkItem], head: i64, tail: i64}
    self.global_queue_type = ir.LiteralStructType([
        ir.ArrayType(self.work_item_type, GLOBAL_CAPACITY),
        self.i64,  # head (atomic)
        self.i64   # tail (atomic)
    ])
    
    # WorkerState: {id: i64, local_deque: deque*, rng_state: i64, is_active: i64}
    self.worker_state_type = ir.LiteralStructType([
        self.i64,                              # id
        self.work_deque_type.as_pointer(),     # local_deque
        self.i64,                              # rng_state
        self.i64                               # is_active (atomic)
    ])
    
    # FormulaSubstrate: main state structure
    self.formula_substrate_type = ir.LiteralStructType([
        ir.ArrayType(self.worker_state_type, MAX_WORKERS),   # workers
        ir.ArrayType(self.work_deque_type, MAX_WORKERS),     # worker_deques
        self.global_queue_type,                               # global_queue
        self.i64,                                             # worker_count
        ir.ArrayType(self.i8_ptr, MAX_FORMULAS),             # formula_table
        self.i64,                                             # shutdown (atomic)
        self.i64,                                             # parked_count (atomic)
    ])
```

### Global Variables

```python
def _declare_substrate_globals(self):
    """Declare global variables for formula substrate."""
    
    # Main substrate state
    self.formula_substrate = ir.GlobalVariable(
        self.module,
        self.formula_substrate_type,
        name="coex_formula_substrate"
    )
    self.formula_substrate.initializer = ir.Constant(
        self.formula_substrate_type, None  # Zero-initialized
    )
    self.formula_substrate.linkage = 'internal'
    
    # Pthread synchronization (allocated at init)
    self.formula_park_mutex = ir.GlobalVariable(
        self.module, self.i8_ptr, name="coex_formula_park_mutex"
    )
    self.formula_park_mutex.initializer = ir.Constant(self.i8_ptr, None)
    
    self.formula_park_cond = ir.GlobalVariable(
        self.module, self.i8_ptr, name="coex_formula_park_cond"
    )
    self.formula_park_cond.initializer = ir.Constant(self.i8_ptr, None)
```

### Function Declarations

```python
def _declare_substrate_functions(self):
    """Declare formula substrate functions."""
    
    # Initialization
    # formula_substrate_init(worker_count: i64) -> void
    init_ty = ir.FunctionType(self.void, [self.i64])
    self.formula_substrate_init = ir.Function(
        self.module, init_ty, name="coex_formula_substrate_init"
    )
    
    # Shutdown
    # formula_substrate_shutdown() -> void
    shutdown_ty = ir.FunctionType(self.void, [])
    self.formula_substrate_shutdown = ir.Function(
        self.module, shutdown_ty, name="coex_formula_substrate_shutdown"
    )
    
    # Formula registration
    # formula_register(formula_id: i64, fn_ptr: i8*) -> void
    register_ty = ir.FunctionType(self.void, [self.i64, self.i8_ptr])
    self.formula_register = ir.Function(
        self.module, register_ty, name="coex_formula_register"
    )
    
    # Parallel map - main entry point
    # formula_parallel_map(formula_id: i64, inputs: i64*, outputs: i64*, count: i64) -> void
    map_ty = ir.FunctionType(self.void, [
        self.i64,      # formula_id
        self.i64_ptr,  # inputs array (handles)
        self.i64_ptr,  # outputs array (handle slots)
        self.i64       # count
    ])
    self.formula_parallel_map = ir.Function(
        self.module, map_ty, name="coex_formula_parallel_map"
    )
    
    # Internal: worker thread main loop
    # formula_worker_main(arg: i8*) -> i8*
    worker_main_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
    self.formula_worker_main = ir.Function(
        self.module, worker_main_ty, name="coex_formula_worker_main"
    )
    
    # Internal: execute single work item
    # formula_execute_item(item: WorkItem*) -> void
    execute_ty = ir.FunctionType(self.void, [self.work_item_type.as_pointer()])
    self.formula_execute_item = ir.Function(
        self.module, execute_ty, name="coex_formula_execute_item"
    )
    
    # Deque operations
    # formula_deque_push(deque: WorkDeque*, item: WorkItem*) -> i1 (success)
    push_ty = ir.FunctionType(self.i1, [
        self.work_deque_type.as_pointer(),
        self.work_item_type.as_pointer()
    ])
    self.formula_deque_push = ir.Function(
        self.module, push_ty, name="coex_formula_deque_push"
    )
    
    # formula_deque_pop(deque: WorkDeque*, out: WorkItem*) -> i1 (success)
    pop_ty = ir.FunctionType(self.i1, [
        self.work_deque_type.as_pointer(),
        self.work_item_type.as_pointer()
    ])
    self.formula_deque_pop = ir.Function(
        self.module, pop_ty, name="coex_formula_deque_pop"
    )
    
    # formula_deque_steal(deque: WorkDeque*, out: WorkItem*) -> i1 (success)
    steal_ty = ir.FunctionType(self.i1, [
        self.work_deque_type.as_pointer(),
        self.work_item_type.as_pointer()
    ])
    self.formula_deque_steal = ir.Function(
        self.module, steal_ty, name="coex_formula_deque_steal"
    )
    
    # Global queue operations
    # formula_global_enqueue(item: WorkItem*) -> i1 (success)
    enqueue_ty = ir.FunctionType(self.i1, [self.work_item_type.as_pointer()])
    self.formula_global_enqueue = ir.Function(
        self.module, enqueue_ty, name="coex_formula_global_enqueue"
    )
    
    # formula_global_dequeue(out: WorkItem*) -> i1 (success)
    dequeue_ty = ir.FunctionType(self.i1, [self.work_item_type.as_pointer()])
    self.formula_global_dequeue = ir.Function(
        self.module, dequeue_ty, name="coex_formula_global_dequeue"
    )
    
    # GPU stubs (for future implementation)
    # formula_gpu_available() -> i1
    gpu_avail_ty = ir.FunctionType(self.i1, [])
    self.formula_gpu_available = ir.Function(
        self.module, gpu_avail_ty, name="coex_formula_gpu_available"
    )
    
    # formula_gpu_dispatch(formula_id: i64, inputs: i64*, outputs: i64*, count: i64) -> void
    gpu_dispatch_ty = ir.FunctionType(self.void, [
        self.i64, self.i64_ptr, self.i64_ptr, self.i64
    ])
    self.formula_gpu_dispatch = ir.Function(
        self.module, gpu_dispatch_ty, name="coex_formula_gpu_dispatch"
    )
```

## Function Implementations

### Substrate Initialization

```python
def _implement_formula_substrate_init(self):
    """
    Initialize the formula execution substrate.
    
    - Allocates pthread synchronization primitives
    - Determines worker count (default: num_cores - 1)
    - Spawns worker threads
    - Each worker registers with GC
    """
    func = self.formula_substrate_init
    func.args[0].name = "requested_workers"
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    # Determine actual worker count
    # Use requested if > 0, else use num_cores - 1
    requested = func.args[0]
    # ... (implement core count detection or use requested)
    
    # Store worker count in substrate
    worker_count_ptr = builder.gep(self.formula_substrate, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 3)  # worker_count field
    ], inbounds=True)
    builder.store(worker_count, worker_count_ptr)
    
    # Allocate and init mutex
    mutex_size = ir.Constant(self.i64, 64)  # pthread_mutex_t is ≤64 bytes
    mutex_mem = builder.call(self.malloc, [mutex_size])
    builder.store(mutex_mem, self.formula_park_mutex)
    builder.call(self.pthread_mutex_init, [mutex_mem, ir.Constant(self.i8_ptr, None)])
    
    # Allocate and init condition variable
    cond_size = ir.Constant(self.i64, 64)
    cond_mem = builder.call(self.malloc, [cond_size])
    builder.store(cond_mem, self.formula_park_cond)
    builder.call(self.pthread_cond_init, [cond_mem, ir.Constant(self.i8_ptr, None)])
    
    # Initialize each worker's state and spawn thread
    # Loop: for i in 0..worker_count
    #   workers[i].id = i
    #   workers[i].local_deque = &worker_deques[i]
    #   workers[i].rng_state = seed_from_id(i)
    #   workers[i].is_active = 1
    #   worker_deques[i].top = 0
    #   worker_deques[i].bottom = 0
    #   pthread_create(&thread, NULL, formula_worker_main, &workers[i])
    
    # ... (implement spawn loop)
    
    builder.ret_void()
```

### Worker Main Loop

```python
def _implement_formula_worker_main(self):
    """
    Worker thread main loop.
    
    1. Register with GC (shadow stack setup)
    2. Loop:
       a. Try pop from local deque
       b. If empty, try global queue
       c. If empty, try steal from random victim
       d. If still empty, park (wait on condition variable)
       e. If got work item, execute it
       f. Check shutdown flag
    3. Unregister from GC
    """
    func = self.formula_worker_main
    func.args[0].name = "arg"
    
    entry = func.append_basic_block("entry")
    main_loop = func.append_basic_block("main_loop")
    try_local = func.append_basic_block("try_local")
    try_global = func.append_basic_block("try_global")
    try_steal = func.append_basic_block("try_steal")
    park_worker = func.append_basic_block("park_worker")
    execute = func.append_basic_block("execute")
    check_shutdown = func.append_basic_block("check_shutdown")
    cleanup = func.append_basic_block("cleanup")
    
    builder = ir.IRBuilder(entry)
    
    # Cast arg to WorkerState*
    worker_state = builder.bitcast(func.args[0], self.worker_state_type.as_pointer())
    
    # Register with GC
    builder.call(self.gc_register_thread, [...])
    
    # Allocate stack slot for work item
    item_slot = builder.alloca(self.work_item_type, name="item")
    
    builder.branch(main_loop)
    
    # Main loop
    builder.position_at_end(main_loop)
    
    # Check shutdown flag first
    shutdown_ptr = builder.gep(self.formula_substrate, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 5)  # shutdown field
    ], inbounds=True)
    shutdown = builder.load(shutdown_ptr)
    is_shutdown = builder.icmp_unsigned("!=", shutdown, ir.Constant(self.i64, 0))
    builder.cbranch(is_shutdown, cleanup, try_local)
    
    # Try local deque
    builder.position_at_end(try_local)
    local_deque_ptr = builder.gep(worker_state, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 1)  # local_deque field
    ], inbounds=True)
    local_deque = builder.load(local_deque_ptr)
    pop_success = builder.call(self.formula_deque_pop, [local_deque, item_slot])
    builder.cbranch(pop_success, execute, try_global)
    
    # Try global queue
    builder.position_at_end(try_global)
    global_success = builder.call(self.formula_global_dequeue, [item_slot])
    builder.cbranch(global_success, execute, try_steal)
    
    # Try stealing (with multiple attempts)
    builder.position_at_end(try_steal)
    # ... implement steal attempts with random victim selection
    # If all attempts fail, branch to park_worker
    # If any succeeds, branch to execute
    
    # Park (wait for work)
    builder.position_at_end(park_worker)
    mutex = builder.load(self.formula_park_mutex)
    cond = builder.load(self.formula_park_cond)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Increment parked count
    parked_ptr = builder.gep(self.formula_substrate, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 6)  # parked_count field
    ], inbounds=True)
    # atomic increment...
    
    # Wait on condition
    builder.call(self.pthread_cond_wait, [cond, mutex])
    
    # Decrement parked count
    # atomic decrement...
    
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(main_loop)
    
    # Execute work item
    builder.position_at_end(execute)
    builder.call(self.formula_execute_item, [item_slot])
    builder.branch(check_shutdown)
    
    # Check shutdown after execution
    builder.position_at_end(check_shutdown)
    builder.branch(main_loop)
    
    # Cleanup and exit
    builder.position_at_end(cleanup)
    builder.call(self.gc_unregister_thread, [...])
    builder.ret(ir.Constant(self.i8_ptr, None))
```

### Execute Work Item

```python
def _implement_formula_execute_item(self):
    """
    Execute a single work item.
    
    1. Load formula function pointer from table
    2. Call formula with arguments handle
    3. Store result handle to result_slot
    4. Atomic decrement completion counter
    5. If counter reached zero, signal waiters
    """
    func = self.formula_execute_item
    func.args[0].name = "item"
    
    entry = func.append_basic_block("entry")
    signal_waiter = func.append_basic_block("signal_waiter")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    item = func.args[0]
    
    # Load formula_id
    formula_id_ptr = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 0)
    ], inbounds=True)
    formula_id = builder.load(formula_id_ptr)
    
    # Load arguments handle
    args_ptr = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 1)
    ], inbounds=True)
    arguments = builder.load(args_ptr)
    
    # Load result_slot pointer
    result_slot_ptr = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 2)
    ], inbounds=True)
    result_slot = builder.load(result_slot_ptr)
    
    # Load completion counter pointer
    completion_ptr = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 3)
    ], inbounds=True)
    completion = builder.load(completion_ptr)
    
    # Get formula function pointer from table
    table_ptr = builder.gep(self.formula_substrate, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 4),  # formula_table field
        formula_id
    ], inbounds=True)
    fn_ptr_raw = builder.load(table_ptr)
    
    # Cast to formula function type: fn(i64) -> i64
    formula_fn_type = ir.FunctionType(self.i64, [self.i64])
    fn_ptr = builder.bitcast(fn_ptr_raw, formula_fn_type.as_pointer())
    
    # Call formula
    result = builder.call(fn_ptr, [arguments])
    
    # Store result
    builder.store(result, result_slot)
    
    # Atomic decrement completion counter
    old_count = builder.atomic_rmw('sub', completion, ir.Constant(self.i64, 1), 'seq_cst')
    
    # If we decremented to zero, signal waiter
    was_one = builder.icmp_unsigned("==", old_count, ir.Constant(self.i64, 1))
    builder.cbranch(was_one, signal_waiter, done)
    
    builder.position_at_end(signal_waiter)
    # Signal condition variable to wake waiter
    cond = builder.load(self.formula_park_cond)
    builder.call(self.pthread_cond_broadcast, [cond])
    builder.branch(done)
    
    builder.position_at_end(done)
    builder.ret_void()
```

### Parallel Map (Main Entry Point)

```python
def _implement_formula_parallel_map(self):
    """
    Execute formula over array of inputs in parallel.
    
    For small batches (< MIN_PARALLEL_SIZE), execute sequentially.
    For larger batches:
    1. Initialize completion counter to count
    2. Enqueue work items to global queue
    3. Wake parked workers
    4. Wait for completion counter to reach zero
    """
    func = self.formula_parallel_map
    func.args[0].name = "formula_id"
    func.args[1].name = "inputs"
    func.args[2].name = "outputs"
    func.args[3].name = "count"
    
    entry = func.append_basic_block("entry")
    sequential = func.append_basic_block("sequential")
    parallel = func.append_basic_block("parallel")
    enqueue_loop = func.append_basic_block("enqueue_loop")
    enqueue_body = func.append_basic_block("enqueue_body")
    enqueue_done = func.append_basic_block("enqueue_done")
    wait_loop = func.append_basic_block("wait_loop")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    formula_id = func.args[0]
    inputs = func.args[1]
    outputs = func.args[2]
    count = func.args[3]
    
    # Check if GPU is available and beneficial (stub for now)
    # gpu_ok = builder.call(self.formula_gpu_available, [])
    # ... (GPU path would go here)
    
    # Check batch size threshold
    min_size = ir.Constant(self.i64, MIN_PARALLEL_SIZE)
    is_small = builder.icmp_unsigned("<", count, min_size)
    builder.cbranch(is_small, sequential, parallel)
    
    # Sequential path for small batches
    builder.position_at_end(sequential)
    # Simple loop: for i in 0..count: outputs[i] = formula(inputs[i])
    seq_i = builder.alloca(self.i64, name="seq_i")
    builder.store(ir.Constant(self.i64, 0), seq_i)
    
    seq_loop = func.append_basic_block("seq_loop")
    seq_body = func.append_basic_block("seq_body")
    seq_done = func.append_basic_block("seq_done")
    
    builder.branch(seq_loop)
    
    builder.position_at_end(seq_loop)
    i_val = builder.load(seq_i)
    seq_continue = builder.icmp_unsigned("<", i_val, count)
    builder.cbranch(seq_continue, seq_body, seq_done)
    
    builder.position_at_end(seq_body)
    # Load input handle
    input_ptr = builder.gep(inputs, [i_val], inbounds=True)
    input_handle = builder.load(input_ptr)
    
    # Get formula function pointer
    table_ptr = builder.gep(self.formula_substrate, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 4),
        formula_id
    ], inbounds=True)
    fn_ptr_raw = builder.load(table_ptr)
    formula_fn_type = ir.FunctionType(self.i64, [self.i64])
    fn_ptr = builder.bitcast(fn_ptr_raw, formula_fn_type.as_pointer())
    
    # Call formula
    result = builder.call(fn_ptr, [input_handle])
    
    # Store result
    output_ptr = builder.gep(outputs, [i_val], inbounds=True)
    builder.store(result, output_ptr)
    
    # Increment and loop
    next_i = builder.add(i_val, ir.Constant(self.i64, 1))
    builder.store(next_i, seq_i)
    builder.branch(seq_loop)
    
    builder.position_at_end(seq_done)
    builder.branch(done)
    
    # Parallel path
    builder.position_at_end(parallel)
    
    # Allocate completion counter on stack
    completion = builder.alloca(self.i64, name="completion")
    builder.store(count, completion)  # Initialize to count
    
    # Allocate work item on stack for reuse
    item = builder.alloca(self.work_item_type, name="item")
    
    # Store formula_id (constant for all items)
    formula_id_slot = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 0)
    ], inbounds=True)
    builder.store(formula_id, formula_id_slot)
    
    # Store completion pointer (same for all items)
    completion_slot = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 3)
    ], inbounds=True)
    builder.store(completion, completion_slot)
    
    # Enqueue loop index
    enq_i = builder.alloca(self.i64, name="enq_i")
    builder.store(ir.Constant(self.i64, 0), enq_i)
    builder.branch(enqueue_loop)
    
    builder.position_at_end(enqueue_loop)
    i_val = builder.load(enq_i)
    enq_continue = builder.icmp_unsigned("<", i_val, count)
    builder.cbranch(enq_continue, enqueue_body, enqueue_done)
    
    builder.position_at_end(enqueue_body)
    
    # Set arguments (input handle for this index)
    input_ptr = builder.gep(inputs, [i_val], inbounds=True)
    input_handle = builder.load(input_ptr)
    args_slot = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 1)
    ], inbounds=True)
    builder.store(input_handle, args_slot)
    
    # Set result_slot (output pointer for this index)
    output_ptr = builder.gep(outputs, [i_val], inbounds=True)
    result_slot = builder.gep(item, [
        ir.Constant(self.i32, 0),
        ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(output_ptr, result_slot)
    
    # Enqueue (copies the item)
    builder.call(self.formula_global_enqueue, [item])
    
    # Increment
    next_i = builder.add(i_val, ir.Constant(self.i64, 1))
    builder.store(next_i, enq_i)
    builder.branch(enqueue_loop)
    
    builder.position_at_end(enqueue_done)
    
    # Wake all parked workers
    cond = builder.load(self.formula_park_cond)
    builder.call(self.pthread_cond_broadcast, [cond])
    
    builder.branch(wait_loop)
    
    # Wait for completion
    builder.position_at_end(wait_loop)
    current = builder.load(completion)
    is_done = builder.icmp_unsigned("==", current, ir.Constant(self.i64, 0))
    
    # If not done, help execute work ourselves
    help_execute = func.append_basic_block("help_execute")
    builder.cbranch(is_done, done, help_execute)
    
    builder.position_at_end(help_execute)
    # Try to dequeue and execute one item
    help_item = builder.alloca(self.work_item_type, name="help_item")
    got_work = builder.call(self.formula_global_dequeue, [help_item])
    
    with builder.if_then(got_work):
        builder.call(self.formula_execute_item, [help_item])
    
    # Brief pause if no work (avoid tight spin)
    # Could use pthread_yield or sched_yield here
    
    builder.branch(wait_loop)
    
    builder.position_at_end(done)
    builder.ret_void()
```

### Work-Stealing Deque Operations

```python
def _implement_formula_deque_push(self):
    """
    Push work item to local deque (owner only).
    
    Lock-free using compare-and-swap on top index.
    Returns false if deque is full.
    """
    func = self.formula_deque_push
    # ... Chase-Lev deque push implementation
    
def _implement_formula_deque_pop(self):
    """
    Pop work item from local deque (owner only).
    
    LIFO order for cache locality.
    Returns false if deque is empty.
    """
    func = self.formula_deque_pop
    # ... Chase-Lev deque pop implementation
    
def _implement_formula_deque_steal(self):
    """
    Steal work item from another worker's deque.
    
    FIFO order (steal from bottom) for fairness.
    Returns false if deque is empty or contention.
    """
    func = self.formula_deque_steal
    # ... Chase-Lev deque steal implementation
```

### GPU Stubs

```python
def _implement_formula_gpu_available(self):
    """
    Check if GPU execution is available.
    
    STUB: Always returns false until GPU backend is implemented.
    """
    func = self.formula_gpu_available
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    builder.ret(ir.Constant(self.i1, 0))  # Always false for now

def _implement_formula_gpu_dispatch(self):
    """
    Dispatch formula batch to GPU.
    
    STUB: Falls back to CPU parallel execution.
    Future implementation will:
    1. Marshal arguments to GPU-accessible memory
    2. Submit compute shader/kernel
    3. Arrange for results to be copied back
    4. Signal completion when GPU finishes
    """
    func = self.formula_gpu_dispatch
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    # Stub: delegate to CPU
    builder.call(self.formula_parallel_map, list(func.args))
    builder.ret_void()
```

## Integration with CodeGen

### Formula Registration

When the compiler encounters a formula declaration, register it with the substrate:

```python
def _generate_formula_decl(self, func_decl: FunctionDecl):
    """Generate LLVM function for formula and register with substrate."""
    
    # Generate the formula function as usual
    llvm_func = self._generate_function(func_decl)
    
    # Assign formula ID
    formula_id = self.next_formula_id
    self.next_formula_id += 1
    self.formula_ids[func_decl.name] = formula_id
    
    # Emit registration call in module init
    # formula_register(formula_id, bitcast(llvm_func, i8*))
    self._emit_formula_registration(formula_id, llvm_func)
    
    return llvm_func
```

### Parallel Map Emission

When generating code for `collection.map(formula)`, emit parallel execution:

```python
def _generate_map_call(self, collection_expr, formula_expr):
    """Generate parallel map over collection with formula."""
    
    # Get formula ID
    formula_name = formula_expr.name  # or extract from lambda
    formula_id = self.formula_ids[formula_name]
    
    # Generate collection
    collection = self._generate_expression(collection_expr)
    
    # Get collection length and element pointer
    length = self._get_collection_length(collection)
    elements = self._get_collection_elements(collection)
    
    # Allocate result array
    results = self._allocate_handle_array(length)
    
    # Call parallel map
    self.builder.call(self.gc.formula_parallel_map, [
        ir.Constant(self.i64, formula_id),
        elements,
        results,
        length
    ])
    
    # Construct result collection from results array
    return self._construct_collection_from_array(results, length)
```

## GC Integration

Workers must register with the GC so their shadow stacks are scanned during collection:

```python
def _worker_gc_registration(self):
    """
    Each worker thread registers with GC at startup.
    
    This ensures:
    1. Worker's shadow stack is tracked
    2. Handles held by in-flight work items are roots
    3. GC waits for workers to reach safepoints
    
    Safepoints occur between work items (never mid-formula).
    """
```

The completion counter wait loop is a natural safepoint—if GC needs to collect, workers finish their current item and pause at the next dequeue attempt.

## Testing Strategy

### Unit Tests

1. **Deque operations**: Push, pop, steal with single and multiple threads
2. **Global queue**: Enqueue, dequeue with concurrent producers/consumers
3. **Work stealing**: Verify load balancing under uneven work distribution
4. **Completion signaling**: Counter decrement and waiter wakeup

### Integration Tests

1. **Simple parallel map**: `[1,2,3,4].map(x => x * 2)` produces `[2,4,6,8]`
2. **Large batch**: Million-element array parallelized correctly
3. **Nested parallelism**: Formula containing inner `.map()` call
4. **Mixed sizes**: Batch below threshold runs sequential, above runs parallel

### Stress Tests

1. **High contention**: Many threads, small deques, frequent stealing
2. **Memory pressure**: GC during parallel execution
3. **Rapid spawn/join**: Many short parallel sections in sequence

### Benchmarks

1. **Speedup curve**: 1, 2, 4, 8 workers on embarrassingly parallel workload
2. **Overhead measurement**: Parallel map vs sequential loop for varying batch sizes
3. **Steal efficiency**: Work distribution metrics under unbalanced loads

## Implementation Order

1. **Phase 1: Sequential foundation**
   - Type definitions and global state
   - Sequential `formula_parallel_map` (no threading)
   - Formula registration
   - Integration with codegen for `.map()` calls

2. **Phase 2: Single worker**
   - Worker main loop (single thread)
   - Global queue operations
   - Execute item
   - Completion signaling

3. **Phase 3: Multi-worker**
   - Worker spawning at init
   - Work-stealing deque
   - Stealing logic with random victim selection
   - Parking and wakeup

4. **Phase 4: GC integration**
   - Worker registration with GC
   - Safepoint handling
   - Testing under memory pressure

5. **Phase 5: GPU stubs**
   - `formula_gpu_available` returning false
   - `formula_gpu_dispatch` delegating to CPU
   - Interface ready for future GPU backend

## Notes for Implementation

### Atomic Operations in llvmlite

```python
# Atomic load
value = builder.load(ptr, atomic=True)
# Or use atomic_rmw for read-modify-write:
old = builder.atomic_rmw('add', ptr, increment, 'seq_cst')

# Atomic compare-and-swap
result = builder.cmpxchg(ptr, expected, desired, 'seq_cst', 'seq_cst')
# result is {old_value, success_bit}
```

### Chase-Lev Deque Reference

The work-stealing deque follows the Chase-Lev algorithm:
- Paper: "Dynamic Circular Work-Stealing Deque" (Chase & Lev, 2005)
- Key insight: Owner uses simple operations; thieves use CAS
- Memory ordering: acquire/release sufficient for most operations

### Debugging Tips

- Add trace output similar to GC tracing infrastructure
- Track work item flow: enqueue → dequeue → execute → complete
- Monitor queue depths and steal rates
- Detect deadlock via timeout on completion wait
