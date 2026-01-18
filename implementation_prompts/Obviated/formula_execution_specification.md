# Formula Execution Substrate Specification

## Overview

Formulas in Coex are pure, terminating functions designed for parallel execution. The primary target is GPU offload, where each formula invocation maps to a shader invocation or compute kernel. However, not all machines have GPUs, and not all formula invocations are worth the dispatch overhead. This specification defines a unified execution substrate that supports CPU thread pools, GPU offload, and hybrid execution, with the work queue as the central abstraction.

## Design Principles

**Semantic Invisibility.** The execution substrate is invisible to the programmer. Whether a formula runs on CPU, GPU, or both, the observable behavior is identical: the same inputs produce the same outputs. The only differences are performance characteristics.

**Work as Data.** A formula invocation is reified as a work item—a passive data structure containing everything needed to execute the computation. Work items are enqueued, dequeued, and executed by workers without awareness of which worker (CPU thread or GPU) will process them.

**Static Boundedness.** The compiler's existing guarantees—manifest loop bounds and acyclic call graphs—ensure that any formula invocation generates a statically bounded amount of work. The parallel execution substrate relies on this property for termination and deadlock freedom.

**Unified Queue, Heterogeneous Workers.** A single logical work queue feeds multiple worker types. CPU workers are OS threads that execute work items directly. GPU workers are dispatch threads that batch compatible work items and submit them to GPU compute pipelines. The scheduler decides which worker type handles which work based on configurable heuristics.

## Work Item Structure

A work item encapsulates a single formula invocation:

```
WorkItem:
    formula_id    : u64          # Identifies which formula to execute
    arguments     : Handle       # Handle to argument tuple on heap
    result_slot   : *mut Handle  # Where to write the result handle
    completion    : *AtomicU64   # Atomic counter for join synchronization
    flags         : u32          # Execution hints (GPU-eligible, priority, etc.)
```

The `formula_id` is a compile-time constant that indexes into a table of formula implementations. For CPU execution, this maps to a function pointer. For GPU execution, this identifies a compiled shader or kernel.

The `arguments` field is a handle to a heap-allocated tuple containing the formula's parameters. Using a handle (rather than a raw pointer) ensures the arguments remain valid across GC cycles and are scannable as roots if collection occurs during execution.

The `result_slot` is a pointer to where the result handle should be written. For bulk operations like `map`, this points into a pre-allocated result array. The caller is responsible for allocating result storage before enqueueing work.

The `completion` pointer references an atomic counter shared across a batch of related work items. Each worker decrements this counter upon completing a work item. The caller waits for the counter to reach zero, indicating all results are ready.

The `flags` field carries hints for the scheduler: whether the formula is GPU-eligible (some formulas may use features not available on GPU), relative priority, estimated cost, etc.

## Work Queue Architecture

### Logical Structure

The work queue is logically a single FIFO queue with multiple consumers. Work items enter at one end and workers of all types compete to dequeue from the other. In practice, the implementation may use multiple physical queues for efficiency, but the abstraction presented to the rest of the system is a single submission point.

### Physical Implementation

For CPU workers, a work-stealing deque topology provides good cache locality and load balancing:

```
Per-Worker State:
    local_deque   : Deque<WorkItem>   # Local double-ended queue
    rng_state     : u64               # For random victim selection

Global State:
    worker_deques : []*Deque<WorkItem>  # Pointers to all worker deques
    worker_count  : usize               # Number of CPU workers
    global_queue  : Queue<WorkItem>     # Overflow/initial submission queue
```

Submission enqueues to the global queue. Workers first check their local deque (LIFO for cache locality), then the global queue, then attempt to steal from random victims (FIFO from victim's deque to balance load).

For GPU workers, a batching queue accumulates work items until a threshold is reached or a timeout expires, then dispatches them as a single GPU submission:

```
GPU Dispatcher State:
    pending_batch : Vec<WorkItem>     # Accumulating work items
    batch_limit   : usize             # Max items per dispatch
    timeout_ns    : u64               # Max wait before dispatch
    last_submit   : u64               # Timestamp of last batch submission
```

### Queue Operations

**submit(items: &[WorkItem])** — Enqueue one or more work items for execution. For bulk operations, submit all items in a single call to reduce synchronization overhead. Returns immediately; does not wait for completion.

**submit_and_wait(items: &[WorkItem])** — Convenience wrapper that submits items and blocks until all complete. Equivalent to submit followed by waiting on the completion counter.

## CPU Worker Implementation

Each CPU worker is an OS thread that runs a simple loop:

```
fn worker_main(worker_id: usize):
    register_with_gc()  # Set up shadow stack, join thread registry
    
    loop:
        item = try_dequeue_local()
              ?? try_dequeue_global()
              ?? try_steal_from_random_victim()
        
        if item is None:
            park_until_notified()
            continue
        
        execute_formula(item)
        
        # Signal completion
        old = item.completion.fetch_sub(1)
        if old == 1:
            wake_waiter(item.completion)
```

The `execute_formula` function indexes into the formula table, retrieves the function pointer, and calls it with the arguments:

```
fn execute_formula(item: WorkItem):
    formula_fn = FORMULA_TABLE[item.formula_id]
    result = formula_fn(item.arguments)
    *item.result_slot = result
```

Because formulas are guaranteed to terminate and never suspend, execution is straightforward: call the function, write the result, done. No continuation capture, no state machine, no complexity.

### Worker Count

The default worker count equals the number of physical CPU cores minus one (reserving one core for the main thread and GPU dispatch). This is configurable at startup. Workers are created once at program initialization and persist for the program's lifetime.

### GC Integration

CPU workers are full participants in the GC system. Each worker has its own shadow stack for tracking live handles during formula execution. Before collection, the GC waits for all workers to reach safepoints (between work items, never mid-formula). The handle-based architecture ensures that arguments and results remain valid across collections.

Because formulas cannot call `await`, `send`, or `receive`, they have no suspension points. A worker executing a formula will reach a safepoint (work item completion) within bounded time, determined by the formula's termination guarantee. This prevents GC stalls from long-running work items.

## GPU Worker Implementation

The GPU dispatch thread monitors the pending batch and submits to the GPU when conditions are met:

```
fn gpu_dispatcher_main():
    loop:
        item = try_dequeue_gpu_eligible()
        
        if item is Some:
            pending_batch.push(item)
        
        should_dispatch = pending_batch.len() >= batch_limit
                       || (pending_batch.len() > 0 
                           && now() - last_submit > timeout_ns)
        
        if should_dispatch:
            dispatch_to_gpu(pending_batch)
            pending_batch.clear()
            last_submit = now()
        
        if item is None and pending_batch.is_empty():
            park_until_notified()
```

### GPU Dispatch

GPU dispatch involves marshaling arguments to GPU-accessible memory, submitting the compute shader or kernel, and arranging for results to be written back:

```
fn dispatch_to_gpu(items: &[WorkItem]):
    # Group by formula_id (same kernel)
    batches = group_by_formula(items)
    
    for (formula_id, batch) in batches:
        kernel = GPU_KERNEL_TABLE[formula_id]
        
        # Upload arguments
        arg_buffer = gpu_allocate(batch.len() * arg_size(formula_id))
        for (i, item) in batch.enumerate():
            copy_to_gpu(arg_buffer, i, item.arguments)
        
        # Allocate result buffer
        result_buffer = gpu_allocate(batch.len() * result_size(formula_id))
        
        # Submit kernel
        gpu_submit(kernel, arg_buffer, result_buffer, batch.len())
        
        # Enqueue completion handler
        gpu_on_complete(result_buffer, batch, || {
            for (i, item) in batch.enumerate():
                *item.result_slot = copy_from_gpu(result_buffer, i)
                old = item.completion.fetch_sub(1)
                if old == 1:
                    wake_waiter(item.completion)
        })
```

The GPU completion handler runs asynchronously when the GPU signals completion. It copies results back to CPU-accessible handles and signals completion to waiters.

### GPU Eligibility

Not all formulas can run on GPU. The compiler marks each formula with GPU eligibility based on:

- **Supported operations**: GPU kernels support arithmetic, comparisons, basic math functions, and structured control flow. Features like arbitrary heap allocation, string manipulation, or complex pattern matching may not be available.

- **Data types**: GPU execution works best with fixed-size numeric types. Formulas operating on variable-length collections or complex nested structures may be CPU-only.

- **Code size**: Very complex formulas may exceed GPU kernel limits or suffer from register pressure. The compiler may mark these as CPU-preferred.

The scheduler respects these markings. GPU-ineligible work items are never sent to the GPU dispatcher.

## Hybrid Scheduling

With both CPU and GPU workers consuming from the same logical queue, the scheduler must decide how to partition work. Several strategies are available:

### Size-Based Partitioning

Small batches (below a threshold, e.g., 1000 items) go to CPU workers; large batches go to GPU. The rationale is that GPU dispatch has fixed overhead, so small batches don't amortize it well.

```
fn submit_parallel_map(formula_id: u64, items: &[Handle]) -> Vec<Handle>:
    if items.len() < GPU_THRESHOLD || !is_gpu_eligible(formula_id):
        return submit_to_cpu(formula_id, items)
    else:
        return submit_to_gpu(formula_id, items)
```

### Work Splitting

For very large batches, split between GPU and CPU to utilize all available compute:

```
fn submit_parallel_map(formula_id: u64, items: &[Handle]) -> Vec<Handle>:
    if items.len() < GPU_THRESHOLD || !is_gpu_eligible(formula_id):
        return submit_to_cpu(formula_id, items)
    
    # Split: 80% GPU, 20% CPU (tunable)
    split_point = items.len() * 4 / 5
    
    gpu_items = items[..split_point]
    cpu_items = items[split_point..]
    
    # Submit both, wait for both
    completion = AtomicU64::new(items.len())
    results = allocate_result_array(items.len())
    
    submit_to_gpu_async(formula_id, gpu_items, &results[..split_point], &completion)
    submit_to_cpu_async(formula_id, cpu_items, &results[split_point..], &completion)
    
    wait_for_completion(&completion)
    return results
```

### Adaptive Scheduling

Monitor actual throughput and adjust the split ratio dynamically:

```
Global State:
    gpu_throughput  : AtomicU64   # Items/second on GPU (smoothed)
    cpu_throughput  : AtomicU64   # Items/second on CPU (smoothed)

fn compute_split_ratio() -> f64:
    gpu = gpu_throughput.load()
    cpu = cpu_throughput.load()
    return gpu / (gpu + cpu)  # Fraction to send to GPU
```

This allows the runtime to adapt to different hardware configurations and formula characteristics without programmer intervention.

## Nested Parallelism

When a formula calls another parallel operation (e.g., `nested.map(g)` inside `items.map(f)`), the nested work items are enqueued to the same work queue. Because formulas form a DAG with no cycles, the nesting depth is statically bounded.

The work-stealing topology handles this naturally: nested work items enter the local deque, and the same worker can continue executing them (good for cache locality) or other workers can steal them (good for load balancing).

For GPU execution, nested parallelism is more complex. Options include:

1. **Flatten at compile time**: If the compiler can determine the nested structure statically, it may be able to generate a single kernel that handles both levels.

2. **CPU fallback for inner levels**: The outer `map` runs on GPU, but any nested `map` calls within the formula execute on CPU. This is conservative but simple.

3. **Dynamic parallelism**: Some GPUs support launching kernels from within kernels. This maps well to nested `map` but is not universally available.

The initial implementation should use option 2 (CPU fallback) for simplicity, with options 1 and 3 as future optimizations.

## Integration with Formula Compilation

The compiler generates two artifacts for each formula:

1. **CPU implementation**: A native function following the standard Coex calling convention, compiled to machine code via LLVM.

2. **GPU implementation** (if eligible): A compute shader (SPIR-V, DXIL, or Metal IR depending on platform) implementing the same logic.

Both implementations are registered in their respective tables at program startup:

```
# Generated at compile time
FORMULA_TABLE: [fn(Handle) -> Handle] = [
    formula_0_cpu,
    formula_1_cpu,
    formula_2_cpu,
    ...
]

GPU_KERNEL_TABLE: [GpuKernel] = [
    load_kernel("formula_0.spv"),
    null,  # formula_1 not GPU-eligible
    load_kernel("formula_2.spv"),
    ...
]
```

The `formula_id` indexes into both tables. A null entry in the GPU table indicates the formula is CPU-only.

## Synchronization and Memory Model

### Completion Signaling

Work items within a batch share a completion counter. The counter is initialized to the batch size before submission. Each worker decrements the counter upon completing its item. When the counter reaches zero, the batch is complete.

```
fn wait_for_completion(counter: *AtomicU64):
    while counter.load(Acquire) > 0:
        park()  # Woken by final worker
```

The final worker (the one whose decrement transitions the counter to zero) is responsible for waking any thread waiting on completion.

### Memory Ordering

Formula execution follows Coex's sequential consistency model. All heap accesses through handles are sequentially consistent. The work queue itself uses acquire-release ordering for efficiency:

- **Enqueue**: Release semantics (ensures work item writes are visible)
- **Dequeue**: Acquire semantics (ensures work item reads see enqueued values)
- **Completion**: Release on decrement, acquire on wait

### Result Visibility

When `submit_and_wait` returns, all results are guaranteed visible. The completion counter's acquire load synchronizes with each worker's release decrement, which in turn synchronizes with each worker's result write.

## Error Handling

Formulas, being pure and total, do not throw exceptions or panic in normal execution. However, certain runtime errors may occur:

- **Out of memory**: Heap allocation during formula execution may fail. The formula execution is aborted, and an OOM error propagates to the caller.

- **Stack overflow**: Deeply nested formula calls may exhaust stack space. Workers run with large stacks (e.g., 8MB), but this is not unlimited.

- **GPU errors**: Shader compilation failure, device lost, timeout. The GPU dispatcher handles these by falling back to CPU execution for affected work items.

All error handling is internal to the substrate. The programmer sees either successful results or a propagated error from the parallel operation.

## Performance Considerations

### Granularity

The work item overhead (enqueue, dequeue, completion signaling) is non-zero. Very fine-grained formulas (e.g., `x => x + 1`) may not benefit from parallelization. The compiler should estimate formula cost and potentially inline trivial formulas rather than parallelizing them.

Heuristics for parallelization decisions:

- **Minimum batch size**: Don't parallelize `map` over fewer than N items (e.g., N=64)
- **Minimum formula cost**: Don't parallelize formulas below a cost threshold
- **Combined threshold**: Parallelize if `batch_size * formula_cost > threshold`

### Cache Efficiency

Work stealing biases toward LIFO execution on local deques, which improves cache locality: recently enqueued items (from nested parallelism) are processed first, while their arguments are still hot.

For GPU execution, batching amortizes dispatch overhead and improves memory coalescing: adjacent work items often access adjacent data.

### Avoiding Contention

The global queue is a potential contention point. In high-throughput scenarios, most work should flow through local deques (enqueued by nested calls, stolen by idle workers) rather than the global queue.

Consider sharded global queues if profiling reveals contention: hash submitting thread ID to select a queue, reducing lock contention at the cost of potential load imbalance.

## Future Extensions

### Priority Scheduling

Attach priorities to work items. High-priority work (e.g., interactive formula evaluations) jumps ahead of background computation.

### Cancellation

Allow callers to cancel in-flight work. Requires cooperative checking: workers periodically check a cancellation flag and abort early if set.

### Affinity Hints

Allow the compiler or programmer to hint that certain formulas prefer CPU (e.g., memory-bound) or GPU (e.g., compute-bound). The scheduler respects hints but may override under load.

### NUMA Awareness

On multi-socket systems, associate workers with NUMA nodes and prefer local memory allocation. Steal from same-node workers before cross-node.

### Distributed Execution

The work queue abstraction could extend to distributed systems: remote workers pull from the queue over the network. This is speculative but architecturally consistent with the design.

## Summary

The formula execution substrate provides a unified abstraction for parallel formula execution across CPU and GPU. Work items are passive data structures; workers are active executors that dequeue and process items. The CPU backend uses a work-stealing thread pool; the GPU backend batches items for efficient dispatch. Hybrid scheduling partitions work based on size, eligibility, and adaptive throughput measurement.

The programmer sees none of this. They write pure formulas, and the runtime executes them in parallel, invisibly and efficiently.
